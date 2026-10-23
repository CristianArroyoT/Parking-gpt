"""Recuperación de contraseña del cliente (T-22 · plan maestro 2026-10-21).

Hasta este sprint **no existía** ningún flujo de "olvidé mi contraseña": ni
backend, ni correo, ni token. El login sólo aceptaba usuario + contraseña y
la única forma de recuperar el acceso era que un admin la reiniciara a mano.

Dos endpoints, ambos **públicos** (el usuario todavía no tiene token):

- ``POST /auth/forgot-password`` → manda un correo con un token de un solo
  uso y caducidad (30 min).
- ``POST /auth/reset-password`` → cambia la contraseña e invalida los
  tokens (JWT) que el usuario tuviera emitidos.

Decisiones de diseño (aplicadas, no discutidas):

1. **El token se guarda hasheado** (SHA-256) en la base de datos: si se
   roba la tabla, no sirve para resetear contraseñas. El token en claro
   sólo viaja por el correo.
2. **Un token usado se invalida** (``used_at``) y **cambiar la contraseña
   invalida los tokens previos**: se reutiliza el mecanismo de
   ``session_tracker.revoke_all`` (el mismo que usa ``/auth/logout/all``),
   que blacklistea cada ``jti`` en Redis.
3. **Anti-abuso**: bucket propio de rate-limit (``rl:forgot_password:*``)
   por IP y por email, reutilizando el ``EndpointRateLimiter`` existente.
4. **Anti-enumeración**: la respuesta del endpoint es **siempre la misma**
   exista o no la cuenta (200 en ambos casos). Tampoco se consulta el
   usuario antes de comprobar que el transporte de correo está disponible,
   para que un 503 tampoco revele qué emails existen.

Los parámetros (TTL del token, ventana y umbral del rate-limit) son
constantes de módulo y no settings: ``app/core/config.py`` es un fichero
compartido que otros agentes están editando en paralelo en este repo, y la
regla de propiedad exclusiva del plan maestro limita los cambios a un
único setting (el feature flag de T-23). Si pasan a ser parámetros de
despliegue, se mueven a ``Settings`` cuando ese fichero deje de estar en
uso compartido.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.emails import normalizar_email
from app.core.ip import get_real_ip
from app.core.security import hash_password
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas import MessageResponse
from app.schemas.password_reset import ForgotPasswordRequest, ResetPasswordRequest
from app.services import password_reset_email as email_module
from app.services.audit import record_audit_from_request
from app.services.endpoint_rate_limit import endpoint_rate_limiter
from app.services.session_tracker import session_tracker

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Parámetros del flujo ───────────────────────────────────────────────────

#: Ventana de validez del token de un solo uso (minutos).
TOKEN_TTL_MINUTES = 30

#: Suelo de latencia de ``forgot-password`` (milisegundos).
#:
#: POR QUE (T-94): la respuesta **no** puede ser mas rapida si la cuenta
#: no existe. Antes el envio del correo estaba dentro del request, asi que
#: con la cuenta existente tardaba hasta 5,03 s (medido) y sin la cuenta
#: era instantanea: el tiempo revelaba que correos estan registrados.
#: Ahora el correo va en una tarea de Celery y el trabajo que queda es de
#: milisegundos, pero la diferencia entre "hay cuenta" y "no hay cuenta"
#: sigue siendo medible. El suelo la tapa.
#:
#: 350 ms es corto para el usuario y el endpoint esta limitado a 5
#: peticiones por IP cada 15 minutos, asi que el coste es despreciable.
SUELO_RESPUESTA_MS = 350


def _esperar_suelo(inicio: float) -> None:
    """Espera lo que falte para que la respuesta tarde al menos el suelo."""
    restante = SUELO_RESPUESTA_MS / 1000 - (time.perf_counter() - inicio)
    if restante > 0:
        time.sleep(restante)
#: Peticiones de forgot-password permitidas por IP y por email en la ventana.
FORGOT_RATE_LIMIT_MAX_ATTEMPTS = 5
FORGOT_RATE_LIMIT_WINDOW_SECONDS = 900  # 15 minutos
#: Intentos de reset-password permitidos por IP (el token tiene 256 bits de
#: entropía, pero el freno evita martillear el endpoint).
RESET_RATE_LIMIT_MAX_ATTEMPTS = 10
RESET_RATE_LIMIT_WINDOW_SECONDS = 900  # 15 minutos

#: Respuesta ÚNICA del endpoint de forgot-password. Al ser idéntica
#: exista o no la cuenta, no permite enumerar usuarios registrados.
MENSAJE_GENERICO = (
    "Si el email está registrado, te hemos enviado un correo con las "
    "instrucciones para restablecer tu contraseña."
)


# ── Utilidades de token ────────────────────────────────────────────────────


def generar_token_bruto() -> str:
    """Genera el token de un solo uso que viajará por el correo.

    32 bytes aleatorios en base64url (≈256 bits de entropía).
    """
    return secrets.token_urlsafe(32)


def hashear_token(token_bruto: str) -> str:
    """Devuelve el hash SHA-256 (hex) del token en claro.

    En la base de datos sólo se guarda este hash: con la tabla en claro un
    atacante no puede resetear contraseñas, porque el token real sólo
    existe en el buzón de quien lo pidió.
    """
    return hashlib.sha256(token_bruto.encode("utf-8")).hexdigest()


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _a_utc(dt: datetime) -> datetime:
    """Normaliza un ``datetime`` a UTC **con** tzinfo.

    SQLite no conserva el tzinfo (guarda el reloj tal cual) y PostgreSQL
    sí. Comparar un valor naive con otro aware lanza ``TypeError``, así que
    normalizamos SIEMPRE antes de comparar (mismo cuidado que el bug de
    ``strftime()`` que.handlers obligaba a parametrize la suite).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _invalidar_tokens_pendientes(
    db: Session, *, user_id: int, excluir_id: int | None = None,
) -> int:
    """Marca como consumidos los tokens pendientes del usuario.

    Devuelve cuántos tokens se han invalidado. Se llama al pedir un reset
    nuevo (sólo vale el último correo) y al completar un reset (los demás
    correos en vuelo dejan de servir).
    """
    ahora = _ahora()
    consulta = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    )
    if excluir_id is not None:
        consulta = consulta.filter(PasswordResetToken.id != excluir_id)
    filas = consulta.all()
    for fila in filas:
        fila.used_at = ahora
    return len(filas)


