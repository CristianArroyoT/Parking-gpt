"""Adjuntos de incidentes: validación, almacenamiento y borrado (T-21).

Este módulo es el corazón de T-21 (``docs/superpowers/specs/2026-10-21-plan-pendientes-solidapp-design.md``).
Convierte una subida en un fichero photo-fijo y decide, de forma
explícita, qué se guarda, cómo se valida y cuándo se borra.

Decisiones (todas deliberadas, ninguna heredada por casualidad):

1. **El binario NO va a la base de datos.** Ni ``bytea``, ni base64. La
   foto vive en un volumen local y en la BD queda **sólo la metadata**
   (nombre original, hash del contenido, mime, tamaño y ruta relativa).
   Una foto de 4 MB en la BD multiplica el tamaño de cada backup y hace
   que los ``SELECT`` de listado arrastren el binario.

2. **El nombre del fichero se deriva del hash del contenido** (SHA-256),
   no del nombre que envía el cliente: el volumen no filtra el nombre
   original (puede llevar datos personales) y dos subidas del mismo
   fichero comparten fichero en disco (dedup).

3. **El tipo se verifica por los BYTES**, nunca por la extensión ni por
   el ``Content-Type`` que declara el cliente. Un fichero que se disfraza
   de imagen (``evil.jpg`` con HTML dentro) no se guarda. Además se
   abre con Pillow para verificar que la imagen decodifica de verdad.

4. **SVG no se acepta**: es XML ejecutable (HTML embebido) y sirve como
   XSS guardado. La lista admitida es JPEG, PNG y WebP.

5. **Servido como descarga o como imagen validada**, nunca como
   ``text/html`` ni interpolado en la página: la descarga lleva
   ``Content-Disposition: attachment`` y la miniatura lleva
   ``Content-Type: image/jpeg`` (ya validada por bytes), ambas con
   ``X-Content-Type-Options: nosniff``.

6. **Retención por defecto de 90 días** (LOPDGDD: minimización) + borrado
   explícito + **derecho al olvido**: al borrar un usuario se borran sus
   fotos (filas y ficheros del disco).

Decisión de producto D5 (ya tomada por la sesión principal, NO se
re-discute aquí): **las fotos de un incidente no se exponen a ningún
canal externo** en el MVP. No hay correo con adjuntos, ni webhook, ni
integración con terceros. Sólo las ven el **gestor** y el **admin** de
esa sucursal (el operador las sube, pero no puede volver a listarlas).
"""

from __future__ import annotations
from typing import Any

import hashlib
import io
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import event, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import Alert
from app.models.incident import IncidentAttachment
from app.models.user import User
from app.schemas.incident import IncidentAttachmentRead

log = logging.getLogger(__name__)

# ── Tipos MIME admitidos ────────────────────────────────────────────────
MIME_JPEG = "image/jpeg"
MIME_PNG = "image/png"
MIME_WEBP = "image/webp"

#: Extensión en disco por tipo MIME verificado.
EXTENSIONES: dict[str, str] = {
    MIME_JPEG: ".jpg",
    MIME_PNG: ".png",
    MIME_WEBP: ".webp",
}

#: Lado máximo (en píxeles) de la miniatura.
TAM_MINIATURA = 320
#: Tope de píxeles de la imagen original (50 MP): por encima de esto el
#: fichero es un abuso, no una foto de un móvil.
MAX_PIXELES = 50_000_000

#: 413 Request Entity Too Large. Se define aquí (y no con
#: ``status.HTTP_413_REQUEST_ENTITY_TOO_LARGE``) porque Starlette cambió
#: el nombre de la constante y la deprecada avisa en cada respuesta.
HTTP_413_TOO_LARGE = 413

#: Clave del ``session.info`` donde se encolan los ficheros que se
#: borran del disco tras el commit (derecho al olvido).
_CLAVE_PENDIENTES = "_solidapp_adjuntos_pendientes_borrado"


# ── Detección y validación ──────────────────────────────────────────────
def detectar_mime_por_bytes(contenido: bytes) -> str | None:
    """Devuelve el MIME **real** del fichero según sus bytes (o ``None``).

    Firmas:
      - JPEG: ``FF D8 FF``
      - PNG:  ``89 50 4E 47 0D 0A 1A 0A``
      - WebP: ``RIFF....WEBP``
    """
    if contenido.startswith(b"\xff\xd8\xff"):
        return MIME_JPEG
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_PNG
    if len(contenido) >= 12 and contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return MIME_WEBP
    return None


