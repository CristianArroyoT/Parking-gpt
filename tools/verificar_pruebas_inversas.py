"""Comprueba que los tests de los arreglos **siguen detectando** el defecto.

POR QUÉ ESTA PUERTA
-------------------
Un test que no puede demostrar que detecta lo que dice detectar no es un
test: es una línea de texto que dice "OK". Con los arreglos de esta tanda
(T-113, T-121, T-122, T-125, T-129...T-134) hay **diez** regresiones que
sólo se ven si alguien vuelve a poner el defecto.

Mientras la prueba inversa vivía en la carpeta temporal de quien la
escribió, nadie la ejecutaba: los tests podían dejar de detectar (por un
refactor, un cambio de mensaje o un test reescrito) y el repo se
quedaría en verde sin que nadie se enterase. Esta puerta las ejecuta
**todas**, cada vez, y falla si alguna deja de detectar.

CÓMO FUNCIONA
--------------
Para cada caso: se copia el fichero, se vuelve a poner el defecto, se
ejecuta el test y se comprueba que **falla** (y que falla por una
aserción, no por un error de código: un ``NameError`` en el defecto
probaría que el test se rompe, no que detecta). Después se restaura el
fichero.

    python tools/verificar_pruebas_inversas.py
    python tools/verificar_pruebas_inversas.py --autoprueba

OJO: los ``pytest`` se ejecutan **desde ``backend/``** (el rootdir de
la suite) y con el fichero modificado **en su sitio**, que es lo único
que hace que el módulo que se importa sea el defectuoso.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"


@dataclass
class Caso:
    nombre: str
    fichero: str
    cambios: list[tuple[str, str]] = field(default_factory=list)
    test: str = ""
    nota: str = ""


# ── los casos (el defecto y el test que lo debe detectar) ───────────────
CASOS: list[Caso] = [
    Caso(
        nombre="T-113 · el alta de tickets vuelve a aceptar cualquier sucursal",
        fichero="backend/app/api/v1/tickets.py",
        cambios=[
            (
                "    # T-113: la sucursal del body tiene que ser una sucursal del usuario.\n"
                "    parking_context(payload.parking_id, current=user, db=db)\n",
                "",
            ),
        ],
        test="tests/test_aislamiento_sucursal.py::test_alta_de_ticket_en_sucursal_ajena_da_403",
    ),
    Caso(
        nombre="T-114 · una membresia vuelve a convertir a un cliente en gestor",
        fichero="backend/app/core/deps.py",
        cambios=[
            (
                "    # T-114: la membresia no convierte a un cliente en gestor.\n"
                "    if role_value not in ROLES_STAFF:\n"
                "        raise HTTPException(\n"
                "            status_code=status.HTTP_403_FORBIDDEN,\n"
                '            detail="No tiene acceso a esta sucursal",\n'
                "        )\n\n",
                "",
            ),
        ],
        test=(
            "tests/test_aislamiento_sucursal.py::"
            "test_un_cliente_con_membresia_no_gestiona_la_sucursal"
        ),
    ),
    Caso(
        nombre="T-115 · las geocercas vuelven a cruzarse sin la sucursal",
        fichero="backend/app/api/v1/cameras.py",
        cambios=[
            (
                "    # T-115: la camara tiene que ser de la sucursal del path.\n"
                "    _camara_de_sucursal(db, camera_id, parking_id)\n"
                "    return (\n",
                "    return (\n",
            ),
        ],
        test=(
            "tests/test_aislamiento_sucursal.py::"
            "test_no_se_leen_las_geocercas_de_una_camara_de_otra_sucursal"
        ),
    ),
    Caso(
        nombre="T-120 · un cliente vuelve a poder cerrar su propio ticket",
        fichero="backend/app/api/v1/tickets.py",
        cambios=[
            (
                "    user: User = Depends(require_role(*ROLES_STAFF)),\n",
                "    user: User = Depends(get_current_user),\n",
            ),
        ],
        test="tests/test_ticket_cierre.py::test_un_cliente_no_puede_cerrar_su_propio_ticket",
    ),
    Caso(
        nombre="T-121 · el cierre manual vuelve a ser un commit a ciegas",
        fichero="backend/app/services/ticket_closing.py",
        cambios=[
            (
                """    actualizados = (
        db.query(Ticket)
        .filter(Ticket.id == ticket.id, Ticket.status == TicketStatus.ACTIVO)
        .update(campos, synchronize_session=False)
    )
    if not actualizados:
        # Otro cierre se ha adelantado: no se toca el ticket.
        db.rollback()
        raise TicketAlreadyClosedError(ticket.id)
    db.commit()
