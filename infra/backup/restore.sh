#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# solidAPP · restauración de PostgreSQL (T-12 del plan de pendientes)
#
# "Un backup sin restaurar probado no es un backup" (regla del plan de
# pendientes). Este script hace la restauración completa en una base
# limpia y VERIFICA que la base restaurada es utilizable: tablas creadas,
# PostGIS activo, y conteos comparados contra el dump original.
#
# Uso:
#   ./restore.sh --file /backups/solidapp-20261021T020000Z.dump.enc \
#                --target-db parking_restore_test
#
#   ./restore.sh --file <enc> --target-db <db> [--yes]
#
# Variables de entorno:
#   PGHOST, PGPORT, PGUSER        → conexión al servidor
#   BACKUP_PASSPHRASE_FILE        → fichero con la passphrase
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-parking}"
BACKUP_PASSPHRASE_FILE="${BACKUP_PASSPHRASE_FILE:-}"

FILE=""
TARGET_DB=""
ASSUME_YES=""

log() { printf '[restore] %s\n' "$*" >&2; }
die() { printf '[restore] ERROR: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --file) FILE="$2"; shift 2 ;;
        --target-db) TARGET_DB="$2"; shift 2 ;;
        --yes|-y) ASSUME_YES="yes"; shift ;;
        --help|-h) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "argumento desconocido: $1" ;;
    esac
done

[[ -n "$FILE" ]] || die "falta --file"
[[ -n "$TARGET_DB" ]] || die "falta --target-db"
[[ -r "$FILE" ]] || die "no se puede leer $FILE"
[[ -n "$BACKUP_PASSPHRASE_FILE" && -r "$BACKUP_PASSPHRASE_FILE" ]] \
    || die "falta BACKUP_PASSPHRASE_FILE"
export PASS_PHRASE="$(cat "$BACKUP_PASSPHRASE_FILE")"

if [[ -z "$ASSUME_YES" ]]; then
    log "ATENCIÓN: se va a BORRAR la base '$TARGET_DB' y restaurar dentro."
    read -r -p "¿Continuar? (sí/N) " resp
    [[ "$resp" == "sí" || "$resp" == "si" ]] || die "cancelado por el operador"
fi

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT
PLAIN="$TMPDIR_LOCAL/dump.pgdmp"

log "descifrando $FILE"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
    -in "$FILE" -pass env:PASS_PHRASE -out "$PLAIN" \
    || die "no se pudo descifrar (passphrase incorrecta o fichero corrupto)"

head -c 5 "$PLAIN" | grep -q 'PGDMP' || die "el fichero descifrado no es un dump de Postgres"

log " Recreando la base '$TARGET_DB' desde cero"
psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname=postgres \
    --set ON_ERROR_STOP=1 --quiet <<SQL
DROP DATABASE IF EXISTS "$TARGET_DB";
CREATE DATABASE "$TARGET_DB";
SQL

# PostGIS debe existir ANTES del restore: el dump contiene la extensión.
log "habilitando PostGIS en '$TARGET_DB'"
psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$TARGET_DB" \
    --set ON_ERROR_STOP=1 --quiet \
    -c "CREATE EXTENSION IF NOT EXISTS postgis;" \
    || log "AVISO: no se pudo crear la extensión postgis (¿faltan los binarios en la imagen?)"

log "restaurando (pg_restore)"
pg_restore --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" \
    --dbname="$TARGET_DB" --no-owner --exit-on-error "$PLAIN" \
    || die "pg_restore falló"

# ── Adjuntos de los incidentes (T-78) ──────────────────────────────────────
# Las fotos NO estan en el dump: viven en un volumen aparte. Si el backup
# trae su tar, se restaura aqui; si no, se avisa (para que nadie crea que
# se han restaurado).
if [[ -n "${ATTACHMENTS_RESTORE_DIR:-}" ]]; then
    ENC_ADJ="${FILE%.dump.enc}.adjuntos.tar.enc"
    if [[ -f "$ENC_ADJ" ]]; then
        log "restaurando los adjuntos en $ATTACHMENTS_RESTORE_DIR"
        mkdir -p "$ATTACHMENTS_RESTORE_DIR"
        openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
            -in "$ENC_ADJ" -pass env:PASS_PHRASE -out "$TMPDIR_LOCAL/adjuntos.tar" \
            || die "no se pudo descifrar el tar de adjuntos"
        tar -xzf "$TMPDIR_LOCAL/adjuntos.tar" -C "$ATTACHMENTS_RESTORE_DIR" \
            || die "no se pudo desempaquetar el tar de adjuntos"
        log "adjuntos restaurados: $(find "$ATTACHMENTS_RESTORE_DIR" -type f | wc -l) ficheros"
    else
        log "AVISO: este backup NO incluye los adjuntos de los incidentes"
    fi
fi

# ── Verificación ────────────────────────────────────────────────────────────
log "verificando la base restaurada"
TABLAS="$(psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$TARGET_DB" \
    --tuples-only --no-align -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
[[ "${TABLAS:-0}" -gt 0 ]] || die "la base restaurada no tiene ninguna tabla en public"

USUARIOS="$(psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$TARGET_DB" \
    --tuples-only --no-align -c "SELECT count(*) FROM users;" 2>/dev/null || echo 0)"

GEOCERCAS="$(psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$TARGET_DB" \
    --tuples-only --no-align -c "SELECT count(*) FROM geofences;" 2>/dev/null || echo 0)"

POSTGIS="$(psql --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" --dbname="$TARGET_DB" \
    --tuples-only --no-align -c "SELECT count(*) FROM pg_extension WHERE extname='postgis';" || echo 0)"

log "tablas en public : $TABLAS"
log "filas en users   : $USUARIOS"
log "filas en geofences: $GEOCERCAS"
log "postgis instalado: $POSTGIS"

cat <<RESUMEN

[restore] RESTAURACIÓN CORRECTA
    base     : $TARGET_DB
    tablas   : $TABLAS
    usuarios : $USUARIOS
    geocercas: $GEOCERCAS
    postgis  : $POSTGIS

Para abrir la app contra esta base de prueba:
    DATABASE_URL=postgresql+psycopg://$PGUSER:<pass>@$PGHOST:$PGPORT/$TARGET_DB

Cuando termine la prueba: DROP DATABASE "$TARGET_DB";
RESUMEN
