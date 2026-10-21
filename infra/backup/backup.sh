#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# solidAPP · backup de PostgreSQL (T-12 del plan de pendientes)
#
# Qué hace:
#   1. pg_dump en formato custom (-Fc) → comprimido y restaurable con pg_restore.
#   2. Cifrado en reposo con AES-256-CBC (openssl) → nada legible en disco.
#   3. Retención GFS: 7 diarios + 4 semanales + 6 mensuales.
#   4. Copia fuera del host (S3-compatible) si se configura BACKUP_REMOTE.
#   5. Modo --check: sale con código 1 si el último backup es más antiguo que
#      BACKUP_MAX_AGE_HOURS → lo usa la alerta de D3.
#
# Por qué un script y no "docker compose exec db pg_dump" a mano: un backup
# que sólo existe como comando en un wiki no es un backup. Esto se puede
# cron-ear, falla ruidosamente y se puede restaurar.
#
# Uso:
#   ./backup.sh              → hace un backup nuevo
#   ./backup.sh --check      → sólo verifica frescura (para la alerta)
#   ./backup.sh --help
#
# Variables de entorno (ver .env.example):
#   PGHOST, PGPORT, PGUSER, PGDATABASE  → conexión (por defecto al servicio db)
#   BACKUP_DIR                           → dónde dejar los ficheros
#   BACKUP_PASSPHRASE_FILE               → fichero con la passphrase (obligatorio)
#   BACKUP_RETENTION_DAYS/WEEKS/MONTHS   → retención GFS
#   BACKUP_REMOTE                        → destino S3-compatible (opcional)
#   BACKUP_REMOTE_CMD                   → comando de subida (opcional)
#   BACKUP_MAX_AGE_HOURS                → umbral de la alerta (por defecto 26)
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-parking}"
PGDATABASE="${PGDATABASE:-parking}"

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
RETENTION_WEEKS="${BACKUP_RETENTION_WEEKS:-4}"
RETENTION_MONTHS="${BACKUP_RETENTION_MONTHS:-6}"

BACKUP_REMOTE="${BACKUP_REMOTE:-}"
BACKUP_REMOTE_CMD="${BACKUP_REMOTE_CMD:-}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DAY_OF_WEEK="$(date -u +%u)"   # 1=lunes … 7=domingo
DAY_OF_MONTH="$(date -u +%d)"

