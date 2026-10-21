"""Comprobación previa a la carga (preflight).

Antes de lanzar un escenario de carga hay que comprobar que el entorno
responde: si el RTSP de prueba está caído o el login falla, el informe de
Locust aparecerá lleno de fallos y no distinguirá "el producto va lento"
de "el entorno estaba roto".

Uso::

    python backend/locust/preflight.py
    python backend/locust/preflight.py --base-url http://localhost:8000 \
        --parking-id 11 --camera-ids 81,136 --email gestor.madrid@solidapp.es

Códigos de salida: 0 = todo OK, 1 = hay comprobaciones fallidas.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

TIMEOUT_S = 20.0


def _peticion(
    metodo: str,
    url: str,
    *,
    datos: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = TIMEOUT_S,
) -> tuple[int, bytes]:
    """Llama a la API y devuelve (status, cuerpo). No lanza por status >= 400."""
    cuerpo = json.dumps(datos).encode() if datos is not None else None
    peticion = urllib.request.Request(url, data=cuerpo, method=metodo)
    if cuerpo is not None:
        peticion.add_header("Content-Type", "application/json")
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _leer_stream(
    url: str,
    ventana_s: float,
    timeout_s: float,
    token: str | None = None,
    max_lecturas: int | None = None,
) -> tuple[int, bytes, int]:
    """Abre un stream infinito, lee durante la ventana y lo cierra.

    Devuelve (status, bytes_leidos, frames_jpeg). Los bytes se leen a
    trozos con ``read1`` para poder respetar la ventana: el stream no
    termina nunca y hay que cerrar la conexión sí o sí.

    ``max_lecturas`` corta el bucle tras N lecturas: el SSE sólo interesa
    por su primer evento (el ``ping``) y, como luego está 30 s en silencio,
    seguir leyendo bloquearía hasta el timeout del socket.
    """
    peticion = urllib.request.Request(url, method="GET")
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(peticion, timeout=timeout_s)
    except urllib.error.HTTPError as exc:
        # Un 4xx/5xx en un stream: se devuelve el estado y el cuerpo para
        # que el preflight diga POR QUÉ falló (y no sólo "error").
        return exc.code, exc.read(), 0
    with resp:
        limite = time.monotonic() + ventana_s
        buffer = bytearray()
        lecturas = 0
        while time.monotonic() < limite:
            try:
                # ``http.client.HTTPResponse.read1`` devuelve lo que haya
                # disponible sin esperar a llenar el buffer (el stream no
                # termina nunca, así que ``read()`` bloquearía).
                trozo = resp.read1(65536)
            except http.client.IncompleteRead as exc:
                # El frame ha llegado a trozos: ``http.client`` lanza
                # IncompleteRead con lo que sí ha leído. Se guarda y se
                # sale (la conexión ya no es utilizable).
                buffer.extend(exc.partial)
                break
            except Exception:  # noqa: BLE001 — al cerrar puede saltar el timeout
                break
            if not trozo:
                break
            buffer.extend(trozo)
            lecturas += 1
            if max_lecturas is not None and lecturas >= max_lecturas:
                break
        # Los frames se cuentan por el boundary multipart (``--frame``):
        # es más robusto que buscar el marcador JPEG, porque el frame puede
        # llegar partido en varios trozos de red.
        frames = bytes(buffer).count(b"--frame")
        return resp.status, bytes(buffer), frames


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones y devuelve 0 (todo OK) o 1 (alguna falla)."""
    parser = argparse.ArgumentParser(description="Preflight del entorno de carga de solidAPP.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--parking-id", type=int, default=11)
    parser.add_argument("--camera-ids", default="81")
    parser.add_argument("--vehicle-id", type=int, default=1)
    parser.add_argument("--email", default="gestor.madrid@solidapp.es")
    parser.add_argument("--password", default="gestor1234")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    cameras = [int(x) for x in args.camera_ids.split(",") if x.strip()]
    fallos = 0

    def comprobar(ok: bool, texto: str) -> None:
        nonlocal fallos
        if not ok:
            fallos += 1
        print(f"[{'OK  ' if ok else 'FALLO'}] {texto}")

    # 1) Salud del backend
    try:
        status, cuerpo = _peticion("GET", f"{base}/health")
        comprobar(status == 200, f"GET /health -> {status} {cuerpo[:80].decode(errors='replace')}")
    except (urllib.error.URLError, OSError) as exc:
        comprobar(False, f"GET /health -> error de conexión: {exc}")
        print("Sin backend no se puede seguir con el preflight.")
        return 1

    # 2) Login
    token = ""
    try:
        status, cuerpo = _peticion(
            "POST",
            f"{base}/api/v1/auth/login",
            datos={"email": args.email, "password": args.password},
        )
        if status == 200:
            token = json.loads(cuerpo).get("access_token", "")
        comprobar(status == 200 and bool(token), f"POST /api/v1/auth/login ({args.email}) -> {status}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        comprobar(False, f"POST /api/v1/auth/login -> error: {exc}")

    if not token:
        print("Sin token no se puede seguir con el preflight.")
        return 1

    # 3) La sucursal existe
    try:
        status, cuerpo = _peticion("GET", f"{base}/api/v1/parkings/{args.parking_id}", token=token)
        comprobar(status == 200, f"GET /api/v1/parkings/{args.parking_id} -> {status}")
    except (urllib.error.URLError, OSError) as exc:
        comprobar(False, f"GET /api/v1/parkings/{args.parking_id} -> error: {exc}")

    # 4) Alta y cierre de ticket
    entrada = datetime.now(timezone.utc) - timedelta(hours=1)
    ticket_id = 0
    try:
        status, cuerpo = _peticion(
            "POST",
            f"{base}/api/v1/tickets",
            datos={
                "parking_id": args.parking_id,
                "vehicle_id": args.vehicle_id,
                "entry_at": entrada.isoformat(),
            },
            token=token,
        )
        if status == 201:
            ticket_id = int(json.loads(cuerpo).get("id") or 0)
        comprobar(status == 201 and ticket_id > 0, f"POST /api/v1/tickets -> {status}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        comprobar(False, f"POST /api/v1/tickets -> error: {exc}")

    if ticket_id:
        try:
            status, _ = _peticion(
                "POST",
                f"{base}/api/v1/tickets/{ticket_id}/close",
                datos={"payment_method": "card"},
                token=token,
            )
            comprobar(status == 200, f"POST /api/v1/tickets/{ticket_id}/close -> {status}")
        except (urllib.error.URLError, OSError) as exc:
            comprobar(False, f"POST /api/v1/tickets/{ticket_id}/close -> error: {exc}")

    # 5) SSE del mapa en vivo (stream infinito: se lee una ventana y se cierra)
    #
    # OJO: el SSE sólo acepta el token por cabecera ``Authorization``. Su
    # dep de contexto de sucursal (``parking_context``) es header-only, así
    # que el ``?token=`` que anuncia el docstring del endpoint NO vale
    # (a diferencia del preview MJPEG, que sí lo acepta).
    try:
        status, leidos, _ = _leer_stream(
            f"{base}/api/v1/parkings/{args.parking_id}/events",
            ventana_s=2.0,
            timeout_s=10.0,
            token=token,
            max_lecturas=1,
        )
        detalle = "" if status == 200 else f" {leidos[:120].decode(errors='replace')}"
        comprobar(
            status == 200 and len(leidos) > 0,
            f"GET /api/v1/parkings/{args.parking_id}/events -> {status}, "
            f"{len(leidos)} bytes en 2 s{detalle}",
        )
    except (urllib.error.URLError, OSError) as exc:
        comprobar(False, f"GET .../events -> error: {exc}")

    # 6) Preview MJPEG de cada cámara configurada
    #
    # La ventana tiene que ser mayor que el arranque del preview: abrir el
    # RTSP y codificar el primer JPEG tarda 1,7-4 s (medido), así que con
    # 3 s se leen bytes pero el frame todavía no está completo.
    for camera_id in cameras:
        url = f"{base}/api/v1/parkings/{args.parking_id}/cameras/{camera_id}/live?token={token}"
        try:
            status, leidos, frames = _leer_stream(url, ventana_s=8.0, timeout_s=15.0)
            detalle = "" if status == 200 else f" {leidos[:120].decode(errors='replace')}"
            comprobar(
                status == 200 and frames > 0,
                f"GET .../cameras/{camera_id}/live -> {status}, "
                f"{frames} frames ({len(leidos)} bytes) en 8 s{detalle}",
            )
        except (urllib.error.URLError, OSError) as exc:
            comprobar(False, f"GET .../cameras/{camera_id}/live -> error: {exc}")

    print()
    if fallos:
        print(f"PREFLIGHT FALLIDO: {fallos} comprobaciones fallidas.")
        return 1
    print("PREFLIGHT OK: el entorno responde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
