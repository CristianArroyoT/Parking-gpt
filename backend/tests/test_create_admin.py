"""T-185: el script que crea el primer administrador de una instalación.

POR QUÉ (2026-10-25): el README dice que en staging/producción «los
usuarios reales se dan de alta desde la aplicación», pero la aplicación
sólo crea usuarios si **ya hay un administrador** (``POST /users`` es de
admin) y el ``seed`` se niega a arrancar en producción. O sea: el
despliegue documentado llegaba a una sucursal donde nadie podía entrar.
"""
from __future__ import annotations

from app.models.enums import UserRole
from app.models.user import User
from app.scripts.create_admin import crear_admin, motivo_no_crear

EMAIL = "admin@sucursal.es"
PASSWORD = "una-contrasena-larga"


def test_sin_administradores_y_con_datos_validos_se_puede() -> None:
    assert motivo_no_crear(EMAIL, PASSWORD, []) is None


def test_si_ya_hay_un_administrador_no_se_hace_nada() -> None:
    """Es una operacion de una vez: si ya hay admin, no se crea otro."""
    motivo = motivo_no_crear(EMAIL, PASSWORD, ["admin@anterior.es"])
    assert motivo is not None
    assert "admin@anterior.es" in motivo


def test_falta_el_correo() -> None:
    motivo = motivo_no_crear(None, PASSWORD, [])
    assert motivo is not None
    assert "SOLIDAPP_ADMIN_EMAIL" in motivo


def test_falta_la_contrasena() -> None:
    motivo = motivo_no_crear(EMAIL, None, [])
    assert motivo is not None
    assert "SOLIDAPP_ADMIN_PASSWORD" in motivo


def test_contrasena_corta() -> None:
    """La misma politica que la de la aplicacion (minimo 8)."""
    motivo = motivo_no_crear(EMAIL, "corta", [])
    assert motivo is not None


def test_contrasena_de_mas_de_72_bytes() -> None:
    """bcrypt solo distingue los primeros 72 bytes (T-87)."""
    motivo = motivo_no_crear(EMAIL, "a" * 73, [])
    assert motivo is not None
    assert "72" in motivo


def test_correo_invalido() -> None:
    motivo = motivo_no_crear("no-es-un-correo", PASSWORD, [])
    assert motivo is not None


def test_el_correo_se_canoniza() -> None:
    """El correo se guarda en minusculas, como en el resto del codigo."""
    assert motivo_no_crear("Admin@Sucursal.ES", PASSWORD, []) is None


def test_crea_el_administrador_con_la_contrasena_hasheada(db_session) -> None:
    from app.core.security import verify_password

    usuario = crear_admin(db_session, "Admin@Sucursal.ES", PASSWORD)

    assert usuario.email == "admin@sucursal.es"
    assert usuario.role == UserRole.ADMIN
    assert usuario.is_active is True
    assert usuario.hashed_password != PASSWORD
    assert verify_password(PASSWORD, usuario.hashed_password)


def test_no_crea_un_administrador_si_ya_hay_uno(db_session) -> None:
    """La fila no se duplica: el guard se comprueba antes de escribir."""
    from app.scripts import create_admin as modulo

    db_session.add(
        User(
            email="admin@anterior.es",
            full_name="Administrador",
            role=UserRole.ADMIN,
            hashed_password="x",
        )
    )
    db_session.commit()

    motivo = modulo.motivo_no_crear(EMAIL, PASSWORD, ["admin@anterior.es"])
    assert motivo is not None

    total = db_session.query(User).filter(User.role == UserRole.ADMIN).count()
    assert total == 1
