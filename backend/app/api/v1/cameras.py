"""CRUD de cámaras y geocercas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import parking_context
from app.models.geofence import CameraGeofence
from app.models.parking import Camera, Parking
from app.schemas.parking import (
    CameraCreate,
    CameraRead,
    CameraUpdate,
    GeofenceCreate,
    GeofenceRead,
    GeofenceUpdate,
)

router = APIRouter(
    prefix="/parkings/{parking_id}/cameras",
    tags=["cámaras"],
    dependencies=[Depends(parking_context)],
)


@router.get("", response_model=list[CameraRead])
def list_cameras(parking_id: int, db: Session = Depends(get_db)) -> list[Camera]:
    return (
        db.query(Camera)
        .filter(Camera.parking_id == parking_id)
        .order_by(Camera.id)
        .all()
    )


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(
    parking_id: int,
    payload: CameraCreate,
    db: Session = Depends(get_db),
) -> Camera:
    if not db.get(Parking, parking_id):
        raise HTTPException(status_code=404, detail="Sucursal no encontrada")
    camera = Camera(parking_id=parking_id, **payload.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.patch("/{camera_id}", response_model=CameraRead)
def update_camera(
    parking_id: int,
    camera_id: int,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
) -> Camera:
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not camera:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(camera, key, value)
    db.commit()
    db.refresh(camera)
    return camera


@router.get("/{camera_id}/geofences", response_model=list[GeofenceRead])
def list_geofences(
    parking_id: int,
    camera_id: int,
    db: Session = Depends(get_db),
) -> list[CameraGeofence]:
    return (
        db.query(CameraGeofence)
        .filter(CameraGeofence.camera_id == camera_id)
        .all()
    )


@router.post(
    "/{camera_id}/geofences",
    response_model=GeofenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_geofence(
    parking_id: int,
    camera_id: int,
    payload: GeofenceCreate,
    db: Session = Depends(get_db),
) -> CameraGeofence:
    camera = (
        db.query(Camera)
        .filter(Camera.id == camera_id, Camera.parking_id == parking_id)
        .one_or_none()
    )
    if not camera:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    fence = CameraGeofence(camera_id=camera_id, **payload.model_dump())
    db.add(fence)
    db.commit()
    db.refresh(fence)
    return fence


@router.patch("/{camera_id}/geofences/{fence_id}", response_model=GeofenceRead)
def update_geofence(
    parking_id: int,
    camera_id: int,
    fence_id: int,
    payload: GeofenceUpdate,
    db: Session = Depends(get_db),
) -> CameraGeofence:
    fence = (
        db.query(CameraGeofence)
        .filter(
            CameraGeofence.id == fence_id, CameraGeofence.camera_id == camera_id
        )
        .one_or_none()
    )
    if not fence:
        raise HTTPException(status_code=404, detail="Geocerca no encontrada")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(fence, key, value)
    db.commit()
    db.refresh(fence)
    return fence