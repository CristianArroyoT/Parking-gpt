"""Plantillas de reconocimiento facial (T-23 · plan maestro 2026-10-21).

.. warning::

   **El reconocimiento facial está FUERA DEL MVP.**

   Este router existe para dejar la *estructura* preparada (tabla +
   endpoints de alta/baja), pero:

   - Está **deshabilitado por feature flag** (``FACE_TEMPLATES_ENABLED``,
     por defecto ``false``). Con el flag apagado, **todos** los endpoints
     de este router devuelven **404 Not Found** (decisión documentada: se
     elige 404 y no 403 porque la funcionalidad no existe todavía para
     esta instalación; así el cliente no ve una API que luego desaparecerá).
   - **No se usa en el login.** El acceso al sistema sigue siendo
     exclusivamente usuario + contraseña: ni ``auth.py`` ni
     ``core/security.py`` leen la tabla ``face_templates``.

Endpoints (sólo con el flag activo):

- ``POST /face-templates`` → alta de un template del usuario autenticado.
- ``DELETE /face-templates/{id}`` → baja de un template propio (o de
  cualquiera, si quien llama es admin).

RBAC: el template se crea **siempre** para el usuario autenticado
(el ``user_id`` no viene en el body: así nadie puede dar de alta una
biometría en nombre de otro). Para la baja, el propietario o un admin.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audited
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import enforce_parking_membership, get_current_user
from app.models.enums import UserRole
from app.models.face_template import FaceTemplate
from app.models.parking import Camera
from app.models.user import User
from app.schemas.face_template import FaceTemplateCreate, FaceTemplateRead

log = logging.getLogger(__name__)


def _exigir_feature_flag() -> None:
    """Dependencia de router: si el flag está apagado → 404.

    Va como dependencia **de router** (y no dentro del handler) para que
    el corte ocurra antes de cualquier lógica de negocio y antes del
    ``@audited`` (así no se ensucia ``audit_logs`` con rechazos de una
    funcionalidad que no existe).
    """
    if not get_settings().face_templates_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurso no disponible: el reconocimiento facial está "
                   "fuera del MVP.",
        )


router = APIRouter(
    prefix="/face-templates",
    tags=["biometria"],
    dependencies=[Depends(_exigir_feature_flag)],
)


@router.post(
    "",
    response_model=FaceTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
@audited("create_face_template")
def create_face_template(
    payload: FaceTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> FaceTemplate:
    """Da de alta un template biométrico **del usuario autenticado**.

    ``user_id`` sale siempre de la sesión, nunca del body: nadie puede
    registrar una biometría en nombre de otro. Si se indica ``camera_id``
    la cámara debe existir y el usuario debe tener acceso a su sucursal
    (o ser admin).
    """
    camera: Camera | None = None
    if payload.camera_id is not None:
        camera = db.get(Camera, payload.camera_id)
        if camera is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cámara no encontrada",
            )
        # Un cliente sólo puede asociar su template a una cámara de una
        # sucursal en la que tiene membresía (o es admin).
        enforce_parking_membership(current, camera.parking_id, db)

    template = FaceTemplate(
        user_id=current.id,
        camera_id=camera.id if camera is not None else None,
        embedding=[float(valor) for valor in payload.embedding],
        dimension=len(payload.embedding),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
@audited("delete_face_template")
def delete_face_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> None:
    """Da de baja un template: el propietario o un admin.

    Para el resto de usuarios la respuesta es 404 (no revelamos la
    existencia de templates de otros).
    """
    template = db.get(FaceTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template no encontrado",
        )
    rol = current.role.value if hasattr(current.role, "value") else str(current.role)
    if template.user_id != current.id and rol != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template no encontrado",
        )
    db.delete(template)
    db.commit()
    return None


__all__ = ["router"]
