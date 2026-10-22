"""Endpoints REST para incidentes (marcar plaza, reportar robo, rehabilitar)
y para sus **ADJUNTOS** (fotos) — T-21 del plan maestro (2026-10-21).

Incidentes: un único endpoint, ``POST /api/v1/parkings/{parking_id}/incidents``
con ``kind ∈ {space_broken, space_unbroken, robery_reported}``. RBAC:
admin/gestor/operador con membresía en la sucursal. Cliente → 403.

Devuelve 201 con ``IncidentRead`` si crea una alerta nueva, o 200 con
``{"noop": true, "detail": "..."}`` si la operación era idempotente (la
plaza ya estaba en el estado deseado).

Adjuntos (T-21)
---------------
El operador adjunta **hasta 3 fotos** al reportar. La foto **nunca** va
a la base de datos: se guarda en un volumen local con el nombre derivado
del hash del contenido, y en la BD sólo queda la metadata.

Decisión de producto **D5** (ya tomada; no se re-discute aquí): los
adjuntos **no se exponen a ningún canal externo** en el MVP. No hay
correo con adjuntos, ni webhooks, ni integración con servicios de
terceros. Sólo los ven el **gestor** y el **admin** de esa sucursal: el
operador los sube, pero **no puede volver a listarlos ni descargarlos**
salvo que sea gestor/admin de esa misma sucursal.

RBAC:

- ``POST .../attachments``: admin, gestor u operador **de la sucursal**.
- ``GET .../attachments``, descarga, miniatura y borrado: **gestor o
  admin de la sucursal** del incidente.

La miniatura se sirve con ``Content-Type: image/jpeg`` (tipo verificado
por los bytes del fichero) y ``nosniff``; la descarga se sirve como
``attachment`` con el mime verificado. **Nunca** se sirve el contenido
como ``text/html`` ni se interpola en la página: el SVG, además, no se
acepta como adjunto (es XML ejecutable).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import (
    enforce_parking_membership,
    get_current_user,
    get_current_user_or_query_token,
    parking_context,
    require_role,
)
from app.core.ip import get_real_ip
from app.models.audit import Alert
from app.models.enums import UserRole
from app.models.incident import IncidentAttachment
from app.models.user import User
from app.schemas.audit import IncidentCreate, IncidentRead
from app.schemas.incident import IncidentAttachmentRead
from app.services import incident_attachments as adjuntos
from app.services import record_audit
from app.services.incidents import create_incident

log = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents", tags=["incidentes"])

#: Cabeceras que acompañan siempre a la entrega de un fichero.
_CABECERAS_SEGURAS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
}


@router.post(
    "/parkings/{parking_id}",
    dependencies=[
        Depends(require_role(
            UserRole.ADMIN.value,
            UserRole.GESTOR.value,
            UserRole.OPERADOR.value,
        ))
    ],
)
def create_incident_endpoint(
    parking_id: int,
    payload: IncidentCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any] | IncidentRead:
    parking_context(parking_id, current=current_user, db=db)
    # OJO (T-62): con ``request.client.host`` se auditaba la IP del
    # PROXY (nginx), no la del cliente.
    ip = get_real_ip(request) if request.client else None
    alert = create_incident(
        payload,
        parking_id=parking_id,
        current_user=current_user,
        ip=ip,
    )
    if alert is None:
        # Idempotente: ya estaba en el estado deseado.
        response.status_code = 200
        return {"noop": True, "detail": "La plaza ya estaba en el estado deseado"}
    response.status_code = 201
    return IncidentRead.model_validate(alert)


# ── Adjuntos (T-21) ─────────────────────────────────────────────────────
def _gestor_o_admin(
    current: User = Depends(get_current_user_or_query_token),
) -> User:
    """Rol **gestor** o **admin** para leer/descargar adjuntos.

    Acepta el token por query param (``?token=...``) porque la miniatura
    la consume un ``<img>`` del navegador, que no puede mandar
    cabeceras. Mismo patrón que el preview MJPEG (``cameras_live.py``) y
    el stream SSE: la ampliación del scope de auth es *opt-in por
    endpoint* y sólo afecta a estas tres rutas.
    """
    rol = current.role.value if hasattr(current.role, "value") else current.role
    if rol not in (UserRole.ADMIN.value, UserRole.GESTOR.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Sólo el gestor y el admin de la sucursal pueden ver "
                "los adjuntos del incidente"
            ),
        )
    return current


async def _leer_limitado(upload: UploadFile, limite: int) -> bytes:
    """Lee el fichero como máximo en ``limite`` bytes.

    No se usa ``await upload.read()`` a pelo: un cliente podría mandar
    un cuerpo enorme y el backend se lo cargaría entero en memoria.
    """
    trozos: list[bytes] = []
    total = 0
    while True:
        trozo = await upload.read(64 * 1024)
        if not trozo:
            break
        total += len(trozo)
        if total > limite:
            raise HTTPException(
                status_code=adjuntos.HTTP_413_TOO_LARGE,
                detail=(
                    f"El fichero '{upload.filename or 'adjunto'}' supera el "
                    f"tamaño máximo ({limite} bytes)"
                ),
            )
        trozos.append(trozo)
    return b"".join(trozos)


def _adjunto_de_sucursal(
    attachment_id: int, db: Session, current_user: User
) -> IncidentAttachment:
    """Carga el adjunto y comprueba que el usuario tiene la sucursal."""
    adjunto = db.get(IncidentAttachment, attachment_id)
    if adjunto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Adjunto no encontrado",
        )
    enforce_parking_membership(current_user, adjunto.parking_id, db)
    return adjunto


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_role(UserRole.ADMIN.value, UserRole.GESTOR.value))
    ],
)
def borrar_adjunto_incidente(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Borra una foto (LOPDGDD: supresión y derecho al olvido).

    Se borra la fila **y** el fichero del volumen. Si otra fila apunta al
    mismo fichero (mismo contenido, mismo hash) el fichero se conserva.
    """
    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    record_audit(
        db,
        action="incident_attachment_deleted",
        user_id=current_user.id,
        resource=f"incident_attachment:{adjunto.id}",
        payload={
            "attachment_id": adjunto.id,
            "alert_id": adjunto.alert_id,
            "size_bytes": adjunto.size_bytes,
        },
        parking_id=adjunto.parking_id,
        result="success",
    )
    db.commit()
    adjuntos.borrar_adjunto(db, adjunto)


