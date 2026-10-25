"""Crea el **primer** administrador de una instalación (una sola vez, al desplegar).

POR QUÉ (T-185, 2026-10-25)
-----------------------------
El README dice que en ``staging``/``production`` «los usuarios reales se
dan de alta desde la aplicación». Pero la aplicación **sólo** crea
usuarios si **ya hay un administrador** (``POST /users`` es de admin):
sin él no hay forma de entrar en una sucursal recién desplegada. Y el
``seed`` se niega a arrancar en producción, porque crea usuarios DEMO con
contraseñas **públicas** (escritas en este repositorio público).

O sea: el despliegue documentado llegaba a una sucursal donde **nadie
podía entrar**. Este script es la pieza que faltaba:

- crea **un** administrador, con el correo y la contraseña que el
  operador elija (ninguna pública);
- se niega a hacer nada si **ya hay** un administrador (es una operación
  de una vez, y no deja una puerta trasera abierta);
- los datos se validan con el **mismo esquema de la aplicación**
  (``UserCreate``): la política de contraseñas es la de siempre, no una
  copia que se pueda quedar vieja.

Uso (en la sucursal, con el stack de producción levantado)::

    export SOLIDAPP_ADMIN_EMAIL="admin@sucursal.es"
    export SOLIDAPP_ADMIN_PASSWORD="una contrasena larga, de la sucursal"
    docker compose -f docker-compose.yml -f docker-compose.prod.yml \\
        exec -e SOLIDAPP_ADMIN_EMAIL -e SOLIDAPP_ADMIN_PASSWORD backend \\
        python -m app.scripts.create_admin

Ojo: las variables van en el **entorno**, no en la linea de comandos: una
contraseña en los argumentos queda en el historial del shell y se ve en
``ps``.
"""
from __future__ import annotations

import argparse
import os
import sys

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.emails import normalizar_email
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserCreate

#: Variables de entorno con las que se pasa el administrador a crear.
ENV_EMAIL = "SOLIDAPP_ADMIN_EMAIL"
ENV_PASSWORD = "SOLIDAPP_ADMIN_PASSWORD"

#: Nombre por defecto del administrador (lo puede cambiar la aplicacion).
NOMBRE_POR_DEFECTO = "Administrador"


def motivo_no_crear(
    email: str | None,
    password: str | None,
    admins_existentes: list[str],
) -> str | None:
    """Por qué no se puede crear el administrador (``None`` = sí se puede).

    Función ** pura** (se puede probar sin tocar la base de datos): una
    puerta que no se puede ver fallar no es una puerta.
    """
    if admins_existentes:
        return (
            "ya hay un administrador en esta instalacion "
            f"({', '.join(admins_existentes)}): este script es de una vez, "
            "para el alta inicial. Los demas administradores se crean "
            "desde la aplicacion."
        )
    if not email:
        return (
            f"falta el correo del administrador (variable de entorno {ENV_EMAIL})"
        )
    if not password:
        return (
            "falta la contrasena del administrador "
            f"(variable de entorno {ENV_PASSWORD})"
        )
    # La validacion es la de la aplicacion (correo canonico, minimo de
    # contrasena y el limite real de bcrypt), no una copia.
    try:
        UserCreate(
            email=email,
            full_name=NOMBRE_POR_DEFECTO,
            password=password,
            role=UserRole.ADMIN.value,
        )
    except ValidationError as error:
        detalles = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in error.errors()
        )
        return f"los datos del administrador no son validos: {detalles}"
    return None


def crear_admin(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
) -> User:
    """Crea el administrador (la fila) y lo devuelve."""
    correo = normalizar_email(email)
    usuario = User(
        email=correo,
        full_name=full_name or NOMBRE_POR_DEFECTO,
        role=UserRole.ADMIN,
        is_active=True,
        hashed_password=hash_password(password),
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def run(email: str | None, password: str | None) -> int:
    """Crea el administrador si se puede. Devuelve el código de salida."""
    with SessionLocal() as db:
        admins = [
            u.email
            for u in db.query(User).filter(User.role == UserRole.ADMIN).all()
        ]
        motivo = motivo_no_crear(email, password, admins)
        if motivo:
            print(f"[create_admin] ERROR: {motivo}")
            return 1
        assert email is not None and password is not None
        usuario = crear_admin(db, email, password)
        print(
            f"[create_admin] administrador creado: {usuario.email} "
            f"(id {usuario.id}). Ya puedes entrar con el."
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email",
        default=os.environ.get(ENV_EMAIL),
        help=f"Correo del administrador (o la variable de entorno {ENV_EMAIL}).",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get(ENV_PASSWORD),
        help=(
            f"Contrasena del administrador (o la variable de entorno "
            f"{ENV_PASSWORD}). OJO: en la linea de comandos queda en el "
            "historial del shell."
        ),
    )
    args = parser.parse_args(argv)
    return run(args.email, args.password)


if __name__ == "__main__":
    sys.exit(main())