def validar_imagen(contenido: bytes, *, nombre: str = "") -> str:
    """Valida el fichero y devuelve su MIME verificado.

    Lanza ``HTTPException``:
      - 400 si el fichero está vacío.
      - 413 si supera el tamaño máximo o si tiene demasiados píxeles.
      - 415 si no es una imagen válida (falsificada, corrupta o de un
        tipo no admitido).
    """
    if not contenido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El fichero '{nombre_seguro(nombre)}' está vacío",
        )

    limite = get_settings().incident_attachment_max_bytes
    if len(contenido) > limite:
        raise HTTPException(
            status_code=HTTP_413_TOO_LARGE,
            detail=(
                f"El fichero '{nombre_seguro(nombre)}' supera el tamaño máximo "
                f"({limite} bytes)"
            ),
        )

    mime = detectar_mime_por_bytes(contenido)
    if mime is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"El fichero '{nombre_seguro(nombre)}' no es una imagen válida "
                "(sólo JPEG, PNG o WebP)"
            ),
        )

    permitidos = get_settings().incident_attachment_mime_types_list
    if mime not in permitidos:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo de imagen no admitido: {mime}",
        )

    # Verificación real: la firma dice "esto es un PNG", pero el
    # contenido puede ser basura. Pillow lo comprueba al decodificar.
    try:
        with Image.open(io.BytesIO(contenido)) as imagen:
            ancho, alto = imagen.size
            imagen.verify()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"El fichero '{nombre_seguro(nombre)}' no es una imagen válida "
                f"o está corrupto"
            ),
        ) from exc

    if ancho * alto > MAX_PIXELES:
        raise HTTPException(
            status_code=HTTP_413_TOO_LARGE,
            detail=f"La imagen '{nombre_seguro(nombre)}' tiene demasiados píxeles",
        )

    return mime


def nombre_seguro(nombre: str | None) -> str:
    """Sanea el nombre original del fichero.

    Elimina rutas (``../``), caracteres de control y comillas: el nombre
    viaja en la cabecera ``Content-Disposition`` de la descarga, así que
    no puede permitir inyección de cabeceras ni rutas fuera del volumen.
    """
    base = (nombre or "").replace("\\", "/").split("/")[-1]
    base = "".join(c for c in base if c.isprintable() and c not in '"<>|:*?')
    base = base.strip().strip(".")
    if not base:
        base = "adjunto"
    return base[:200]


# ── Almacenamiento en el volumen local ───────────────────────────────────
def directorio_base() -> Path:
    """Directorio raíz del volumen de adjuntos."""
    return Path(get_settings().incident_attachments_dir)


def ruta_relativa_original(hash_hex: str, extension: str) -> str:
    """Ruta relativa del original: ``originales/ab/<hash>.jpg``."""
    return f"originales/{hash_hex[:2]}/{hash_hex}{extension}"


def ruta_relativa_thumbnail(hash_hex: str) -> str:
    """Ruta relativa de la miniatura: ``miniaturas/ab/<hash>_thumb.jpg``."""
    return f"miniaturas/{hash_hex[:2]}/{hash_hex}_thumb.jpg"


def _escribir(destino: Path, contenido: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)


def asegurar_directorio(base: Path) -> None:
    """Comprueba que el volumen de adjuntos existe y se puede escribir.

    Si el volumen no está montado (o no es escribible por el usuario del
    backend) se responde 503 con un mensaje claro en vez de un 500 opaco
    al escribir el fichero.
    """
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error(
            "incident_attachments: no se pudo preparar el volumen %s: %s. "
            "Revisa que el volumen 'incident_attachments' esté montado en el "
            "backend y que la imagen se haya reconstruido (docker compose up "
            "-d --build backend): el directorio lo crea el Dockerfile con "
            "permisos del usuario 'app'.",
            base,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El almacenamiento de adjuntos no está disponible",
        ) from exc
    if not os.access(base, os.W_OK):
        log.error(
            "incident_attachments: el volumen %s no es escribible por el "
            "usuario del backend. Reconstruye la imagen (docker compose up -d "
            "--build backend) para que el directorio del volumen herede los "
            "permisos de 'app'.",
            base,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El almacenamiento de adjuntos no está disponible",
        )


