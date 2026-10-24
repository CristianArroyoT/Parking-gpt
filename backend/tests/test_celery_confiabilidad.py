"""T-151 (2026-10-24): el worker reentrega lo que se pierde y acota las
tareas.

El defecto
----------
``task_acks_late=True`` sin ``task_reject_on_worker_lost`` hacia que, si
el worker mueria de forma abrupta, el mensaje no se reentregaba hasta que
vencia el ``visibility_timeout`` de Redis (1 hora), mientras el beat
publicaba la ronda **cada 60 s**: la cola crecia sin que nadie la
consumiera. Y sin limites de tiempo, una tarea colgada ocupaba un slot
del pool **para siempre**.
"""
from __future__ import annotations

from app.workers.celery_app import celery_app


def test_el_worker_reentrega_las_tareas_si_muere() -> None:
    """Sin esto, el mensaje espera al ``visibility_timeout`` (1 hora)."""
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True


def test_ninguna_tarea_puede_ocupar_el_slot_para_siempre() -> None:
    """Una tarea colgada no puede quedarse con un slot del pool para siempre."""
    blando = celery_app.conf.task_soft_time_limit
    duro = celery_app.conf.task_time_limit
    assert blando, "no hay limite blando de tiempo"
    assert duro, "no hay limite duro de tiempo"
    assert duro > blando, "el limite duro tiene que ser mayor que el blando"


def test_una_tarea_que_falla_no_se_reintenta_en_bucle() -> None:
    """Con ``acks_late``, un fallo permanente seria un bucle de reintentos."""
    assert celery_app.conf.task_acks_on_failure_or_timeout is True
