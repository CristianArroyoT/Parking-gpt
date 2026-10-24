"""T-153 (2026-10-24): el informe de alertas hereda el tope de filas.

El informe de alertas era el **unico** de los cinco que no acotaba las
filas (T-100): un informe de un periodo con muchas alertas traia
**todas** a memoria, y si el proceso se queda sin memoria **se cae la API
entera**.

El tope se baja a 3 en el test (en vez de crear 20.001 alertas): lo que
se comprueba es que el informe **rechaza** la ventana que lo supera, no
cuantas filas caben.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.audit import Alert
from app.models.enums import AlertSeverity, AlertType
from app.models.parking import Parking
from app.services import reports as reports_mod


def _alertas(db: Session, parking_id: int, cuantas: int) -> None:
    ahora = datetime.now(timezone.utc)
    for indice in range(cuantas):
        db.add(
            Alert(
                parking_id=parking_id,
                type=AlertType.OCR_FAILED,
                severity=AlertSeverity.WARN,
                message=f"alerta {indice}",
                created_at=ahora - timedelta(minutes=indice),
            )
        )
    db.commit()


def test_el_informe_de_alertas_rechaza_una_ventana_demasiado_grande(
    db_session: Session, monkeypatch
) -> None:
    """Con mas filas que el tope, el informe falla (no se recorta en silencio)."""
    parking = Parking(
        name="Sucursal T-153", code="T153", address="Calle 1", city="Huelva",
        latitude=37.2614, longitude=-6.9447,
    )
    db_session.add(parking)
    db_session.commit()
    db_session.refresh(parking)

    _alertas(db_session, parking.id, 4)

    # El tope se baja para no tener que crear 20.001 filas en el test.
    monkeypatch.setattr(reports_mod, "MAX_FILAS_INFORME", 3)

    desde = datetime.now(timezone.utc) - timedelta(hours=1)
    hasta = datetime.now(timezone.utc) + timedelta(hours=1)

    with pytest.raises(reports_mod.InformeDemasiadoGrandeError):
        reports_mod.build_alertas_report(db_session, parking.id, desde, hasta)


def test_el_informe_de_alertas_devuelve_las_filas_si_caben(
    db_session: Session, monkeypatch
) -> None:
    """Si la ventana cabe en el tope, el informe sale con sus filas."""
    parking = Parking(
        name="Sucursal T-153b", code="T153B", address="Calle 2", city="Huelva",
        latitude=37.2614, longitude=-6.9447,
    )
    db_session.add(parking)
    db_session.commit()
    db_session.refresh(parking)

    _alertas(db_session, parking.id, 2)

    monkeypatch.setattr(reports_mod, "MAX_FILAS_INFORME", 3)

    desde = datetime.now(timezone.utc) - timedelta(hours=1)
    hasta = datetime.now(timezone.utc) + timedelta(hours=1)

    informe = reports_mod.build_alertas_report(db_session, parking.id, desde, hasta)
    assert len(informe.rows) == 2