def _unlink(ruta: Path) -> None:
    try:
        ruta.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover — defensiva
        log.warning("incident_attachments: no se pudo borrar %s: %s", ruta, exc)


def sanear_metadatos(contenido: bytes, mime: str) -> bytes:
    """Re-codifica la imagen **sin metadatos** (EXIF, GPS, texto...).

    Se conservan los pixeles (mismas dimensiones) y la orientacion: la
    rotacion de la camara va en el EXIF, asi que si se quita el EXIF sin
    aplicar la rotacion, la foto sale girada.

    Se hace con ``ImageOps.exif_transpose`` (aplica la rotacion) y un
    ``save()`` **sin** pasar ``exif=`` (Pillow no copia los metadatos si
    no se los pasas). Para JPEG se pide ``quality="keep"`` para no
    recomprimir de mas; si Pillow no puede (imagen ya modificada), se
    recurre a ``quality=95``.

    OJO: el contenido devuelto es **distinto** del subido (mismo
    aspecto, sin metadatos). El hash y el tamano se calculan sobre el
    contenido guardado, no sobre el recibido.
    """
    with Image.open(io.BytesIO(contenido)) as imagen:
        imagen.load()
        # La orientacion va en el EXIF: se aplica a los pixeles antes de
        # quitarlo, o la foto sale girada.
        enderezada = ImageOps.exif_transpose(imagen)
        buffer = io.BytesIO()
        if mime == "image/jpeg":
            try:
                enderezada.save(
                    buffer, format="JPEG", quality="keep", subsampling="keep"
                )
            except (OSError, ValueError):
                buffer = io.BytesIO()
                enderezada.save(buffer, format="JPEG", quality=95)
        elif mime == "image/png":
            enderezada.save(buffer, format="PNG", optimize=True)
        else:
            enderezada.save(buffer, format="WEBP", quality=90)
        return buffer.getvalue()


