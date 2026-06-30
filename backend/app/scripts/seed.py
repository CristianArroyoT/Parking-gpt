"""Seed inicial: admin, 5 sucursales demo, 60 plazas por sucursal, planes demo.

Uso: docker compose exec backend python -m app.scripts.seed
"""

from __future__ import annotations

from datetime import datetime, timezone

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


def _seed_parking(db, code: str, name: str, address: str, city: str) -> Parking:
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
    db,
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


def _seed_plans(db) -> None:
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


def run() -> None:
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


if __name__ == "__main__":
    run()