@router.get("/attachments/{attachment_id}/download")
def descargar_adjunto_incidente(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_gestor_o_admin),
) -> Response:
    """Descarga el fichero original de la foto.

    Se sirve como **descarga** (``Content-Disposition: attachment``) con el
    mime **verificado por los bytes** al subirlo y ``nosniff``: el
    navegador nunca lo interpreta como HTML.
    """
    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    ruta = adjuntos.directorio_base() / adjunto.storage_path
    if not ruta.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El fichero del adjunto ya no está en el volumen",
        )
    return FileResponse(
        ruta,
        media_type=adjunto.mime_type,
        filename=adjunto.original_filename,
        headers=dict(_CABECERAS_SEGURAS),
    )


@router.get("/attachments/{attachment_id}/thumbnail")
def ver_miniatura_incidente(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_gestor_o_admin),
) -> FileResponse:
    """Miniatura (JPEG) de la foto.

    Es lo que muestra el listado: **no** la imagen completa. La miniatura
    se re-codificó al subirla (sin EXIF), así que su mime es
    ``image/jpeg`` siempre y se puede servir en línea con ``nosniff``.
    """
    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    if not adjunto.thumbnail_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El adjunto no tiene miniatura",
        )
    ruta = adjuntos.directorio_base() / adjunto.thumbnail_path
    if not ruta.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La miniatura ya no está en el volumen",
        )
    cabeceras = dict(_CABECERAS_SEGURAS)
    cabeceras["Content-Disposition"] = 'inline; filename="miniatura.jpg"'
    return FileResponse(ruta, media_type="image/jpeg", headers=cabeceras)


@router.get(
    "/attachments/{attachment_id}",
    response_model=IncidentAttachmentRead,
)
def ver_adjunto_incidente(
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_gestor_o_admin),
) -> IncidentAttachmentRead:
    """Metadata de un adjunto (sin el binario)."""
    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    return adjuntos.a_esquema(adjunto)


