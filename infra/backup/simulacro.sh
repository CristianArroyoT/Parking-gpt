#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# solidAPP · simulacro de restauración (T-12 del plan de pendientes)
#
# "Un backup sin restaurar probado no es un backup" (regla del plan de
# pendientes). La decisión D3 fija que el procedimiento de restauración se
# prueba **cada trimestre**, y hasta ahora ese simulacro era una checklist
# en papel: alguien la repasaba a mano y lo anotaba en un ticket.
#
# Este script es la checklist, ejecutada. Hace, en orden:
#
#   1. backup.sh          → un volcado cifrado nuevo
#   2. el .enc NO es texto plano (si se lee, el backup no está cifrado)
#   3. restore.sh         → restauración en una base limpia, con verificación
#   4. la base restaurada tiene **los mismos datos** que la original
#
# Y deja la base restaurada en pie para que el driver (tools/verificar_backup.py)
# siga: compruebe el esquema contra los modelos de la app y que el backend
# arranque contra ella. La base de prueba la borra el driver al terminar.
#
# Uso (dentro de la imagen de PostgreSQL, en la red de Docker):
#   PGHOST=db PGUSER=parking PGDATABASE=parking \
#   BACKUP_DIR=/backups BACKUP_PASSPHRASE_FILE=/secrets/backup.pass \
#   bash /backup/simulacro.sh
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-parking}"
PGDATABASE="${PGDATABASE:-parking}"
# La contraseña va en el entorno (o en un ~/.pgpass del host de backups).
# Sin ella, ``pg_dump`` pide la contraseña por tty y falla en un cron.
PGPASSWORD="${PGPASSWORD:-}"
export PGPASSWORD
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-/secrets/backup.pass}"
BACKUP_SCRIPT="${BACKUP_SCRIPT:-/backup/backup.sh}"
RESTORE_SCRIPT="${RESTORE_SCRIPT:-/backup/restore.sh}"
TARGET_DB="${TARGET_DB:-parking_simulacro}"
#: Directorio de los adjuntos de los incidentes (T-78). Si está vacío, el
#: simulacro no comprueba los adjuntos (y avisa).
ATTACHMENTS_DIR="${ATTACHMENTS_DIR:-}"
#: Dónde se restauran los adjuntos en el simulacro.
ATTACHMENTS_RESTORE_DIR="${ATTACHMENTS_RESTORE_DIR:-/adjuntos-restaurados}"

# Tablas cuyo recuento se compara entre el origen y la restauración.
# Las que no existan en el origen se omiten; las que existan en una y no
# en la otra son un fallo del backup.
TABLAS_A_COMPARAR="users cameras parking_spaces tickets plans alerts tariffs vehicles"

log() { printf '[simulacro] %s\n' "$*" >&2; }
die() { printf '[simulacro] ERROR: %s\n' "$*" >&2; exit 1; }

contar() {
    local db="$1" tabla="$2"
    psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$db" \
        --tuples-only --no-align -c "SELECT count(*) FROM \"$tabla\";" 2>/dev/null \
        | tr -d '[:space:]' || echo "-"
}

# ── 1. Volcado ───────────────────────────────────────────────────────────────
log "1/4. volcando '$PGDATABASE' (cifrado, retención GFS)"

# T-78: los adjuntos de los incidentes (las fotos) NO viven en la base de
# datos, asi que sin esto el simulacro daba verde con las fotos perdidas.
# Se mete un fichero de prueba para poder comprobar que vuelve.
FICHERO_PRUEBA=""
if [[ -n "$ATTACHMENTS_DIR" && -d "$ATTACHMENTS_DIR" ]]; then
    FICHERO_PRUEBA="simulacro-prueba-$$.txt"
    printf 'contenido de prueba %s\n' "$FICHERO_PRUEBA" \
        > "$ATTACHMENTS_DIR/$FICHERO_PRUEBA"
    log "    fichero de prueba en los adjuntos: $FICHERO_PRUEBA"
else
    log "    AVISO: sin ATTACHMENTS_DIR este simulacro NO comprueba los adjuntos"
fi

