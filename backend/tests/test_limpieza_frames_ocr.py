"""T-168 (2026-10-24): el directorio de respaldo de los frames lo limpia
**alguien**.

El defecto
----------
``alerts._save_frame`` guarda el frame en ``/tmp/ocr-failed`` y, si ese
directorio no se puede escribir (tests en Windows, disco lleno...), cae a
``/tmp/solidapp-alerts-test``. Pero la tarea ``cleanup_failed_frames``
**sólo** purga ``/tmp/ocr-failed``: los frames del directorio de respaldo
se quedaban **para siempre**.

Medido (2026-10-24, dentro del contenedor): con un frame de 45 días en
``/tmp/solidapp-alerts-test``, la tarea devolvió ``{"deleted": 0,
"kept": 0}`` y el fichero **siguió ahí**; en el directorio normal la
misma tarea devolvió ``{"deleted": 1, "kept": 1}`` y borró el viejo.

El arreglo
----------
La tarea purga **los dos** directorios, con la misma retención
(``FAILED_FRAMES_RETENTION_DAYS``) y el mismo formato de retorno
(``{"deleted": N, "kept": M}``, sumando los dos).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.workers import tasks as tasks_mod


def _escribir(path: Path, contenido: bytes, dias: int) -> Path:
    """Escribe un fichero con la antiguedad indicada."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contenido)
    if dias:
        antiguo = (datetime.now(timezone.utc) - timedelta(days=dias)).timestamp()
        os.utime(path, (antiguo, antiguo))
    return path


def test_la_tarea_limpia_el_directorio_de_respaldo(
    monkeypatch, tmp_path: Path,
) -> None:
    """El frame viejo del directorio de respaldo tiene que desaparecer."""
    normal = tmp_path / "ocr-failed"
    respaldo = tmp_path / "solidapp-alerts-test"
    monkeypatch.setattr(tasks_mod, "DEFAULT_OCR_FAILED_DIR", normal)
    monkeypatch.setattr(tasks_mod, "FALLBACK_OCR_FAILED_DIR", respaldo)

    viejo = _escribir(respaldo / "CAM-01-viejo.jpg", b"viejo", dias=45)
    hoy = _escribir(respaldo / "CAM-01-hoy.jpg", b"hoy", dias=0)

    resultado = tasks_mod.cleanup_failed_frames()

    assert not viejo.exists(), (
        "el frame viejo del directorio de respaldo sigue ahí: no lo limpia "
        "ninguna tarea"
    )
    assert hoy.exists(), "la tarea ha borrado un frame que no había que borrar"
    assert resultado == {"deleted": 1, "kept": 1}


def test_la_tarea_limpia_los_dos_directorios(
    monkeypatch, tmp_path: Path,
) -> None:
    """El recuento es la suma de los dos directorios."""
    normal = tmp_path / "ocr-failed"
    respaldo = tmp_path / "solidapp-alerts-test"
    monkeypatch.setattr(tasks_mod, "DEFAULT_OCR_FAILED_DIR", normal)
    monkeypatch.setattr(tasks_mod, "FALLBACK_OCR_FAILED_DIR", respaldo)

    viejo_normal = _escribir(normal / "CAM-01-viejo.jpg", b"viejo", dias=45)
    viejo_respaldo = _escribir(respaldo / "CAM-02-viejo.jpg", b"viejo", dias=45)
    hoy_normal = _escribir(normal / "CAM-01-hoy.jpg", b"hoy", dias=0)
    hoy_respaldo = _escribir(respaldo / "CAM-02-hoy.jpg", b"hoy", dias=0)

    resultado = tasks_mod.cleanup_failed_frames()

    assert not viejo_normal.exists()
    assert not viejo_respaldo.exists()
    assert hoy_normal.exists()
    assert hoy_respaldo.exists()
    assert resultado == {"deleted": 2, "kept": 2}


def test_la_tarea_no_falla_si_no_hay_directorios(
    monkeypatch, tmp_path: Path,
) -> None:
    """Si no existe ninguno, no hay error (el worker no debe caer)."""
    monkeypatch.setattr(tasks_mod, "DEFAULT_OCR_FAILED_DIR", tmp_path / "no-existe")
    monkeypatch.setattr(
        tasks_mod, "FALLBACK_OCR_FAILED_DIR", tmp_path / "tampoco-existe"
    )
    assert tasks_mod.cleanup_failed_frames() == {"deleted": 0, "kept": 0}


def test_la_retencion_es_la_misma_que_la_del_directorio_normal(
    monkeypatch, tmp_path: Path,
) -> None:
    """Un frame con la retención justa se queda; uno más viejo, no."""
    normal = tmp_path / "ocr-failed"
    respaldo = tmp_path / "solidapp-alerts-test"
    monkeypatch.setattr(tasks_mod, "DEFAULT_OCR_FAILED_DIR", normal)
    monkeypatch.setattr(tasks_mod, "FALLBACK_OCR_FAILED_DIR", respaldo)

    justo = _escribir(
        respaldo / "CAM-03-justo.jpg",
        b"justo",
        dias=tasks_mod.FAILED_FRAMES_RETENTION_DAYS - 1,
    )
    pasado = _escribir(
        respaldo / "CAM-03-pasado.jpg",
        b"pasado",
        dias=tasks_mod.FAILED_FRAMES_RETENTION_DAYS + 1,
    )

    resultado = tasks_mod.cleanup_failed_frames()

    assert justo.exists()
    assert not pasado.exists()
    assert resultado == {"deleted": 1, "kept": 1}
