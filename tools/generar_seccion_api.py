"""Genera la sección 3 de ``docs/API-INTERNAL.md`` a partir del código.

Sustituye a mano lo que se escribió en su día: el inventario sale de
los routers, no de la memoria. La columna "Quién" sale de las
dependencias que declara cada endpoint.

Uso:
    python tools/generar_seccion_api.py            # imprime la sección
    python tools/generar_seccion_api.py --escribir # la deja en el doc
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from extraer_api import extraer_de_modulo  # noqa: E402

V1 = RAIZ / "backend" / "app" / "api" / "v1"
DOC = RAIZ / "docs" / "API-INTERNAL.md"

#: Modulo -> (titulo legible, fichero del router)
TITULOS = {
    "admin": ("Administración — auditoría", "admin.py"),
    "alerts": ("Alertas", "alerts.py"),
    "auth": ("Autenticación", "auth.py"),
    "cameras": ("Cámaras, geocercas y salud", "cameras.py"),
    "cameras_live": ("Preview en vivo (MJPEG)", "cameras_live.py"),
    "cliente": ("Cliente final (PWA)", "cliente.py"),
    "costs": ("Costes operativos", "costs.py"),
    "dashboard": ("KPIs de dirección", "dashboard.py"),
    "events": ("Eventos (SSE)", "events.py"),
    "face_templates": ("Plantillas faciales (fuera del MVP)", "face_templates.py"),
    "gestor_operadores": ("Operadores de la sucursal", "gestor_operadores.py"),
    "incidents": ("Incidentes y adjuntos", "incidents.py"),
    "logout_all": ("Cierre de sesión global", "logout_all.py"),
    "parkings": ("Sucursales", "parkings.py"),
    "password_reset": ("Recuperación de contraseña", "password_reset.py"),
    "plans": ("Planes y suscripciones", "plans.py"),
    "plates": ("Placas (OCR)", "plates.py"),
    "reports": ("Informes", "reports.py"),
    "spaces": ("Plazas", "spaces.py"),
    "tariffs": ("Tarifas", "tariffs.py"),
    "ticket_summary": ("Resumen de tickets", "ticket_summary.py"),
    "tickets": ("Tickets", "tickets.py"),
    "users": ("Usuarios y membresías", "users.py"),
    "vehicles": ("Vehículos", "vehicles.py"),
}

#: Todos los routers son grupos propios del inventario: los que cuelgan
#: de otro (costs va dentro de admin, reports dentro de admin...) siguen
#: siendo endpoints de la API y tienen que aparecer.
SUBNO_MODULOS: set[str] = set()


def _rutas_por_modulo() -> dict[str, list[tuple[str, str, str]]]:
    por_modulo: dict[str, list[tuple[str, str, str]]] = {}
    for fichero in sorted(V1.glob("*.py")):
        if fichero.stem == "__init__":
            continue
        filas = extraer_de_modulo(fichero)
        if filas:
            por_modulo[fichero.stem] = [(m, r, q) for m, r, q, _ in filas]
    return por_modulo


def seccion() -> str:
    por_modulo = _rutas_por_modulo()
    lineas: list[str] = []
    total = sum(len(v) for v in por_modulo.values()) + 1  # + /health
    grupos = len([m for m in por_modulo if m not in SUBNO_MODULOS])
    lineas.append("## 3. Mapa de recursos y RBAC")
    lineas.append("")
    lineas.append(
        f"{total} endpoints en {grupos + 1} grupos. La columna «Quién» tiene "
        "dos partes, las dos leídas del código con `tools/extraer_api.py`:"
    )
    lineas.append("")
    lineas.append(
        "1. **El RBAC de dependencia**: quién puede llamar al endpoint "
        "(`parking_context`, `require_role(...)`, el token por `?token=`, "
        "el middleware de auditoría…)."
    )
    lineas.append(
        "2. **El ámbito de datos** que el endpoint aplica *en el cuerpo* "
        "(`ámbito: membresías de sucursal`, `ámbito: sus vehículos`): "
        "varios endpoints filtran por rol y por membresía a mano, para no "
        "duplicar el JOIN con `parking_context`."
    )
    lineas.append("")
    lineas.append(
        "El `admin` salta el filtro de membresías salvo que la propia "
        "dependencia lo restrinja (`require_role('admin')`)."
    )
    lineas.append("")
    numero = 0
    for modulo, (titulo, fichero) in TITULOS.items():
        if modulo in SUBNO_MODULOS or modulo not in por_modulo:
            continue
        numero += 1
        lineas.append(f"### 3.{numero} {titulo} — `{modulo}` (`{fichero}`)")
        lineas.append("")
        lineas.append("| Método | Ruta | Quién |")
        lineas.append("|---|---|---|")
        for metodo, ruta, quien in por_modulo[modulo]:
            ruta_doc = ruta.replace("/api/v1", "")
            lineas.append(f"| {metodo} | `{ruta_doc}` | {quien} |")
        lineas.append("")

    # El endpoint de salud no vive en un router de la API: lo define
    # ``create_app`` en ``app/main.py`` y va fuera del prefijo.
    numero += 1
    lineas.append(f"### 3.{numero} Salud — `meta` (`main.py`)")
    lineas.append("")
    lineas.append("| Método | Ruta | Quién |")
    lineas.append("|---|---|---|")
    lineas.append("| GET | `/health` | Público |")
    lineas.append("| GET | `/health/ready` | Público |")
    lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--escribir", action="store_true",
                    help="Sustituye la sección 3 del documento")
    args = ap.parse_args()

    texto = seccion()
    if not args.escribir:
        print(texto)
        return 0

    contenido = DOC.read_text(encoding="utf-8")
    inicio = contenido.index("## 3. Mapa de recursos y RBAC")
    fin = contenido.index("## 4. Versionado y política de deprecación")
    nuevo = contenido[:inicio] + texto + "\n" + contenido[fin:]
    DOC.write_text(nuevo, encoding="utf-8")
    print(f"Seccion 3 actualizada en {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
