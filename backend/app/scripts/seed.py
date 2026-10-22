"""Seed inicial: admin, 5 sucursales demo, 60 plazas por sucursal, planes demo.

Uso: docker compose exec backend python -m app.scripts.seed

OJO (T-83, 2026-10-22): este seed crea usuarios **demo con contrasenas
publicas** (``admin@solidapp.es`` / ``admin12345``), escritas en el README
y en este repositorio publico. En ``staging``/``production`` el seed **se
niega a arrancar**: quien quiera sembrar datos de prueba alla tiene que
decirlo explicitamente con ``--allow-demo-users``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.parking import Camera, Parking, ParkingSpace
from app.models.pricing import Plan, Tariff
from app.models.user import ParkingMembership, User

DEMO_PARKINGS = [
    ("MAD-A", "Madrid Centro A", "Calle Gran Vía 100", "Madrid"),
    ("MAD-B", "Madrid Centro B", "Calle Alcalá 50", "Madrid"),
    ("BCN-1", "Barcelona Eixample", "Av. Diagonal 200", "Barcelona"),
    ("VAL-1", "Valencia Centro", "Calle Colón 30", "Valencia"),
    ("SEV-1", "Sevilla Nervión", "Av. Luis de Morales 5", "Sevilla"),
]

# Tarifa estándar para todas las sucursales demo.
DEFAULT_TARIFF = {
    "name": "Estándar 2025",
    "price_per_hour": 2.5,
    "price_per_fraction": 0.70,
    "fraction_minutes": 15,
    "max_daily": 25.0,
    "valid_from": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
}

DEMO_USERS = [
    ("admin@solidapp.es", "Administrador", None, "admin12345", UserRole.ADMIN, None),
    ("gestor.madrid@solidapp.es", "Gestora Madrid", "+34 600 100 100", "gestor1234", UserRole.GESTOR, "MAD-A"),
    ("operador.madrid@solidapp.es", "Operador Madrid", "+34 600 100 101", "oper12345", UserRole.OPERADOR, "MAD-A"),
    ("cliente.demo@solidapp.es", "Cliente Demo", "+34 600 200 200", "cliente1234", UserRole.CLIENTE, None),
]

DEMO_PLANS = [
    ("basico", "Básico", 30.0, 5.0, 0),
    ("familiar", "Familiar", 60.0, 10.0, 2),
    ("empresa", "Empresa", 200.0, 20.0, 10),
]

LANES = ["A", "B", "C", "D"]
SPACES_PER_LANE = 15


def _seed_parking(db: Session, code: str, name: str, address: str, city: str) -> Parking:
    parking = db.query(Parking).filter(Parking.code == code).one_or_none()
    created = False
    if parking is None:
        parking = Parking(code=code, name=name, address=address, city=city)
        db.add(parking)
        db.flush()
        created = True
    if created:
        for lane in LANES:
            for n in range(1, SPACES_PER_LANE + 1):
                db.add(
                    ParkingSpace(
                        parking_id=parking.id,
                        lane=lane,
                        number=f"{lane}-{n:02d}",
                    )
                )
        for i in range(1, 11):
            db.add(
                Camera(
                    parking_id=parking.id,
                    code=f"CAM-{i:02d}",
                    name=f"Cámara {LANES[(i - 1) % len(LANES)]}-{i:02d}",
                    rtsp_url=f"rtsp://demo.invalid/{code.lower()}/{i:02d}",
                    lane_hint=LANES[(i - 1) % len(LANES)],
                    fps=10,
                )
            )
    # Tarifa por defecto de la sucursal (idempotente, se crea aunque el parking ya existiese).
    if not (
        db.query(Tariff)
        .filter(Tariff.parking_id == parking.id, Tariff.name == DEFAULT_TARIFF["name"])
        .first()
    ):
        db.add(Tariff(parking_id=parking.id, **DEFAULT_TARIFF))
    return parking


def _seed_user(
    db: Session,
    email: str,
    full_name: str,
    phone: str | None,
    password: str,
    role: UserRole,
    parking_code: str | None,
) -> User:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user:
        return user
    user = User(
        email=email,
        full_name=full_name,
        phone=phone,
        role=role,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.flush()
    if parking_code is not None and role != UserRole.ADMIN:
        parking = db.query(Parking).filter(Parking.code == parking_code).one()
        db.add(
            ParkingMembership(
                user_id=user.id,
                parking_id=parking.id,
                role_in_parking=role,
            )
        )
    return user


def _seed_plans(db: Session) -> None:
    for code, name, price, discount, vehicles in DEMO_PLANS:
        if db.query(Plan).filter(Plan.code == code).one_or_none():
            continue
        db.add(
            Plan(
                code=code,
                name=name,
                monthly_price=price,
                discount_percent=discount,
                included_vehicles=vehicles,
                is_active=True,
            )
        )


def motivo_rechazo(environment: str, permitir_demo: bool) -> str | None:
    """Por que no se puede sembrar en este entorno (``None`` = se puede).

    Funcion **pura** (para poder probarla sin tocar la base de datos): una
    puerta que no se puede ver fallar no es una puerta.
    """
    if environment not in ("staging", "production"):
        return None
    if permitir_demo:
        return None
    return (
        f"El seed crea usuarios DEMO con contrasenas publicas "
        f"(admin@solidapp.es / admin12345), escritas en el README y en este "
        f"repositorio: con ENVIRONMENT={environment} eso seria un "
        f"administrador accesible. Si es lo que quieres, pasalo con "
        f"--allow-demo-users."
    )


def run(permitir_demo: bool = False) -> None:
    motivo = motivo_rechazo(get_settings().environment, permitir_demo)
    if motivo:
        raise SystemExit(f"[seed] ERROR: {motivo}")
    db = SessionLocal()
    try:
        for code, name, addr, city in DEMO_PARKINGS:
            _seed_parking(db, code, name, addr, city)
        for email, full_name, phone, password, role, parking_code in DEMO_USERS:
            _seed_user(db, email, full_name, phone, password, role, parking_code)
        _seed_plans(db)
        db.commit()
        now = datetime.now(timezone.utc)
        print(
            "Seed completado: "
            f"{len(DEMO_PARKINGS)} parkings × {len(LANES) * SPACES_PER_LANE} plazas, "
            f"{len(DEMO_USERS)} usuarios, {len(DEMO_PLANS)} planes, "
            f"{len(DEMO_PARKINGS)} tarifas. ({now.isoformat()})"
        )
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siembra los datos demo.")
    parser.add_argument(
        "--allow-demo-users",
        action="store_true",
        help=(
            "Permite sembrar los usuarios demo (con contrasenas publicas) "
            "tambien en staging/produccion."
        ),
    )
    args = parser.parse_args(argv)
    run(permitir_demo=args.allow_demo_users)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