BACKUP_DIR="$BACKUP_DIR" \
PGHOST="$PGHOST" PGPORT="$PGPORT" PGUSER="$PGUSER" PGDATABASE="$PGDATABASE" \
BACKUP_PASSPHRASE_FILE="$BACKUP_PASSPHRASE_FILE" \
ATTACHMENTS_DIR="$ATTACHMENTS_DIR" \
    bash "$BACKUP_SCRIPT" >/dev/null

DUMP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'solidapp-*.dump.enc' -printf '%T@ %p\n' \
    | sort -nr | head -n1 | cut -d' ' -f2-)"
[[ -n "$DUMP" ]] || die "backup.sh no dejó ningún .enc en $BACKUP_DIR"
log "    volcado: $DUMP ($(du -h "$DUMP" | cut -f1))"

# ── 2. Está cifrado de verdad ────────────────────────────────────────────────
log "2/4. comprobando que el volcado NO es legible en claro"
if head -c 16 "$DUMP" | grep -q 'PGDMP'; then
    die "el volcado se lee en claro: NO está cifrado"
fi
log "    en claro: no (correcto)"

# ── 3. Restauración en una base limpia ───────────────────────────────────────
log "3/4. restaurando en '$TARGET_DB'"
RESTORE_SCRIPT="$RESTORE_SCRIPT" \
PGHOST="$PGHOST" PGPORT="$PGPORT" PGUSER="$PGUSER" \
BACKUP_PASSPHRASE_FILE="$BACKUP_PASSPHRASE_FILE" \
ATTACHMENTS_RESTORE_DIR="$ATTACHMENTS_RESTORE_DIR" \
    bash "$RESTORE_SCRIPT" --file "$DUMP" --target-db "$TARGET_DB" --yes

# ── 4. Los mismos datos ──────────────────────────────────────────────────────
log "4/4. comparando el recuento de filas entre origen y restauración"
for tabla in $TABLAS_A_COMPARAR; do
    origen="$(contar "$PGDATABASE" "$tabla")"
    restaurada="$(contar "$TARGET_DB" "$tabla")"
    if [[ "$origen" == "-" || "$restaurada" == "-" ]]; then
        # La tabla no existe (ni en el origen ni en la restauración): se
        # omite. Lo que NO se admite es que exista en una y no en la otra.
        log "    $tabla: no existe en el origen, se omite"
        continue
    fi
    [[ "$origen" == "$restaurada" ]] \
        || die "la tabla '$tabla' no coincide: origen=$origen restaurada=$restaurada"
    log "    $tabla: $origen filas (coincide)"
done

# ── 5. Los adjuntos vuelven con su contenido (T-78) ──────────────────────────
if [[ -n "$FICHERO_PRUEBA" ]]; then
    log "5/5. comprobando que los adjuntos se han restaurado"
    if [[ ! -f "$ATTACHMENTS_RESTORE_DIR/$FICHERO_PRUEBA" ]]; then
        die "el fichero de prueba de los adjuntos NO ha vuelto: el backup no los incluye"
    fi
    if ! grep -q "contenido de prueba" "$ATTACHMENTS_RESTORE_DIR/$FICHERO_PRUEBA"; then
        die "el fichero de prueba de los adjuntos volvió con otro contenido"
    fi
    N_ORIGEN="$(find "$ATTACHMENTS_DIR" -type f | wc -l)"
    N_RESTAURADOS="$(find "$ATTACHMENTS_RESTORE_DIR" -type f | wc -l)"
    log "    adjuntos originales: $N_ORIGEN | restaurados: $N_RESTAURADOS"
    if [[ "$N_ORIGEN" != "$N_RESTAURADOS" ]]; then
        die "el numero de adjuntos no coincide (origen $N_ORIGEN, restaurados $N_RESTAURADOS)"
    fi
    log "    adjuntos OK: el fichero de prueba ha vuelto con su contenido"
    # Se limpia el fichero de prueba del volumen.
    rm -f "$ATTACHMENTS_DIR/$FICHERO_PRUEBA"
fi

cat <<RESUMEN

[simulacro] BASE RESTAURADA: $TARGET_DB
[simulacro] DUMP: $DUMP
RESUMEN