""",
                """    ticket.exit_at = exit_at
    ticket.amount = amount
    ticket.discount = discount
    ticket.total = total
    ticket.status = TicketStatus.CERRADO
    db.commit()
""",
            ),
        ],
        test=(
            "tests/test_ticket_cierre_carrera.py::"
            "test_dos_cierres_a_la_vez_solo_uno_puede_cobrar"
        ),
    ),
    Caso(
        nombre="T-125 · la purga vuelve a borrar los vehiculos con dueño",
        fichero="backend/app/services/vehicle_purge.py",
        cambios=[
            (
                "        .filter(~Vehicle.users.any())\n",
                "",
            ),
        ],
        test="tests/test_purga_vehiculos.py::test_no_borra_un_vehiculo_con_dueno",
    ),
    Caso(
        nombre="T-129 · el original vuelve a guardarse con sus metadatos",
        fichero="backend/app/services/incident_attachments.py",
        cambios=[
            (
                "    contenido_guardado = sanear_metadatos(contenido, mime)\n",
                "    contenido_guardado = contenido\n",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_el_original_servido_no_lleva_metadatos"
        ),
    ),
    Caso(
        nombre="T-131 · el total vuelve a calcularse con los valores sin redondear",
        fichero="backend/app/services/pricing.py",
        cambios=[
            (
                """    amount = round(_compute_amount(tariff, entry_at, exit_at), 2)
    discount = round(
        _compute_discount(db, vehicle_id=vehicle_id, at=exit_at, amount=amount), 2
    )
    total = round(amount - discount, 2)
    return TicketTotal(amount=amount, discount=discount, total=total)
""",
                """    amount = _compute_amount(tariff, entry_at, exit_at)
    discount = _compute_discount(db, vehicle_id=vehicle_id, at=exit_at, amount=amount)
    total = round(amount - discount, 2)
    return TicketTotal(amount=round(amount, 2), discount=round(discount, 2), total=total)
""",
            ),
        ],
        test=(
            "tests/test_pricing_redondeo.py::"
            "test_el_total_cuadra_con_el_importe_menos_el_descuento"
        ),
    ),
    Caso(
        nombre="T-132 · el cliente vuelve a poder invertir el filtro de planes",
        fichero="backend/app/api/v1/plans.py",
        cambios=[
            (
                """    elif not es_admin:
        # Para el resto de roles, el parametro solo puede endurecer el
        # filtro: nunca se ven los planes desactivados.
        only_active = True
""",
                "",
            ),
        ],
        test="tests/test_planes_api.py::test_el_cliente_no_puede_invertir_el_filtro",
    ),
    Caso(
        nombre="T-133 · la guarda de suscripciones vuelve a mirar solo el presente",
        fichero="backend/app/api/v1/plans.py",
        cambios=[
            (
                """    solapada = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.starts_at < ends_at,
            Subscription.ends_at > starts_at,
        )
        .first()
    )
""",
                """    solapada = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.is_active.is_(True),
            Subscription.starts_at <= ahora_utc(),
            Subscription.ends_at >= ahora_utc(),
        )
        .first()
    )
""",
            ),
        ],
        test=(
            "tests/test_planes_api.py::"
            "test_no_se_puede_crear_una_suscripcion_que_se_solape_con_otra"
        ),
    ),
    Caso(
        nombre="T-134 · la metadata de un adjunto caducado vuelve a servirse",
        fichero="backend/app/api/v1/incidents.py",
        cambios=[
            (
                """    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    _exigir_no_caducado(adjunto)
    return adjuntos.a_esquema(adjunto)
""",
                """    adjunto = _adjunto_de_sucursal(attachment_id, db, current_user)
    return adjuntos.a_esquema(adjunto)