log()  { printf '[backup] %s\n' "$*" >&2; }
die()  { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

# ── passphrase ──────────────────────────────────────────────────────────────
# La clave NO va en el entorno ni en el repositorio: vive en un fichero
# con permisos 600 (o en el secret manager del host). Sin ella no se
# cifra nada y no se sale con un backup "sin cifrar" colado en el disco.
read_passphrase() {
    if [[ -z "$BACKUP_PASSPHRASE_FILE" || ! -r "$BACKUP_PASSPHRASE_FILE" ]]; then
        die "falta BACKUP_PASSPHRASE_FILE (fichero legible con la passphrase)"
    fi
    PASS_PHRASE="$(cat "$BACKUP_PASSPHRASE_FILE")"
    [[ -n "$PASS_PHRASE" ]] || die "la passphrase está vacía"
    export PASS_PHRASE
}

# ── freshness check (modo --check) ──────────────────────────────────────────
check_freshness() {
    local newest
    newest="$(find "$BACKUP_DIR" -maxdepth 1 -name 'solidapp-*.dump.enc' -printf '%T@ %p\n' 2>/dev/null \
        | sort -nr | head -n1 | cut -d' ' -f2- || true)"
    if [[ -z "$newest" ]]; then
        log "NO HAY NINGÚN BACKUP en $BACKUP_DIR"
        return 2
    fi
    local age_hours
    age_hours=$(( ( $(date -u +%s) - $(stat -c %Y "$newest") ) / 3600 ))
    log "último backup: $newest (hace ${age_hours} h)"
    if (( age_hours > BACKUP_MAX_AGE_HOURS )); then
        log "FECHO: el último backup tiene ${age_hours} h (> ${BACKUP_MAX_AGE_HOURS} h)"
        return 1
    fi
    log "OK: backup reciente"
    return 0
}

# ── retención GFS ───────────────────────────────────────────────────────────
# Se conservan:
#   - los RETENTION_DAYS   más recientes (uno por día)
#   - los RETENTION_WEEKS  más recientes de la semana ISO
#   - los RETENTION_MONTHS más recientes del mes
# El resto se borra. Los ficheros se nombran con la fecha UTC, así que el
# bucket "semanal" es el primero que se ve de cada semana y el "mensual" el
# primero de cada mes.
apply_retention() {
    local daily weekly monthly
    daily="$(find "$BACKUP_DIR" -maxdepth 1 -name 'solidapp-*.dump.enc' -printf '%f\n' | sort -r | head -n "$RETENTION_DAYS")"
    weekly="$(find "$BACKUP_DIR" -maxdepth 1 -name 'solidapp-*.dump.enc' -printf '%f\n' | sort -r | awk -F'-' '!seen[$2]++' | head -n "$RETENTION_WEEKS")"
    monthly="$(find "$BACKUP_DIR" -maxdepth 1 -name 'solidapp-*.dump.enc' -printf '%f\n' | sort -r | awk -F'-' '!seen[$2"-"$3]++' | head -n "$RETENTION_MONTHS")"

    local keep keep_file name
    keep="$(printf '%s\n%s\n%s\n' "$daily" "$weekly" "$monthly" | grep -v '^$' | sort -u)"
    while IFS= read -r name; do
        [[ -n "$name" ]] || continue
        if ! grep -qxF "$name" <<<"$keep"; then
            log "retirando $name"
            rm -f "$BACKUP_DIR/$name"
        fi
    done < <(find "$BACKUP_DIR" -maxdepth 1 -name 'solidapp-*.dump.enc' -printf '%f\n')
}

# ── copia fuera del host ────────────────────────────────────────────────────
# LOPDGDD: el backup no puede vivir sólo en la misma máquina que los datos.
# Con BACKUP_REMOTE + BACKUP_REMOTE_CMD se sube a un S3-compatible (MinIO,
# Backblaze B2, Wasabi…). El comando recibe la ruta local como $1.
upload_remote() {
    if [[ -z "$BACKUP_REMOTE" ]]; then
        log "BACKUP_REMOTE sin configurar: el backup se queda sólo en $BACKUP_DIR"
        return 0
    fi
    if [[ -z "$BACKUP_REMOTE_CMD" ]]; then
        die "BACKUP_REMOTE configurado pero falta BACKUP_REMOTE_CMD"
    fi
    log "subiendo a $BACKUP_REMOTE"
    BACKUP_REMOTE="$BACKUP_REMOTE" bash -c "$BACKUP_REMOTE_CMD" -- "$1"
}

main() {
    case "${1:-}" in
        --help|-h) usage ;;
        --check)
            check_freshness
            exit $?
            ;;
        "") ;;
        *) die "argumento desconocido: $1 (usa --help)" ;;
    esac

    mkdir -p "$BACKUP_DIR"
    read_passphrase

    local raw="$BACKUP_DIR/solidapp-$STAMP.dump"
    local enc="$raw.enc"

    log "volcando $PGDATABASE desde $PGHOST:$PGPORT"
    # -Fc: formato custom → comprimido + restaurable con pg_restore (no pg_restore
    # en modo SQL). Importante: `pg_dump` en formato plain con una BBDD PostGIS
    # pierde la extensión si no se incluye --schema; el formato custom la lleva.
    if ! pg_dump --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" \
        --dbname="$PGDATABASE" --format=custom --compress=9 --no-owner --file="$raw"; then
        rm -f "$raw"
        die "pg_dump falló: no se ha creado ningún backup"
    fi

    log "cifrando (AES-256-CBC)"
    if ! openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
        -in "$raw" -out "$enc" -pass env:PASS_PHRASE; then
        rm -f "$raw"
        die "falló el cifrado"
    fi
    # El volcado en claro se borra siempre: no debe quedar una copia sin cifrar.
    rm -f "$raw"

    # El fichero cifrado debe poder descifrarse: un backup que no se puede
    # leer no sirve para nada. Se verifica en el momento de crearlo.
    #
    # Se descifra a un fichero temporal (no a un pipe: `head -c N` cierra el
    # pipe antes de tiempo y, con `pipefail`, openssl sale con "error writing
    # output file" falseando la verificación). El temporal se borra acto
    # seguido y sólo vive en el directorio de backups, que debe estar cifrado
    # en reposo.
    local verify_dir
    verify_dir="$(mktemp -d "${TMPDIR:-/tmp}/solidapp-verify.XXXXXX")"
    if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -in "$enc" -pass env:PASS_PHRASE -out "$verify_dir/verify.pgdmp"; then
        rm -rf "$verify_dir"
        die "el dump cifrado no se puede descifrar (se aborta: no es un backup válido)"
    fi
    if ! head -c 5 "$verify_dir/verify.pgdmp" | grep -q 'PGDMP'; then
        rm -rf "$verify_dir"
        die "el dump descifrado no tiene la firma PGDMP (se aborta)"
    fi
    rm -rf "$verify_dir"

    log "backup listo: $enc ($(du -h "$enc" | cut -f1))"

    apply_retention
    upload_remote "$enc"

    # El estado del último backup se escribe para que el monitor lo consulte.
    date -u +%Y-%m-%dT%H:%M:%SZ > "$BACKUP_DIR/.last-success"
    log "hecho"
}

main "$@"
