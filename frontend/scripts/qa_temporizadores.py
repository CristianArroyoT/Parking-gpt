"""QA del T-162 (2026-10-24): el polling no puede sobrevivir al desmontaje.

OJO: **esto NO es una puerta** (no esta en `verificar_repo.py`), y el
motivo esta escrito aqui para que nadie lo tome por una: en el entorno de
QA el clic al menu **no sale de la vista** (la URL sigue en `/mapa`), y
por tanto la comprobacion se apoya en que el temporizador **no** se
repita a los 30 s, no en que el componente se haya desmontado de verdad.
Es decir: **detecta el sintoma, no causa el defecto**.

La puerta de verdad para esto seria una prueba de componente (montar la
vista, resolver el `await` **despues** de desmontarla, y comprobar que
no queda ningun temporizador). Requiere un entorno de pruebas de
componentes, que el repo todavia no tiene.

QUE COMPRUEBA
-------------
En ``MapView`` (y en ``LiveView`` y ``CalibrateView``) el polling se
crea **despues** de varios ``await`` dentro de ``onMounted``. Si el
gestor sale de la vista **mientras carga**, ``onBeforeUnmount`` ve el
handle en ``null`` (todavia no existe) y el intervalo se crea **despues
del desmontaje**: nunca se borra y sigue pidiendo datos a una vista que ya
no esta.

COMO SE REPRODUCE (que es lo dificil)
--------------------------------------
Retrasar la API **interceptandola** no vale: al navegar, Playwright
cancela las peticiones interceptadas pendientes, el ``await`` de
``onMounted`` se **rechaza** y el codigo posterior no se ejecuta (que es
justamente el caso que no falla).

Lo que reproduce el defecto de verdad es la **red lenta de verdad**
(CDP, ``Network.emulateNetworkConditions``): el ``fetch`` sale de verdad
y, como las peticiones de ``fetch`` **no** se abortan al navegar (a
diferencia de una navegacion de documento), su promesa se resuelve
**despues** del desmontaje. Eso es la ventana del defecto.

Con el defecto: el intervalo huerfano dispara a los 30 s => peticiones.
Con el arreglo: no se crea ninguna.

Uso:
    python frontend/scripts/qa_temporizadores.py
"""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
CUENTA = ("gestor.madrid@solidapp.es", "gestor1234")

#: Latencia que se mete a la red (ms): la carga de la vista se queda
#: pendiente mientras el operador sale de ella.
LATENCIA_MS = 3000

#: Cuanto se espera despues de salir (el polling es de 30 s).
ESPERA_S = 40.0


def main() -> int:
    peticiones: list[tuple[float, str]] = []
    marca_salida: float | None = None

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        pagina.on(
            "request",
            lambda r: peticiones.append((time.monotonic(), r.url)),
        )

        pagina.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        pagina.fill("input[type=email]", CUENTA[0])
        pagina.fill("input[type=password]", CUENTA[1])
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        print("  login OK")

        # Red lenta de verdad (sin interceptar: el `fetch` no se aborta al
        # navegar, que es lo que pasa en un navegador de verdad).
        cdp = pagina.context.new_cdp_session(pagina)
        cdp.send("Network.enable")
        cdp.send(
            "Network.emulateNetworkConditions",
            {
                "offline": False,
                "latency": LATENCIA_MS,
                "downloadThroughput": 2 * 1024 * 1024,
                "uploadThroughput": 1024 * 1024,
            },
        )
        print(f"  red con {LATENCIA_MS} ms de latencia")

        # Se entra en la vista: su carga se queda pendiente.
        pagina.goto(f"{BASE}/mapa", wait_until="domcontentloaded", timeout=30000)
        pagina.wait_for_timeout(1200)
        print("  dentro de /mapa (la carga sigue pendiente)")

        # Se sale de la vista **mientras** su carga esta pendiente.
        #
        # OJO: se navega **dentro del SPA** (un clic en el menu), no con
        # `goto`: un `goto` es una navegacion de DOCUMENTO, que aborta el
        # `fetch` en vuelo (y entonces el `await` de `onMounted` se
        # rechaza y el codigo posterior no se ejecuta, que es justamente
        # el caso que **no** falla). En el SPA el `fetch` sigue vivo
        # (las peticiones de `fetch` no se abortan al cambiar de ruta),
        # que es la ventana real del defecto.
        # OJO: `force=True` porque con la red lenta la pantalla de carga
        # cubre el menu y el clic no llegaria al enlace.
        pagina.get_by_role("link", name="Cámaras").first.click(timeout=15000, force=True)
        pagina.wait_for_timeout(1500)
        marca_salida = time.monotonic()
        print(f"  fuera de /mapa (URL: {pagina.url})")

        # Se espera a que el intervalo huerfano tendria que disparar.
        pagina.wait_for_timeout(int(ESPERA_S * 1000))
        cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 0,
            "downloadThroughput": -1, "uploadThroughput": -1,
        })
        navegador.close()

    # OJO: no basta con contar las peticiones de la vista abandonada: el
    # dashboard del gestor tambien pide /spaces y /tickets al cargar. Lo
    # que delata al intervalo huerfano es que llega **TARDE**: el
    # dashboard pide al entrar, el huerfano pide cada 30 s. Asi que se
    # cuentan solo las peticiones que llegan **mas de 20 s** despues de
    # salir (el huerfano dispara a los ~30 s).
    limite = (marca_salida or 0) + 20
    tardias = [url for ts, url in peticiones if ts > limite]
    print(f"\n  peticiones mas de 20 s despues de salir: {len(tardias)}")
    for url in tardias[:10]:
        print(f"    - {url}")

    huerfanas = [u for u in tardias if "/spaces" in u or "/alerts" in u or "/tickets" in u]
    print(f"  peticiones de la vista abandonada: {len(huerfanas)}")

    if huerfanas:
        print(
            "*** FALLO: el polling sigue vivo despues de salir de la vista "
            "(T-162)"
        )
        return 1
    print("  OK: al salir de la vista, el polling se para (T-162)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
