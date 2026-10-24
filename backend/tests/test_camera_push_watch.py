"""T-164 (2026-10-24): la alarma de «la camara dejo de empujar lecturas».

El push externo es el camino real de datos y no tenia ninguna
vigilancia: la unica alarma de OCR cuelga de ``ping_camera``, que no se
despacha. Si la camara (o el OCR del fabricante) dejaban de hablar, no
saltaba nada y se seguia sin cobrar, en silencio.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.parking import Camera, Parking
from app.models.plates_detected import PlatesDetected
from app.services.camera_push_watch import camaras_sin_push


def _camara(
    db: Session,
    *,
    rtsp: str = "rtsp://real/x",
    pushes: int = 0,
    antiguedad: timedelta = timedelta(minutes=5),
) -> Camera:
    parking = Parking(code="P-PUSH", name="P", address="x", city="y")
    db.add(parking)
    db.flush()
    camera = Camera(
        parking_id=parking.id, code="CAM-PUSH", name="C", rtsp_url=rtsp,
    )
    db.add(camera)
    db.flush()
    for _indice in range(pushes):
        db.add(
            PlatesDetected(
                camera_id=camera.id,
                plate="1234ABC",
                confidence=0.9,
                bbox_x1=1, bbox_y1=1, bbox_x2=2, bbox_y2=2,
                detected_at=datetime.now(timezone.utc) - antiguedad,
            )
        )
    db.commit()
    db.refresh(camera)
    return camera


def test_una_camara_que_no_empuja_nada_se_detecta(db_session: Session) -> None:
    """Una camara que nunca ha empujado lecturas es silenciosa."""
    camera = _camara(db_session)
    silenciosas = camaras_sin_push(db_session, minutos_max=30)
    assert [c.id for c, _ in silenciosas] == [camera.id]


def test_una_camara_que_acaba_de_empujar_no_se_detecta(db_session: Session) -> None:
    """Una camara que empuja hace poco, no."""
    camera = _camara(db_session, pushes=1, antiguedad=timedelta(minutes=2))
    silenciosas = camaras_sin_push(db_session, minutos_max=30)
    assert camera.id not in [c.id for c, _ in silenciosas]


def test_una_camara_que_empuja_hace_mucho_se_detecta(db_session: Session) -> None:
    """Si el push es viejo, la camara esta silenciosa."""
    camera = _camara(db_session, pushes=1, antiguedad=timedelta(minutes=90))
    silenciosas = camaras_sin_push(db_session, minutos_max=30)
    assert [c.id for c, _ in silenciosas] == [camera.id]


def test_las_camaras_de_demo_no_avisan(db_session: Session) -> None:
    """Las camaras de demo no empujan nada: no deben ensuciar con alertas."""
    _camara(db_session, rtsp="rtsp://demo.invalid/x")
    silenciosas = camaras_sin_push(
        db_session, minutos_max=30, skip_prefixes=("rtsp://demo.invalid",)
    )
    assert silenciosas == []