def generar_miniatura(contenido: bytes) -> bytes:
    """Genera la miniatura en JPEG.

    Se re-codifica desde cero: así se **descarta el EXIF** (que en fotos
    de móvil incluye GPS y modelo de cámara) y el resultado siempre es un
    JPEG neutro que se puede servir como ``image/jpeg`` sin sorpresas.
    """
    with Image.open(io.BytesIO(contenido)) as imagen:
        imagen.load()
        # OJO (T-90): Pillow 13 viene con tipos y ``Image.open`` devuelve
        # un ``ImageFile``, mientras que ``convert`` devuelve un ``Image``.
        # Antes se reasignaba la misma variable con las dos cosas y
        # ``mypy --strict`` (que el CI ejecuta) lo hacia fallar: se
        # reescriben las conversiones en otra variable.
        resultado: Image.Image = imagen
        if imagen.mode in ("RGBA", "LA", "P"):
            # El alfa se compone sobre blanco: un PNG con transparencia
            # no puede convertirse a JPEG directamente.
            fondo = Image.new("RGB", imagen.size, (255, 255, 255))
            rgba = imagen.convert("RGBA")
            fondo.paste(rgba, mask=rgba.split()[-1])
            resultado = fondo
        elif imagen.mode != "RGB":
            resultado = imagen.convert("RGB")
        resultado.thumbnail((TAM_MINIATURA, TAM_MINIATURA), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resultado.save(buffer, format="JPEG", quality=82, optimize=True)
        return buffer.getvalue()


def _otras_referencias(
    db: Session, relativa: str, excluir_id: int | None = None
) -> int:
    """Cuántas filas (aparte de ``excluir_id``) apuntan a esa ruta.

    Con el nombre por hash, dos adjuntos con el mismo contenido
    comparten fichero: no se puede borrar el disco mientras quede una
    fila viva que lo use.
    """
    consulta = db.query(IncidentAttachment).filter(
        or_(
            IncidentAttachment.storage_path == relativa,
            IncidentAttachment.thumbnail_path == relativa,
        )
    )
    if excluir_id is not None:
        consulta = consulta.filter(IncidentAttachment.id != excluir_id)
    return consulta.count()


def contar_adjuntos(db: Session, alert_id: int) -> int:
    """Número de fotos **vigentes** ya adjuntas a un incidente.

    T-144 (2026-10-24): una foto caducada ya no se puede descargar (410)
    ni sale en el listado, asi que **no ocupa cupo**. Antes si contaba: un
    incidente con tres fotos caducadas no admitia ninguna nueva (el
    operador no podia documentar nada en el) y las fotos caducadas
    ocupaban un cupo invisible.

    OJO: la caducidad se comprueba **en Python**, no en SQL, porque un
    ``DateTime(timezone=True)`` vuelve *naive* en SQLite y compararlo con
    un datetime con zona revienta. Es el mismo ajuste que hace
    ``app/api/v1/incidents.py`` (``_exigir_no_caducado``).
    """
    ahora = datetime.now(timezone.utc)
    total = 0
    for adjunto in db.query(IncidentAttachment).filter(
        IncidentAttachment.alert_id == alert_id
    ).all():
        caducidad = adjunto.expires_at
        if caducidad is None:
            total += 1
            continue
        if caducidad.tzinfo is None:
            caducidad = caducidad.replace(tzinfo=timezone.utc)
        if caducidad > ahora:
            total += 1
    return total


def maximo_ficheros() -> int:
    """Máximo de ficheros por incidente (3 por defecto)."""
    return get_settings().incident_attachment_max_files


def crear_adjunto(
    db: Session,
    *,
    alert: Alert,
    contenido: bytes,
    nombre_original: str,
    usuario: User,
    base_dir: Path | None = None,
) -> IncidentAttachment:
    """Valida, guarda en el volumen y crea la fila de metadata.

    NO hace ``commit``: lo decide el caller (el endpoint).
    """
    base = base_dir or directorio_base()
    asegurar_directorio(base)
    mime = validar_imagen(contenido, nombre=nombre_original)

    # T-129 (2026-10-23): el original se guarda **sin metadatos**. Una
    # foto de movil lleva la GPS, el modelo de camara y la hora: dato
    # personal que el sistema no necesita y que salia con cada descarga
    # (LOPDGDD, minimizacion). Se conservan los pixeles y la orientacion.
    try:
        contenido_guardado = sanear_metadatos(contenido, mime)
    except (OSError, ValueError) as exc:
        # La imagen ya se ha validado (Pillow la abrio y decodifico), asi
        # que llegar aqui es raro. No se guarda con metadatos: se rechaza
        # la subida, que es la decision segura para la privacidad.
        log.warning(
            "incident_attachments: no se pudo sanear la imagen %s: %s",
            nombre_seguro(nombre_original),
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El fichero '{nombre_seguro(nombre_original)}' está corrupto "
                f"o no se puede decodificar como imagen"
            ),
        ) from exc

    # El hash es del contenido **guardado**: dos subidas del mismo
    # fichero (con EXIF distinto cada vez) tienen que compartir el
    # fichero del volumen, que es lo que hace la deduplicacion.
    hash_hex = hashlib.sha256(contenido_guardado).hexdigest()
    relativa = ruta_relativa_original(hash_hex, EXTENSIONES[mime])
    relativa_thumb = ruta_relativa_thumbnail(hash_hex)

    destino = base / relativa
    if not destino.exists():
        _escribir(destino, contenido_guardado)
    destino_thumb = base / relativa_thumb
    if not destino_thumb.exists():
        try:
            miniatura = generar_miniatura(contenido_guardado)
        except (OSError, ValueError) as exc:
            # El fichero pasa la comprobación de la firma (JPEG/PNG/WebP)
            # pero **no se puede decodificar**: está corrupto o truncado.
            # Es un problema del fichero que nos manda el cliente, no del
            # servidor, así que se responde 400 y no 500. Sin esto, subir
            # una foto a medio escribir tumbaba la petición con un 500.
            _unlink(destino)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"El fichero '{nombre_seguro(nombre_original)}' está corrupto "
                    f"o no se puede decodificar como imagen"
                ),
            ) from exc
        _escribir(destino_thumb, miniatura)

    ahora = datetime.now(timezone.utc)
    retencion = get_settings().incident_attachment_retention_days
    adjunto = IncidentAttachment(
        alert_id=alert.id,
        parking_id=alert.parking_id,
        uploaded_by=usuario.id,
        original_filename=nombre_seguro(nombre_original),
        content_hash=hash_hex,
        mime_type=mime,
        size_bytes=len(contenido_guardado),
        storage_path=relativa,
        thumbnail_path=relativa_thumb,
        expires_at=ahora + timedelta(days=retencion),
    )
    db.add(adjunto)
    return adjunto


