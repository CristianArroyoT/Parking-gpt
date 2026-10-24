"""Dependencias compartidas: usuario actual, RBAC y contexto de sucursal."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from fastapi import Depends, HTTPException, Path, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_token
from app.models.enums import UserRole
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

#: Roles del personal: los que pueden operar sobre una sucursal.
#:
#: T-114 (2026-10-23): esto vivia duplicado en cada router (p.ej.
#: ``vehicles.py`` lo tenia como ``_STAFF``).
#:
#: T-178 (2026-10-24, ADR 0005): el rol global es el **techo** y el rol de
#: la sucursal (``parking_memberships.role_in_parking``) es el **poder real**:
#: el rol efectivo de una sucursal es el **más restrictivo** de los dos (ver
#: ``effective_parking_role``).
ROLES_STAFF: tuple[str, ...] = (
    UserRole.ADMIN.value,
    UserRole.GESTOR.value,
    UserRole.OPERADOR.value,
)

#: Roles válidos en la membresía de una sucursal (ADR 0005).
#:
#: El ``admin`` **no** es un rol por sucursal: el admin es global (regla 1
#: del ADR). Por eso una membresía con ``role_in_parking='admin'`` es
#: inválida y la API la rechaza con 422.
ROLES_DE_SUCURSAL: tuple[str, ...] = (
    UserRole.GESTOR.value,
    UserRole.OPERADOR.value,
    UserRole.CLIENTE.value,
)

#: Jerarquía de poder (ADR 0005) de **más** a **menos** poder:
#: ``admin > gestor > operador > cliente``. El índice mayor = menos poder.
JERARQUIA_ROLES: tuple[str, ...] = (
    UserRole.ADMIN.value,
    UserRole.GESTOR.value,
    UserRole.OPERADOR.value,
    UserRole.CLIENTE.value,
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decodifica el JWT, recupera el usuario activo o lanza 401."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token no válido",
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto")

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuario no válido",
        ) from exc

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo")
    return user


def require_role(*roles: str) -> Callable[..., Any]:
    """Devuelve una dependencia que valida el rol del usuario actual."""

    allowed = set(roles)

    def _checker(current: User = Depends(get_current_user)) -> User:
        role_value = current.role.value if hasattr(current.role, "value") else current.role
        if role_value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para esta operación",
            )
        return current

    return _checker


def get_current_user_or_query_token(
    request: Request,
    token: str | None = Query(default=None),
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Igual que ``get_current_user`` pero también acepta ``?token=...``.

    Pensado para endpoints cuyo consumidor no puede setear headers
    (``EventSource`` del SSE, ``<img>`` del live-preview MJPEG).
    ``Authorization`` NO permite añadir headers arbitrarios; por eso
    permitimos pasar el JWT en query string como fallback. Riesgo:
    el token queda en logs de proxies intermedios. Mitigado por
    ``ACCESS_TOKEN_TTL_MINUTES=15``.

    Si ni header ni query traen token → 401. Si ambos vienen → gana
    el header (``bearer_token`` no es ``None`` cuando viene el header).

    Sprint O2 (2026-07-06). Sprint Live-Preview (2026-07-07): la usa el
    endpoint ``GET /cameras/{id}/live`` (consumido por ``<img>``). NO
    se usa como dep de ``parking_context`` para no expandir el scope
    de auth del resto de routers REST — ver push security review.
    """
    raw: str | None = bearer_token or token
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de token no válido",
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin sujeto")

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuario no válido",
        ) from exc

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo")
    return user


def _valor_rol(rol: object) -> str:
    """El rol como texto.

    La columna es ``String``; tras recargar el ORM puede venir como enum o
    como ``str`` (depende del flush). Aceptamos ambos casos.
    """
    return str(getattr(rol, "value", rol))


def _poder_de_rol(rol: str) -> int:
    """El poder de un rol: **índice mayor = menos poder**.

    Un rol que no está en la jerarquía (dato corrupto) se trata como
    ``cliente``: el principio es *fail closed*, nunca *fail open*.
    """
    try:
        return JERARQUIA_ROLES.index(rol)
    except ValueError:
        return len(JERARQUIA_ROLES) - 1


def _rol_mas_restrictivo(rol_a: str, rol_b: str) -> str:
    """El de **menos** poder de los dos (ADR 0005, regla 2).

    OJO: aquí está la decisión de producto del ADR 0005 (el «techo»): el
    corte es por el rol **menos** poderoso de los dos, no por el de la
    sucursal. Cambiar esta función cambiaría la política entera del ADR.
    """
    if _poder_de_rol(rol_a) >= _poder_de_rol(rol_b):
        return rol_a
    return rol_b