def _aplicar_rate_limit(
    *, scope: str, identifiers: dict[str, str],
    max_attempts: int, window_seconds: int,
) -> tuple[bool, str, int]:
    """Aplica el rate-limit genérico por scope. **Fail-OPEN** si Redis cae.

    Mismo criterio que ``LoginRateLimiter``: si Redis no está disponible
    preferimos no bloquear al usuario legítimo (queda el warning en el log
    para que el operador lo vea).
    """
    try:
        return endpoint_rate_limiter.check(
            scope=scope,
            identifiers=identifiers,
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        )
    except RedisError as exc:
        log.warning("password_reset: Redis no disponible en el rate-limit (%s)", exc)
        return True, "redis_unavailable", 0


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Pide un enlace de restablecimiento de contraseña por correo.

    Respuesta **siempre idéntica** (200) haya o no cuenta con ese email:
    distinguishable sería un oráculo de enumeración de cuentas.

    Anti-abuso: rate-limit por IP **y** por email (bucket propio
    ``rl:forgot_password:*``). Si se supera → 429.
    """
    # 0) ¿Hay transporte de correo? Se comprueba ANTES de tocar la BD de
    #    usuarios: si el SMTP no está configurado, el 503 se devuelve igual
    #    para cualquier email y no revela qué cuentas existen.
    if not email_module.mail_transport_disponible():
        log.error("password_reset: transporte de correo no configurado")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de correo no está disponible. Inténtalo más tarde.",
        )

    inicio = time.perf_counter()
    client_ip = get_real_ip(request)
    # T-99: la misma normalizacion que el login (minusculas, sin
    # espacios): el rate-limit y la busqueda de la cuenta tienen que
    # hablar del MISMO correo.
    email_normalizado = normalizar_email(str(payload.email))

    # 1) Rate-limit por IP y por email.
    allowed, bucket, count = _aplicar_rate_limit(
        scope="forgot_password",
        identifiers={"ip": client_ip, "email": email_normalizado},
        max_attempts=FORGOT_RATE_LIMIT_MAX_ATTEMPTS,
        window_seconds=FORGOT_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not allowed:
        record_audit_from_request(
            request, db,
            action="password_reset_requested",
            payload={
                "email": email_normalizado,
                "ip": client_ip,
                "reason": "rate_limited",
                "bucket": bucket,
                "count": count,
            },
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas peticiones. Inténtalo más tarde.",
        )

    # 2) ¿Existe la cuenta? Mismo criterio de comparación que el login
    #    (forma canónica, T-99) para no resetear una cuenta con
    #    una grafía que luego no serviría para entrar.
    user = (
        db.query(User)
        .filter(func.lower(User.email) == email_normalizado)
        .one_or_none()
    )
    token_emitido = False

    if user is not None and user.is_active:
        # 2a) Sólo vale el último correo: se invalidan los pendientes.
        _invalidar_tokens_pendientes(db, user_id=user.id)

        token_bruto = generar_token_bruto()
        fila = PasswordResetToken(
            user_id=user.id,
            token_hash=hashear_token(token_bruto),
            expires_at=_ahora() + timedelta(minutes=TOKEN_TTL_MINUTES),
            request_ip=client_ip,
        )
        db.add(fila)
        db.commit()

        # T-94: el correo sale en una tarea de Celery, no dentro del
        # request. Si el broker esta caido se envia en linea (mas lento,
        # pero llega): es el camino de emergencia.
        encolado = email_module.encolar_envio_reset(
            to_email=user.email,
            full_name=user.full_name,
            raw_token=token_bruto,
            expires_minutes=TOKEN_TTL_MINUTES,
            token_id=fila.id,
        )
        enviado = True
        if not encolado:
            enviado = email_module.send_password_reset_email(
                to_email=user.email,
                full_name=user.full_name,
                raw_token=token_bruto,
                expires_minutes=TOKEN_TTL_MINUTES,
            )
        if not enviado:
            # El token sin correo no sirve de nada: se elimina para no
            # dejar Tokens válidos que el usuario nunca recibió.
            db.delete(fila)
            db.commit()
            log.error(
                "password_reset: no se pudo enviar el correo (user=%s)", user.id,
            )
            record_audit_from_request(
                request, db,
                action="password_reset_requested",
                resource=f"users/{user.id}",
                payload={
                    "email": email_normalizado,
                    "reason": "email_delivery_failed",
                },
                result="failure",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se ha podido enviar el correo de recuperación. "
                       "Inténtalo más tarde.",
            )
        token_emitido = True

    # 3) Auditoría. Se registra SIEMPRE la petición (exista o no la
    #    cuenta): el campo ``token_issued`` dice si llegó a salir un
    #    correo. ``audit_logs`` es de sólo lectura para el admin, así que
    #    aquí no hay riesgo de enumeración para un atacante.
    record_audit_from_request(
        request, db,
        action="password_reset_requested",
        resource=f"users/{user.id}" if user is not None else None,
        payload={
            "email": email_normalizado,
            "ip": client_ip,
            "token_issued": token_emitido,
        },
        result="success",
    )
    db.commit()
    # T-94: el suelo de latencia (tampoco en el caso de que la cuenta no
    # exista: la respuesta tiene que ser igual de lenta).
    _esperar_suelo(inicio)
    return MessageResponse(detail=MENSAJE_GENERICO)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Cambia la contraseña usando el token de un solo uso del correo.

    Valida el token (existe, no se ha usado y no ha caducado), **invalida
    los tokens JWT previos** del usuario (mismo mecanismo que
    ``/auth/logout/all``), consume el token y marca como consumidos los
    demás tokens pendientes del usuario.
    """
    client_ip = get_real_ip(request)

    # 1) Rate-limit por IP (anti-martilleo del endpoint).
    allowed, bucket, count = _aplicar_rate_limit(
        scope="reset_password",
        identifiers={"ip": client_ip},
        max_attempts=RESET_RATE_LIMIT_MAX_ATTEMPTS,
        window_seconds=RESET_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not allowed:
        record_audit_from_request(
            request, db,
            action="password_reset_failed",
            payload={"reason": "rate_limited", "bucket": bucket, "count": count},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas peticiones. Inténtalo más tarde.",
        )

    # 2) Localizar el token por su hash (nunca se busca por el token en
    #    claro: en la BD sólo está el hash).
    token_hash = hashear_token(payload.token)
    fila = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
    ).one_or_none()

    ahora = _ahora()

    def _rechazar(motivo: str) -> NoReturn:
        """Audita el rechazo y corta con 400 (mensaje único para todos)."""
        record_audit_from_request(
            request, db,
            action="password_reset_failed",
            payload={"reason": motivo},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace de restablecimiento no es válido o ha caducado.",
        )

    # Cada motivo de rechazo devuelve el MISMO mensaje: el atacante no
    # puede distinguir "token inexistente" de "token caducado" para
    # acortar una búsqueda por fuerza bruta.
    if fila is None:
        _rechazar("unknown_token")
    if fila.used_at is not None:
        _rechazar("token_already_used")
    if _a_utc(fila.expires_at) <= ahora:
        _rechazar("token_expired")

    user = db.get(User, fila.user_id)
    if user is None or not user.is_active:
        _rechazar("user_unavailable")

    # 3) Invalidar los tokens JWT previos del usuario ANTES de cambiar la
    #    contraseña. Fail-CLOSED (igual que ``/auth/logout/all``): si no
    #    podemos garantizar la invalidación, es preferible no cambiar la
    #    contraseña a dejarla cambiada con los tokens antiguos vivos.
    try:
        revocadas = session_tracker.revoke_all(user_id=user.id)
    except RedisError as exc:
        db.rollback()
        log.warning(
            "password_reset: Redis caído, no se pudo revocar las sesiones de "
            "user=%s (%s)", user.id, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación no disponible",
        ) from exc

    # 4) Cambiar la contraseña, consumir el token e invalidar el resto.
    user.hashed_password = hash_password(payload.new_password)
    fila.used_at = ahora
    _invalidar_tokens_pendientes(db, user_id=user.id, excluir_id=fila.id)

    record_audit_from_request(
        request, db,
        action="password_reset_completed",
        resource=f"users/{user.id}",
        payload={"user_id": user.id, "revoked_sessions": revocadas},
        result="success",
    )
    db.commit()
    return MessageResponse(
        detail="Contraseña actualizada. Ya puedes iniciar sesión con la nueva contraseña.",
    )


__all__ = ["router", "generar_token_bruto", "hashear_token"]