def borrar_adjunto(
    db: Session, adjunto: IncidentAttachment, base_dir: Path | None = None
) -> None:
    """Borra la fila y el fichero del disco (si ninguna otra fila lo usa)."""
    base = base_dir or directorio_base()
    rutas: list[Path] = []
    for relativa in (adjunto.storage_path, adjunto.thumbnail_path):
        if not relativa:
            continue
        if _otras_referencias(db, relativa, excluir_id=adjunto.id) == 0:
            rutas.append(base / relativa)
    db.delete(adjunto)
    db.commit()
    for ruta in rutas:
        _unlink(ruta)


def a_esquema(adjunto: IncidentAttachment) -> IncidentAttachmentRead:
    """Convierte la fila de metadata en el esquema de la API."""
    return IncidentAttachmentRead(
        id=adjunto.id,
        alert_id=adjunto.alert_id,
        parking_id=adjunto.parking_id,
        uploaded_by=adjunto.uploaded_by,
        original_filename=adjunto.original_filename,
        content_hash=adjunto.content_hash,
        mime_type=adjunto.mime_type,
        size_bytes=adjunto.size_bytes,
        thumbnail_url=f"/api/v1/incidents/attachments/{adjunto.id}/thumbnail",
        download_url=f"/api/v1/incidents/attachments/{adjunto.id}/download",
        expires_at=adjunto.expires_at,
        created_at=adjunto.created_at,
    )


# ── Retención (LOPDGDD) ─────────────────────────────────────────────────
def purgar_adjuntos_vencidos(
    db: Session,
    retention_days: int | None = None,
    base_dir: Path | None = None,
) -> dict[str, object]:
    """Borra las fotos más antiguas que la retención y sus ficheros.

    Idempotente: si no hay nada que borrar devuelve ``deleted=0``.
    """
    settings = get_settings()
    dias = retention_days if retention_days is not None else settings.incident_attachment_retention_days
    ahora = datetime.now(timezone.utc)
    corte = ahora - timedelta(days=dias)
    base = base_dir or directorio_base()

    # Criterio de purga (T-95): el MISMO que usa el endpoint al servir.
    # Antes se purgaba por ``created_at < ahora - retencion`` y el
    # endpoint no miraba nada: la foto se seguia sirviendo aunque
    # ``expires_at`` hubiera pasado. Dos criterios para la misma regla
    # es como se rompe una regla.
    if retention_days is None:
        criterio = or_(
            # Lo que ha caducado: es exactamente lo que el endpoint
            # devuelve con 410 Gone.
            IncidentAttachment.expires_at.is_not(None)
            & (IncidentAttachment.expires_at < ahora),
            # Los antiguos, sin ``expires_at`` (antes de que existiera
            # el campo), se purgan por su fecha de creacion: si no, esos
            # ficheros no se borrarian nunca.
            IncidentAttachment.expires_at.is_(None)
            & (IncidentAttachment.created_at < corte),
        )
    else:
        # Retencion explicita (``--retention-days``): se purga por la
        # fecha de creacion, que es lo que el operador ha pedido.
        criterio = IncidentAttachment.created_at < corte

    adjuntos = db.query(IncidentAttachment).filter(criterio).all()
    ids_a_borrar = {adjunto.id for adjunto in adjuntos}

    # T-141 (2026-10-24): las referencias se cuentan **despues** de saber
    # que adjuntos se purgan, no antes. Antes se miraba si OTRO adjunto
    # usaba el mismo fichero, y con dos adjuntos que comparten el mismo
    # ``storage_path`` (medido: los adjuntos 3 y 4 de la QA, con el mismo
    # hash) cada uno veia al otro como "otra referencia": el fichero no se
    # borraba nunca y las filas si. Un huerfano perpetuo, con la BD
    # diciendo que la foto ya no existe.
    #
    # Ahora se calcula el conjunto de rutas **vivas** (las que referencia un
    # adjunto que NO se purga) y se borra todo lo demas.
    vivos = db.query(IncidentAttachment).all()
    vivas: set[str] = set()
    for adjunto in vivos:
        if adjunto.id in ids_a_borrar:
            continue
        if adjunto.storage_path:
            vivas.add(adjunto.storage_path)
        if adjunto.thumbnail_path:
            vivas.add(adjunto.thumbnail_path)

    rutas: list[Path] = []
    vistas: set[str] = set()
    for adjunto in adjuntos:
        for relativa in (adjunto.storage_path, adjunto.thumbnail_path):
            if not relativa or relativa in vistas:
                continue
            vistas.add(relativa)
            if relativa in vivas:
                continue
            rutas.append(base / relativa)

    # T-141: el proceso puede estar mirando un volumen que **no** es el
    # compartido (measured: el worker tenia un volumen ANONIMO distinto del
    # backend). En ese caso la purga borraba las filas, decia `deleted: N`
    # y los ficheros se quedaban en el disco del backend para siempre: la
    # retencion no se cumplia y nadie se enteraba. Se comprueba ANTES de
    # borrar: si hay adjuntos vivos cuyo fichero no esta, se avisa.
    faltantes = 0
    for adjunto in vivos:
        if adjunto.id in ids_a_borrar:
            continue
        for relativa in (adjunto.storage_path, adjunto.thumbnail_path):
            if relativa and not (base / relativa).exists():
                faltantes += 1

    for adjunto in adjuntos:
        db.delete(adjunto)
    db.commit()

    # Y se distingue lo que se ha borrado de lo que ya no estaba: `deleted`
    # son filas; los ficheros van por separado.
    borrados = 0
    inexistentes = 0
    for ruta in rutas:
        if ruta.exists():
            _unlink(ruta)
            borrados += 1
        else:
            inexistentes += 1

    if faltantes:
        log.error(
            "purgar_adjuntos_vencidos: %s fichero(s) de adjuntos VIVOS no "
            "estan en %s: este proceso NO ve el volumen de adjuntos (la "
            "retencion no se cumplira)",
            faltantes, base,
        )

    log.info(
        "purgar_adjuntos_vencidos: dias=%s corte=%s borrados=%s ficheros=%s "
        "inexistentes=%s faltantes=%s",
        dias, corte.isoformat(), len(adjuntos), borrados, inexistentes, faltantes,
    )
    return {
        "deleted": len(adjuntos),
        "retention_days": dias,
        "cutoff": corte.isoformat(),
        "files_deleted": borrados,
        "files_missing": inexistentes,
        "files_absent_of_live": faltantes,
    }