def validar_rol_de_sucursal(valor: str) -> str:
    """Valida un ``role_in_parking`` (ADR 0005).

    Lanza ``ValueError`` (que pydantic convierte en **422**) si el valor no
    es uno de los roles por sucursal, o si es ``admin``: el admin es un rol
    **global**, no existe un admin «de una sucursal».

    OJO: esto valida la **forma** del valor. Que el rol **global** del
    usuario sea el techo se aplica al **leer** la membresía
    (``effective_parking_role``): escribir un rol más alto del global es
    admisible (queda recortado al leer), no un error.
    """
    normalizado = str(valor or "").strip().lower()
    if normalizado == UserRole.ADMIN.value:
        raise ValueError(
            "'admin' no es un rol por sucursal: el admin es global "
            "(ADR 0005). Usa 'gestor', 'operador' o 'cliente'."
        )
    if normalizado not in ROLES_DE_SUCURSAL:
        raise ValueError(
            f"'{valor}' no es un rol valido. Los roles por sucursal son: "
            f"{', '.join(ROLES_DE_SUCURSAL)}."
        )
    return normalizado


def _rol_de_la_sucursal(user: User, parking_id: int, db: Session) -> str:
    """El rol que el usuario tiene en esa sucursal (su **poder real**).

    OJO: aquí **no** se aplica el techo: esto es sólo lo que dice la
    membresía. El techo (el rol global) se aplica en
    ``effective_parking_role``.

    Si no hay membresía, la sucursal le queda vedada: **403**.
    """
    from app.models.user import ParkingMembership

    membership = (
        db.query(ParkingMembership)
        .filter(
            ParkingMembership.user_id == user.id,
            ParkingMembership.parking_id == parking_id,
        )
        .one_or_none()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene acceso a esta sucursal",
        )
    return _valor_rol(membership.role_in_parking)


def effective_parking_role(user: User, parking_id: int, db: Session) -> str:
    """El rol **efectivo** del usuario en la sucursal ``parking_id`` (ADR 0005).

    El rol global es el **techo** y el rol de la sucursal es el **poder
    real**:

    - ``admin`` global → ``admin`` (poder global, sin membresía: regla 1);
    - sin membresía → **403** (a esa sucursal no tiene acceso);
    - con membresía → el **más restrictivo** entre el rol global y
      ``role_in_parking`` (regla 2), por la jerarquía
      ``admin > gestor > operador > cliente``.

    OJO: ``role_in_parking`` **nunca** da más poder que el rol global
    (regla 4): por eso el corte es por el más restrictivo y no por el de la
    sucursal. Un ``cliente`` global con ``role_in_parking='gestor'`` sigue
    siendo cliente (T-114) y un ``gestor`` global con
    ``role_in_parking='operador'`` es **operador** en esa sucursal.
    """
    rol_global = _valor_rol(user.role)
    if rol_global == UserRole.ADMIN.value:
        return UserRole.ADMIN.value

    rol_sucursal = _rol_de_la_sucursal(user, parking_id, db)
    return _rol_mas_restrictivo(rol_global, rol_sucursal)