""",
            ),
        ],
        test=(
            "tests/test_incident_attachments.py::"
            "test_la_metadata_de_un_adjunto_caducado_no_se_sirve"
        ),
    ),
]


def _aplicar(caso: Caso) -> bool:
    """Pone el defecto. Devuelve False si el bloque no aparece."""
    ruta = RAIZ / caso.fichero
    texto = ruta.read_text(encoding="utf-8")
    for viejo, nuevo in caso.cambios:
        if texto.count(viejo) != 1:
            print(f"      el bloque aparece {texto.count(viejo)} veces (se esperaba 1)")
            return False
        texto = texto.replace(viejo, nuevo)
    ruta.write_text(texto, encoding="utf-8", newline="")
    return True


def _ejecutar(test: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider", test],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _fallo_real(salida: str, test: str) -> bool:
    """El fallo es una asercion del test (no un error de codigo)."""
    nombre = test.split("::")[-1]
    if "FAILED" not in salida or nombre not in salida:
        return False
    return not (
        "NameError" in salida or "SyntaxError" in salida or "ImportError" in salida
    )


def verificar() -> int:
    fallos: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pruebas_inversas_") as temporal:
        for caso in CASOS:
            ruta = RAIZ / caso.fichero
            copia = Path(temporal) / ruta.name
            shutil.copy2(ruta, copia)
            try:
                if not _aplicar(caso):
                    print(f"  [FALLA] {caso.nombre}: no se pudo poner el defecto")
                    fallos.append(caso.nombre)
                    continue
                codigo, salida = _ejecutar(caso.test)
                if codigo == 0:
                    print(f"  [FALLA] {caso.nombre}: el test PASA con el defecto")
                    fallos.append(caso.nombre)
                elif not _fallo_real(salida, caso.test):
                    print(
                        f"  [FALLA] {caso.nombre}: el test falla, pero no por una "
                        f"aserción (eso no prueba que detecte)"
                    )
                    fallos.append(caso.nombre)
                else:
                    print(f"  [OK   ] {caso.nombre}")
            finally:
                shutil.copy2(copia, ruta)

    print()
    if fallos:
        print(f"{len(fallos)} prueba(s) inversa(s) que ya NO detectan su defecto:")
        for nombre in fallos:
            print(f"  - {nombre}")
        return 1
    print(f"Las {len(CASOS)} pruebas inversas siguen detectando su defecto.")
    return 0


def _autoprueba() -> int:
    """La puerta tiene que **detectar** un caso que no detecta nada.

    Se monta un caso de mentira: un "defecto" que **no** rompe el
    comportamiento (un comentario), con un test que sigue pasando. La
    puerta tiene que decir que ese caso no detecta.
    """
    with tempfile.TemporaryDirectory(prefix="autoprueba_") as temporal:
        raiz = Path(temporal)
        (raiz / "backend" / "app").mkdir(parents=True)
        (raiz / "backend" / "tests").mkdir(parents=True)
        # Un caso de mentira: se cambia un comentario y el test sigue
        # pasando -> la puerta tiene que avisar.
        caso = Caso(
            nombre="caso de mentira (un comentario no rompe nada)",
            fichero="backend/app/ejemplo.py",
            cambios=[("# original\n", "# cambiado\n")],
            test="tests/ejemplo.py::test_nada",
        )
        (raiz / "backend" / "app" / "ejemplo.py").write_text("# original\n", encoding="utf-8")
        (raiz / "backend" / "tests" / "ejemplo.py").write_text(
            "def test_nada():\n    assert True\n", encoding="utf-8"
        )
        codigo, salida = _ejecutar_en(raiz, caso.test)
        if codigo == 0:
            print("  OK: la puerta detecta el caso que no detecta nada")
        else:
            print(f"  FALLO: la puerta no vio el caso de mentira (codigo {codigo})")
            return 1
    return 0


def _ejecutar_en(raiz: Path, test: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider", test],
        cwd=raiz / "backend",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--autoprueba",
        action="store_true",
        help="comprueba que la puerta detecta un caso que no detecta nada",
    )
    args = parser.parse_args()

    if args.autoprueba:
        return _autoprueba()

    print(f"Comprobando {len(CASOS)} pruebas inversas (con el defecto puesto)...\n")
    return verificar()


if __name__ == "__main__":
    sys.exit(main())
