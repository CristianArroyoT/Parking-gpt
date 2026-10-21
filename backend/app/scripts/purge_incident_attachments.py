"""Purga de las fotos adjuntas a incidentes (LOPDGDD) — T-21.

Las fotos de un incidente se guardan **90 días** por defecto
(``INCIDENT_ATTACHMENT_RETENTION_DAYS``). Este script borra las que han
cumplido la retención y, además, los ficheros del volumen que se han
quedado sin fila en la base de datos (huérfanos: por ejemplo, los que
dejó un borrado de usuario a medias).

Uso:

    # purga normal (retención por defecto)
    python -m app.scripts.purge_incident_attachments

    # sólo contar lo que se borraría (no toca nada)
    python -m app.scripts.purge_incident_attachments --dry-run

    # otra retención para esta pasada
    python -m app.scripts.purge_incident_attachments --retention-days 30

Es idempotente: si no hay nada que borrar, no hace nada y sale con 0.
Pensado para lanzarse desde el cron del sistema (o desde el beat de
Celery cuando se integre): ``docker compose exec backend python -m
app.scripts.purge_incident_attachments``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.incident import IncidentAttachment
from app.services.incident_attachments import (
    directorio_base,
    purgar_adjuntos_vencidos,
    purgar_ficheros_huerfanos,
)

log = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.purge_incident_attachments",
        description="Purga las fotos adjuntas a incidentes que han cumplido la retención.",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help=(
            "Días de retención (por defecto, "
            "INCIDENT_ATTACHMENT_RETENTION_DAYS = 90)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sólo dice qué se borraría; no modifica nada.",
    )
    parser.add_argument(
        "--skip-orphans",
        action="store_true",
        help="No barre los ficheros huérfanos del volumen.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    settings = get_settings()
    dias = (
        args.retention_days
        if args.retention_days is not None
        else settings.incident_attachment_retention_days
    )
    corte = datetime.now(timezone.utc) - timedelta(days=dias)

    db = SessionLocal()
    try:
        if args.dry_run:
            vencidas = (
                db.query(IncidentAttachment)
                .filter(IncidentAttachment.created_at < corte)
                .count()
            )
            print(
                f"[dry-run] Retención: {dias} días (corte {corte.isoformat()})")
            print(f"[dry-run] Fotos vencidas que se borrarían: {vencidas}")
            if not args.skip_orphans:
                print("[dry-run] Los ficheros huérfanos del volumen se "
                      "borrarían también (usa --skip-orphans para no hacerlo).")
            return 0

        resultado = purgar_adjuntos_vencidos(db, retention_days=dias)
        print(
            f"Fotos vencidas borradas: {resultado['deleted']} "
            f"(retención {resultado['retention_days']} días, "
            f"corte {resultado['cutoff']})"
        )
        if not args.skip_orphans:
            huerfanos = purgar_ficheros_huerfanos(db)
            print(
                f"Ficheros huérfanos borrados: {huerfanos['deleted']} "
                f"(conservados {huerfanos['kept']})"
            )
        print(f"Volumen de adjuntos: {directorio_base()}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover — entrada de CLI
    sys.exit(main())