def enforce_parking_membership(
    user: User, parking_id: int, db: Session
) -> User:
    """Valida que ``user`` (no admin) tenga membresía en ``parking_id``.

    Lógica pura reutilizable tanto por ``parking_context`` (auth header)
    como por deps locales que necesiten aceptar también ``?token=``
    (Sprint Live-Preview 2026-07-07: el ``<img>`` del CalibrateView).

    Push security review (2026-07-07): se extrajo aquí para que
    ``parking_context`` pudiera volver a depender de ``get_current_user``
    (header-only) sin perder la opción de query-token en el endpoint live.

    T-114 (2026-10-23): **el rol global manda**. Antes esta función sólo
    miraba si existía una fila en ``parking_memberships``::

        - [cliente] POST /parkings/11/spaces   -> [201] (creo una plaza)
        - [cliente] POST /parkings/11/cameras  -> [201] (creo una camara)
        - [cliente] POST /parkings/11/tariffs  -> [201] (FIJO EL PRECIO)

    Es decir: un conductor con una fila de membresia (que el admin puede
    crear desde ``POST /users/{id}/memberships``) se convertia en gestor
    de la sucursal: fijaba las tarifas (fraude de ingresos), daba de alta
    camaras y plazas, y subia placas. Ahora un rol que no es de personal
    recibe 403 aunque tenga la membresia.

    OJO: ``role_in_parking`` (la columna que dice "de que rol es en ESTA
    sucursal") **sí se usa para autorizar** desde el T-178 (2026-10-24,
    ADR 0005): es el **poder real**, con el rol global como **techo**. El
    rol efectivo de la sucursal es el **más restrictivo** de los dos (ver
    ``effective_parking_role``): un ``gestor`` global que es
    ``operador`` en esa sucursal opera como operador **allí**, y un
    ``cliente`` global sigue siendo cliente aunque su membresía diga
    ``gestor`` (T-114).
    """
    # El rol se persiste como String(16); tras recargar el ORM puede venir
    # como enum o como str (depende del flush). Aceptamos ambos casos.
    role_value = _valor_rol(user.role)
    if role_value == UserRole.ADMIN.value:
        return user

    # T-114: la membresia no convierte a un cliente en gestor.
    if role_value not in ROLES_STAFF:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene acceso a esta sucursal",
        )

    # T-178 (ADR 0005), regla 3: si el rol **de la sucursal** no es de
    # personal, la sucursal queda vedada (aunque tenga la membresía). El
    # techo (el rol global manda) se aplica al decidir el nivel, en
    # ``effective_parking_role``.
    rol_sucursal = _rol_de_la_sucursal(user, parking_id, db)
    if rol_sucursal not in ROLES_STAFF:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene acceso a esta sucursal",
        )
    return user


def enforce_parking_role(
    user: User,
    parking_id: int,
    db: Session,
    *roles: str,
    detail: str = "No tiene permisos para esta operación",
) -> User:
    """Comprueba el rol **efectivo de esa sucursal** (ADR 0005).

    Es el hermano de ``enforce_parking_membership`` para los endpoints que
    exigen un rol concreto («sólo gestor»): en vez de mirar el rol global
    (que es sólo el **techo**), mira el poder **real** del usuario en esa
    sucursal.

    Por qué dos funciones y no una con un ``roles=`` opcional: en estos
    endpoints el ``parking_id`` llega en el **cuerpo** de la petición o se
    deduce del recurso que se carga, así que no puede ser un parámetro de
    *path* de la dependencia. Para el ``parking_id`` del **path** está
    ``require_parking_role``, que sí es una dependencia de FastAPI.
    """
    permitido = set(roles)
    efectivo = effective_parking_role(user, parking_id, db)
    if efectivo not in permitido:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )
    return user


def require_parking_role(*roles: str) -> Callable[..., Any]:
    """Dependencia: exige un rol **en la sucursal del path** (ADR 0005).

    Es el patrón para los endpoints cuya ruta ya lleva la sucursal
    (``/parkings/{parking_id}/...``): el ``parking_id`` se resuelve del
    *path* y el rol que se mira es el **efectivo en esa sucursal**, no el
    global.

    Ejemplo::

        @router.post(
            "/parkings/{parking_id}/algo",
            dependencies=[Depends(require_parking_role(
                UserRole.ADMIN.value, UserRole.GESTOR.value))],
        )

    OJO: sólo sirve en rutas con ``{parking_id}`` en el *path*; para el
    ``parking_id`` del cuerpo está ``enforce_parking_role``.
    """
    permitido = set(roles)

    def _checker(
        parking_id: int = Path(...),
        current: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        return enforce_parking_role(current, parking_id, db, *permitido)

    return _checker


def parking_context(
    parking_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Valida que el usuario (no admin) tenga membresía en la sucursal.

    Scope deliberadamente limitado a ``Authorization: Bearer``: este dep
    lo usan routers REST tradicionales (CRUD de cámaras, geocercas,
    tickets, etc.) y mantenerlo header-only evita exponer el flujo
    ``?token=...`` a endpoints donde no aporta nada. Endpoints que
    sí necesitan query token (p.ej. ``/cameras/{id}/live`` consumido
    desde ``<img>``) deben definir su propio dep local basado en
    ``get_current_user_or_query_token`` y ``enforce_parking_membership``.
    """
    return enforce_parking_membership(current, parking_id, db)


def require_any_role(roles: Iterable[str]) -> str:
    """Helper de tipo: expone un iterable para fastapi.Depends."""
    return ",".join(roles)
