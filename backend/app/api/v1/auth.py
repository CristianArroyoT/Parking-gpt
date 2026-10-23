"""Router de autenticación."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from redis.exceptions import RedisError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.emails import normalizar_email
from app.core.db import get_db
from app.core.ip import get_real_ip
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password_or_dummy,
)
from app.models.user import User
from app.schemas import LoginRequest, LogoutRequest, MessageResponse, TokenPair
from app.services.audit import record_audit_from_request
from app.services.rate_limit import rate_limiter
from app.services.session_tracker import session_tracker
from app.services.token_blacklist import token_blacklist

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _bind_audit_user(request: Request | None, user: User) -> None:
    """Enriquece el contexto de auditoría con el ``user_id`` del login.

    POR QUÉ (T-08, plan maestro 2026-10-21): la petición de login NO
    lleva header ``Authorization`` — el cliente todavía no tiene token—,
    así que el ``AuditMiddleware`` no tiene ningún JWT que decodificar
    y su ``request.state.audit["user_id"]`` queda a ``None``. Pero el
    handler, después de validar la contraseña, SÍ sabe quién entra.

    Sin este enrichment la auditoría de accesos queda coja: la fila
    ``login_success`` no dice QUIÉN entró, sólo que alguien entró. Y
    como el login es el único punto donde el usuario aún no tiene
    token, es la única acción del sistema en la que el middleware
    estructuralmente no puede completar la fila.

    El enrichment es aditivo: no se toca ``ip`` ni ``correlation_id``
    (que sólo el middleware puede conocer), sólo se rellena el
    ``user_id`` que el middleware no puede deducir aquí.
    """
    if request is None:
        return
    audit_ctx = getattr(request.state, "audit", None)
    if isinstance(audit_ctx, dict):
        audit_ctx["user_id"] = user.id


def _build_tokens(user: User) -> TokenPair:
    settings = get_settings()
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
    access = create_access_token(user.id, extra={"role": role_value})
    refresh = create_refresh_token(user.id)
    # Sprint R2-followup: trackea los jtis (access + refresh) en el set
    # ``user:{id}:active_jtis`` para que ``POST /auth/logout/all`` pueda
    # invalidarlos.
    #
    # T-109: antes esto era FAIL-OPEN (si Redis caia, los tokens se
    # devolvian igualmente). El problema: el middleware de auditoria ya es
    # fail-CLOSED (si Redis cae, toda peticion con token devuelve 401), asi
    # que un token emitido con Redis caido no servia para nada... hasta
    # que Redis volvia. Y entonces ese token **no estaba registrado**, de
    # modo que un cambio de contrasena (que revoca las sesiones
    # registradas) no lo revocaba: sobrevivia al reset.
    #
    # Ahora es fail-CLOSED, como el middleware: si no se puede registrar
    # la sesion, no se emite el token (503). El usuario recibe un mensaje
    # claro ("el servicio de autenticacion no esta disponible") en vez de
    # un token que no funciona, y no queda ningun token sin rastrear.
    access_registrado = session_tracker.track_session(
        user_id=user.id, jti=decode_token(access)["jti"],
    )
    refresh_registrado = session_tracker.track_session(
        user_id=user.id, jti=decode_token(refresh)["jti"],
    )
    if not (access_registrado and refresh_registrado):
        log.error(
            "login: no se pudo registrar la sesion de user=%s; no se emite "
            "el token (Redis no disponible)", user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación no disponible",
        )
    return TokenPair(
        access_token=access,
        expires_in=settings.access_token_ttl_minutes * 60,
        refresh_token=refresh,
    )


def _comprobar_rate_limit_login(
    request: Request,
    db: Session,
    email: str,
    extra: dict[str, object] | None = None,
) -> None:
    """Aplica el rate-limit de login (por IP y por email) y levanta el 429.

    La usan **las dos** vias de login (JSON y OAuth2). Antes cada una hacia
    su cuenta y la via OAuth2 se olvidaba del limitador, de modo que cambiar
    el ``Content-Type`` de la peticion esquivaba la proteccion de fuerza
    bruta (T-59, medido: 15 intentos por la via oauth sin un solo 429).

    Fail-open si Redis cae (igual que ``LoginRateLimiter``).
    """
    client_ip = get_real_ip(request)
    allowed, bucket, count = rate_limiter.check(ip=client_ip, email=email)
    if allowed:
        return
    payload = {"email": email, "ip": client_ip, "bucket": bucket, "count": count}
    if extra:
        payload.update(extra)
    record_audit_from_request(
        request, db,
        action="rate_limited_login",
        payload=payload,
        result="failure",
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Demasiados intentos. Intenta más tarde.",
    )


def _cuenta_demo_bloqueada(email: str) -> bool:
    """¿Es una cuenta de demostracion que no puede entrar en produccion?

    POR QUE (T-98, 2026-10-23): el seed ya se niega a crear estas
    cuentas fuera de desarrollo (T-83), pero **el login no las
    filtraba**: si la base de datos arrastraba cuentas de una
    instalacion de desarrollo (un dump, una copia, una restauracion
    vieja), las credenciales **publicas de este repositorio** (y del
    README) servirian para entrar como administrador.

    El rechazo es un **401 como el de cualquier contrasena incorrecta**:
    un 403 distinto ("cuenta de demostracion") dira que ese correo
    existe, que es justo el oraculo que T-86 acaba de tapar.

    En ``development`` y ``test`` no se bloquea: la QA visual y el
    ``fillDemo()`` de la pantalla de login las usan a proposito.
    """
    if get_settings().environment not in ("production", "staging"):
        return False
    from app.scripts.seed import DEMO_USERS

    normalizado = email.strip().lower()
    return any(normalizado == str(demo[0]).strip().lower() for demo in DEMO_USERS)


def _autenticar(
    request: Request,
    db: Session,
    email: str,
    password: str,
    extra: dict[str, object] | None = None,
) -> User:
    """Comprueba las credenciales y devuelve el usuario ACTIVO.

    La usan **las dos** vias de login (JSON y OAuth2). Antes cada una
    repetia el codigo y se desincronizaron (T-85): la via JSON
    comprobaba ``is_active`` y la via OAuth2 **no**. Con esta via, una
    cuenta desactivada recibia un 200 con tokens y un ``login_success``
    en la auditoria. El token no servia para nada (todo endpoint
    protegido vuelve a comprobar ``is_active``), pero la auditoria
    mentia: decia que un usuario desactivado habia entrado.

    Ademas, el tiempo de respuesta **no depende de que la cuenta
    exista**: si el email no esta, se verifica igualmente contra un hash
    senuelo (T-86). Medido antes del arreglo: 13,9 ms con un email
    inexistente frente a 207,6 ms con un email real y contrasena
    incorrecta.
    """
    # T-99: se compara en la forma canonica (minusculas). Sin esto, un
    # correo con mayusculas no encontraba la cuenta: medido el 2026-10-23
    # contra la API real, "gestor.mixto@solidapp.es" daba 401 para un
    # usuario guardado como "Gestor.Mixto@solidapp.es".
    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalizar_email(email))
        .one_or_none()
    )
    hashed = user.hashed_password if user is not None else None
    credenciales_ok = verify_password_or_dummy(password, hashed)
    extra_payload = dict(extra or {})
    if user is None or not credenciales_ok:
        record_audit_from_request(
            request, db,
            action="login_failure",
            payload={
                "email": email,
                "reason": "invalid_credentials",
                **extra_payload,
            },
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )
    if _cuenta_demo_bloqueada(user.email):
        # T-98: mismo 401 que una contrasena incorrecta (no un 403: no
        # se revela que el correo existe), pero auditado con su motivo.
        record_audit_from_request(
            request, db,
            action="login_failure",
            payload={"email": email, "reason": "demo_account", **extra_payload},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )
    if not user.is_active:
        record_audit_from_request(
            request, db,
            action="login_failure",
            payload={"email": email, "reason": "user_inactive", **extra_payload},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo"
        )
    return user


@router.post("/login", response_model=TokenPair)
def login_json(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenPair:
    # Sprint Fase 3C: rate-limit por IP + email (Redis INCR + EXPIRE).
    # Si CUALQUIER bucket supera ``login_rate_limit_max_attempts`` en
    # ``login_rate_limit_window_seconds`` → 429 Too Many Requests y
    # audit con ``action=rate_limited_login``. Fail-open si Redis cae.
    #
    # OJO (T-59): el limitador vive en una funcion compartida por las DOS
    # vias de login. Antes cada una hacia su cuenta y la via OAuth2 se
    # olvidaba del limitador: cambiar el ``Content-Type`` de la peticion
    # esquivaba la proteccion de fuerza bruta.
    _comprobar_rate_limit_login(request, db, payload.email)
    # OJO (T-85): las dos vias de login usan la MISMA autenticacion
    # (``_autenticar``). Antes cada una repetia el codigo y la via
    # OAuth2 se quedo sin la comprobacion de ``is_active``.
    user = _autenticar(request, db, payload.email, payload.password)
    # T-109: los tokens se construyen PRIMERO (ahi es donde se registra
    # la sesion, y puede fallar si Redis no esta). Si el aviso se
    # escribiera antes, diria "login_success" de un login que en
    # realidad salio con 503.
    tokens = _build_tokens(user)
    # Login OK: audit.
    # El middleware no puede saber quién entra (no hay token en la
    # request), así que le damos el user_id que el handler sí conoce.
    _bind_audit_user(request, user)
    record_audit_from_request(
        request, db,
        action="login_success",
        resource=f"users/{user.id}",
        payload={"email": user.email, "role": user.role.value if hasattr(user.role, "value") else str(user.role)},
        result="success",
    )
    db.commit()
    return tokens


@router.post("/login/oauth", response_model=TokenPair)
def login_oauth(
    form: OAuth2PasswordRequestForm = Depends(),
    # OJO: la anotación debe seguir siendo ``Request`` (no ``Request |
    # None``): FastAPI sólo inyecta la request cuando el tipo es
    # exactamente ``Request``; con la unión, la tomaría por un parámetro
    # del cuerpo y el endpoint dejaría de funcionar.
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
) -> TokenPair:
    # OJO (T-59): esta via hace el MISMO ``verify_password`` que la via
    # JSON, asi que tiene el MISMO rate-limit. Sin esto, cambiar el
    # ``Content-Type`` de la peticion esquivaba el limite (medido: 15
    # intentos por esta via, sin un solo 429).
    _comprobar_rate_limit_login(
        request, db, form.username, extra={"grant_type": "oauth_form"},
    )
    # OJO (T-85): misma autenticacion que la via JSON, incluida la
    # comprobacion de ``is_active`` (que esta via **no** hacia: una
    # cuenta desactivada se loggedaba por OAuth2 y recibia tokens).
    user = _autenticar(
        request, db, form.username, form.password,
        extra={"grant_type": "oauth_form"},
    )
    # T-109: igual que en el login JSON, los tokens se construyen
    # primero (ahi se registra la sesion y puede fallar si Redis no
    # esta): el aviso tiene que reflejar lo que de verdad paso.
    tokens = _build_tokens(user)
    # Mismo enrichment que en el login JSON: el handler sabe quién
    # entra, el middleware no (no hay token en la request de login).
    _bind_audit_user(request, user)
    record_audit_from_request(
        request, db,
        action="login_success",
        resource=f"users/{user.id}",
        payload={"email": user.email, "grant_type": "oauth_form"},
        result="success",
    )
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
def refresh(
    payload: TokenPair,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenPair:
    try:
        data = decode_token(payload.refresh_token)
    except ValueError as exc:
        record_audit_from_request(
            request, db,
            action="refresh_failure",
            payload={"reason": str(exc)},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if data.get("type") != "refresh":
        record_audit_from_request(
            request, db,
            action="refresh_failure",
            payload={"reason": "wrong_token_type"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de refresco requerido"
        )
    # Sprint Fase 3D (push security review 2026-07-01): si el refresh
    # ya está blacklisteado (p. ej. tras logout con body refresh_token),
    # rechazamos con 401. Sin este check, el bypass de 7 días del refresh
    # sigue abierto aunque el cliente haya enviado el refresh al logout.
    ref_jti = data.get("jti")
    if ref_jti is not None:
        try:
            if token_blacklist.is_blocked(ref_jti):
                record_audit_from_request(
                    request, db,
                    action="refresh_failure",
                    payload={"reason": "blacklisted", "jti": ref_jti},
                    result="failure",
                )
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token de refresco revocado",
                    headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
                )
        except RedisError as exc:
            log.warning(
                "refresh: Redis caído, fail-closed (%s)", exc,
            )
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación no disponible",
            ) from exc
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active:
        record_audit_from_request(
            request, db,
            action="refresh_failure",
            payload={"reason": "user_unavailable"},
            result="failure",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no disponible"
        )
    record_audit_from_request(
        request, db,
        action="refresh_success",
        resource=f"users/{user.id}",
        result="success",
    )
    db.commit()
    return _build_tokens(user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    payload: LogoutRequest = Body(default_factory=LogoutRequest),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Logout real: blacklistea access + refresh (si viene) en Redis.

    Sprint Fase 3D (2026-07-01). Antes (Fase 3A) sólo registraba audit.
    Sprint Fase 3D push security review (2026-07-01) — 2 hallazgos:

      1. **Logout-bypass fix**: añade el ``jti`` del access token al
         blacklist con TTL ``(exp - now) + grace_seconds``. Si el
         cliente envía ``refresh_token`` en el body, también lo
         decodifica y blacklistea su ``jti`` — cerrando el bypass que
         dejaba el refresh vivo durante 7 días.

      2. **Legacy-token-ORACLE fix**: rechaza con 401 si el token no
         tiene ``jti`` o el decode JWT falló (antes respondía 200
         ``jti_blacklisted=False`` — canal lateral para atacantes).

    Si Redis cae durante el blacklist → 503 ``Servicio de autenticación
    no disponible``. Fail-CLOSED: preferible un logout fallido antes
    que un token comprometido circulando.
    """
    audit = getattr(request.state, "audit", None) or {}
    user_id = audit.get("user_id")
    jti = audit.get("jti")
    exp = audit.get("exp")
    token_type = audit.get("type")
    decode_error = audit.get("decode_error", False)

    # Hard-fail si el token no se pudo decodificar o no es un access
    # válido con jti + exp. Cierra el oracle que devolvía 200 con
    # tokens malformados.
    if decode_error or jti is None or exp is None or token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no soportado para logout. Vuelve a iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1) Blacklist del access.
    try:
        token_blacklist.add(jti=jti, exp_epoch=int(exp))
    except RedisError as exc:
        db.rollback()
        log.warning(
            "logout: Redis caído, no se pudo blacklistear access jti=%s (%s)",
            jti, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de autenticación no disponible",
        ) from exc

    # 2) Blacklist del refresh si el cliente lo envía en el body.
    refresh_blacklisted = False
    if payload.refresh_token:
        try:
            ref_payload = decode_token(payload.refresh_token)
        except ValueError as exc:
            # El access ya está blacklisteado — devolvemos 401 pero
            # dejamos el audit con refresh_blacklisted=False para que
            # el operador vea que el refresh enviado era inválido.
            record_audit_from_request(
                request, db,
                action="logout_partial",
                resource=f"users/{user_id}" if user_id else None,
                payload={
                    "jti_blacklisted": True,
                    "refresh_jti_blacklisted": False,
                    "refresh_reason": f"decode_error: {exc}",
                },
                result="failure",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token inválido.",
            ) from exc
        ref_jti = ref_payload.get("jti")
        ref_exp = ref_payload.get("exp")
        ref_type = ref_payload.get("type")
        if ref_jti is None or ref_exp is None or ref_type != "refresh":
            record_audit_from_request(
                request, db,
                action="logout_partial",
                resource=f"users/{user_id}" if user_id else None,
                payload={
                    "jti_blacklisted": True,
                    "refresh_jti_blacklisted": False,
                    "refresh_reason": "missing_jti_or_wrong_type",
                },
                result="failure",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token no soportado.",
            )
        try:
            token_blacklist.add(jti=ref_jti, exp_epoch=int(ref_exp))
            refresh_blacklisted = True
        except RedisError as exc:
            db.rollback()
            log.warning(
                "logout: Redis cayó blacklisteando refresh jti=%s (%s)",
                ref_jti, exc,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación no disponible",
            ) from exc

    record_audit_from_request(
        request, db,
        action="logout_success",
        resource=f"users/{user_id}" if user_id else None,
        payload={
            "jti_blacklisted": True,
            "refresh_jti_blacklisted": refresh_blacklisted,
        },
        result="success",
    )
    db.commit()
    return MessageResponse(detail="Sesión cerrada")