def purgar_ficheros_huerfanos(
    db: Session, base_dir: Path | None = None, min_age_hours: int = 0
) -> dict[str, int]:
    """Borra del volumen los ficheros que ya no tiene ninguna fila.

    Es la red de seguridad del derecho al olvido: si una fila se borró
    en la BD (por ejemplo al eliminar al usuario) y el proceso semurió
    antes de limpiar el disco, el fichero se queda huérfano. Aquí se
    recoge.

    OJO (T-141, 2026-10-24): ``min_age_hours`` es el margen de seguridad.
    ``crear_adjunto`` **escribe el fichero antes de crear la fila**, así
    que hay una ventana en la que un fichero recién subido todavía no
    tiene fila: borrarlo ahí sería perder la foto que el operador acaba
    de subir. La tarea programada usa 1 hora; el valor 0 (por defecto)
    borra todo, que es lo que necesitan los tests.

    Y también (T-141): si hay adjuntos **vivos** cuyo fichero no está en
    el disco, es que este proceso **no ve el volumen compartido**. Se
    avisa en el log y en el resultado, en vez de decir «todo bien».
    """
    base = base_dir or directorio_base()
    if not base.exists():
        return {"deleted": 0, "kept": 0, "skipped_recent": 0, "files_absent_of_live": 0}

    adjuntos = db.query(IncidentAttachment).all()
    vivas: set[str] = set()
    faltantes = 0
    for adjunto in adjuntos:
        if adjunto.storage_path:
            vivas.add(adjunto.storage_path)
            if not (base / adjunto.storage_path).exists():
                faltantes += 1
        if adjunto.thumbnail_path:
            vivas.add(adjunto.thumbnail_path)
            if not (base / adjunto.thumbnail_path).exists():
                faltantes += 1

    ahora = datetime.now(timezone.utc)
    borrados = 0
    conservados = 0
    recientes = 0
    for carpeta in ("originales", "miniaturas"):
        raiz = base / carpeta
        if not raiz.exists():
            continue
        for ruta in raiz.rglob("*"):
            if not ruta.is_file():
                continue
            relativa = ruta.relative_to(base).as_posix()
            if relativa in vivas:
                conservados += 1
                continue
            if min_age_hours > 0:
                mtime = datetime.fromtimestamp(ruta.stat().st_mtime, tz=timezone.utc)
                if (ahora - mtime).total_seconds() < min_age_hours * 3600:
                    recientes += 1
                    continue
            _unlink(ruta)
            borrados += 1

    if faltantes:
        log.error(
            "purgar_ficheros_huerfanos: %s fichero(s) de adjuntos VIVOS no "
            "estan en %s: este proceso NO ve el volumen de adjuntos",
            faltantes, base,
        )

    log.info(
        "purgar_ficheros_huerfanos: borrados=%s conservados=%s recientes=%s "
        "faltantes=%s",
        borrados, conservados, recientes, faltantes,
    )
    return {
        "deleted": borrados,
        "kept": conservados,
        "skipped_recent": recientes,
        "files_absent_of_live": faltantes,
    }