@router.post(
    "/{alert_id}/attachments",
    response_model=list[IncidentAttachmentRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_role(
            UserRole.ADMIN.value,
            UserRole.GESTOR.value,
            UserRole.OPERADOR.value,
        ))
    ],
)
async def subir_adjuntos_incidente(
    alert_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[IncidentAttachmentRead]:
    """Sube hasta 3 fotos a un incidente.

    Validación (todas obligatorias):

    - **Cantidad**: como máximo 3 ficheros por incidente (contando los
      que ya había).
    - **Tamaño**: como máximo ``INCIDENT_ATTACHMENT_MAX_BYTES`` por
      fichero (10 MB por defecto).
    - **Tipo real**: se comprueban los **bytes** del fichero (firma
      JPEG/PNG/WebP) y se abre con Pillow para verificar que decodifica.
      Ni la extensión ni el ``Content-Type`` del cliente son fiables: un
      fichero que se disfraza de imagen se rechaza con 415. **SVG no se
      acepta** (es XML ejecutable).

    El binario va al volumen local con el nombre derivado del SHA-256 del
    contenido; en la BD sólo queda la metadata. Nada de esto se expone
    a ningún canal externo (decisión D5): sólo lo ven el gestor y el
    admin de la sucursal.
    """
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incidente no encontrado",
        )
    enforce_parking_membership(current_user, alert.parking_id, db)

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se ha enviado ningún fichero",
        )

    maximo = adjuntos.maximo_ficheros()
    ya_existentes = adjuntos.contar_adjuntos(db, alert_id)
    if ya_existentes + len(files) > maximo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Un incidente admite como máximo {maximo} fotos "
                f"(ya hay {ya_existentes})"
            ),
        )

    limite = get_settings().incident_attachment_max_bytes
    base = adjuntos.directorio_base()
    creados: list[IncidentAttachment] = []
    for upload in files:
        contenido = await _leer_limitado(upload, limite)
        adjunto = adjuntos.crear_adjunto(
            db,
            alert=alert,
            contenido=contenido,
            nombre_original=upload.filename or "adjunto",
            usuario=current_user,
            base_dir=base,
        )
        creados.append(adjunto)

    db.commit()
    for adjunto in creados:
        db.refresh(adjunto)

    # OJO (T-62): con ``request.client.host`` se auditaba la IP del
    # PROXY (nginx), no la del cliente.
    ip = get_real_ip(request) if request.client else None
    record_audit(
        db,
        action="incident_attachment_uploaded",
        user_id=current_user.id,
        ip=ip,
        resource=f"alert:{alert.id}",
        payload={
            "alert_id": alert.id,
            "attachments": [
                {
                    "id": adjunto.id,
                    "mime_type": adjunto.mime_type,
                    "size_bytes": adjunto.size_bytes,
                    "content_hash": adjunto.content_hash,
                }
                for adjunto in creados
            ],
        },
        parking_id=alert.parking_id,
        result="success",
    )
    db.commit()

    log.info(
        "incidents: %s adjuntos subidos alert_id=%s parking_id=%s user_id=%s",
        len(creados), alert.id, alert.parking_id, current_user.id,
    )
    return [adjuntos.a_esquema(adjunto) for adjunto in creados]


@router.get(
    "/{alert_id}/attachments",
    response_model=list[IncidentAttachmentRead],
    dependencies=[
        Depends(require_role(UserRole.ADMIN.value, UserRole.GESTOR.value))
    ],
)
def listar_adjuntos_incidente(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[IncidentAttachmentRead]:
    """Lista los adjuntos de un incidente (metadata, sin el binario).

    Sólo gestor y admin **de la sucursal del incidente**.
    """
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incidente no encontrado",
        )
    enforce_parking_membership(current_user, alert.parking_id, db)
    filas = (
        db.query(IncidentAttachment)
        .filter(IncidentAttachment.alert_id == alert_id)
        .order_by(IncidentAttachment.id)
        .all()
    )
    return [adjuntos.a_esquema(fila) for fila in filas]


__all__ = ["router"]