# ── Derecho al olvido ───────────────────────────────────────────────────
def _encolar_borrado_fichero(
    session: Session, base: Path, adjunto: IncidentAttachment
) -> None:
    """Encola (para borrar tras el commit) los ficheros de un adjunto.

    Se encola y NO se borra en el acto: si la transacción se deshace,
    las filas siguen vivas y el fichero debe seguir ahí.
    """
    pendientes = session.info.setdefault(_CLAVE_PENDIENTES, [])
    for relativa in (adjunto.storage_path, adjunto.thumbnail_path):
        if not relativa:
            continue
        if _otras_referencias(session, relativa, excluir_id=adjunto.id) == 0:
            pendientes.append(base / relativa)


@event.listens_for(Session, "before_flush")
def _purgar_datos_al_borrar_usuario(
    session: Session, flush_context: Any, instances: Any
) -> None:
    """Derecho al olvido: al borrar un usuario, se borran sus datos.

    Borra (a) las fotos que subió y (b) los incidentes (``alerts``) que
    reportó, lo que arrastra sus propias fotos. Los ficheros del disco
    se borran en el ``after_commit`` (este hook corre dentro de la
    transacción).

    Se hace aquí y no sólo con el ``ON DELETE CASCADE`` de la BD porque
    SQLite no aplica las claves foráneas por defecto: el borrado
    explícito funciona igual en los dos motores.
    """
    usuarios = [
        obj for obj in session.deleted if isinstance(obj, User) and obj.id is not None
    ]
    if not usuarios:
        return

    ids = [u.id for u in usuarios]
    base = directorio_base()
    with session.no_autoflush:
        adjuntos = (
            session.query(IncidentAttachment)
            .filter(IncidentAttachment.uploaded_by.in_(ids))
            .all()
        )
        incidentes = (
            session.query(Alert).filter(Alert.created_by.in_(ids)).all()
        )
        ids_incidentes = [inc.id for inc in incidentes]
        if ids_incidentes:
            adjuntos = adjuntos + (
                session.query(IncidentAttachment)
                .filter(IncidentAttachment.alert_id.in_(ids_incidentes))
                .all()
            )

    vistos: dict[int, IncidentAttachment] = {a.id: a for a in adjuntos}
    for adjunto in vistos.values():
        _encolar_borrado_fichero(session, base, adjunto)
        session.delete(adjunto)
    for incidente in incidentes:
        session.delete(incidente)


@event.listens_for(Session, "after_commit")
def _borrar_ficheros_pendientes(session: Session) -> None:
    """Borra del disco los ficheros encolados por el hook anterior."""
    pendientes = session.info.pop(_CLAVE_PENDIENTES, None)
    if not pendientes:
        return
    for ruta in pendientes:
        _unlink(ruta)


@event.listens_for(Session, "after_rollback")
def _descartar_ficheros_pendientes(session: Session) -> None:
    """Si la transacción se deshace, los ficheros se quedan (hay filas)."""
    session.info.pop(_CLAVE_PENDIENTES, None)


__all__ = [
    "MIME_JPEG",
    "MIME_PNG",
    "MIME_WEBP",
    "EXTENSIONES",
    "a_esquema",
    "borrar_adjunto",
    "contar_adjuntos",
    "crear_adjunto",
    "detectar_mime_por_bytes",
    "directorio_base",
    "generar_miniatura",
    "maximo_ficheros",
    "nombre_seguro",
    "purgar_adjuntos_vencidos",
    "purgar_ficheros_huerfanos",
    "ruta_relativa_original",
    "ruta_relativa_thumbnail",
    "validar_imagen",
]
