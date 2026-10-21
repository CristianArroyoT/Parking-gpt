#!/usr/bin/env python3
"""Benchmark del servicio OCR: latencia por frame y throughput (T-14).

Mide lo que de verdad importa para el dimensionado del MVP: **cuántos
fotogramas por segundo** aguanta el servicio con CPU y con GPU, y qué
latencia ve el backend en cada caso.

Uso:
    python benchmark.py --url http://localhost:8801 --iterations 30
    python benchmark.py --url http://localhost:8801 --concurrency 8

Notas:
- La primera llamada carga el modelo (lazy): se hace un *warmup* aparte
  que no cuenta en las estadísticas.
- El tiempo se mide **cliente** (ida + vuelta), que es lo que ve el
  backend. El servicio está en la misma red Docker en producción, así que
  la latencia de red es marginal.
- El informe se imprime en JSON para poder versionarlo en el repo.
"""
from __future__ import annotations

import argparse
import io
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def _imagen_matricula() -> bytes:
    """Genera una imagen sintética con una matrícula legible.

    No es una foto real de un coche, pero sirve para medir **coste de
    cómputo**: la detección + reconocimiento ejecuta las mismas redes
    sobre una imagen de tamaño equivalente.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1280, 720), (110, 112, 116))
    d = ImageDraw.Draw(img)
    # Fondo con algo de estructura (elipses) para que no sea un color plano.
    for i in range(6):
        x = 120 + i * 190
        d.ellipse((x, 380, x + 150, 530), fill=(70, 72, 78))
    # Matrícula
    d.rectangle((430, 300, 850, 400), fill=(245, 245, 242), outline=(30, 30, 30), width=4)
    d.text((470, 320), "1234 ABC", fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _una_peticion(url: str, imagen: bytes, timeout: float) -> tuple[float, int]:
    t0 = time.perf_counter()
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{url}/recognize", files={"image": ("frame.jpg", imagen, "image/jpeg")})
        r.raise_for_status()
        n = len(r.json())
    return time.perf_counter() - t0, n


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark del servicio OCR (T-14)")
    ap.add_argument("--url", default="http://localhost:8801", help="URL base del servicio OCR")
    ap.add_argument("--iterations", type=int, default=30, help="nº de peticiones secuenciales")
    ap.add_argument("--concurrency", type=int, default=1, help="peticiones simultáneas (1 = secuencial)")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--warmup", type=int, default=1)
    args = ap.parse_args()

    imagen = _imagen_matricula()

    for _ in range(args.warmup):
        _una_peticion(args.url, imagen, args.timeout)

    latencias: list[float] = []
    detecciones = 0
    t_inicio = time.perf_counter()

    if args.concurrency <= 1:
        for _ in range(args.iterations):
            lat, n = _una_peticion(args.url, imagen, args.timeout)
            latencias.append(lat)
            detecciones += n
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for lat, n in pool.map(
                lambda _: _una_peticion(args.url, imagen, args.timeout),
                range(args.iterations),
            ):
                latencias.append(lat)
                detecciones += n

    wall = time.perf_counter() - t_inicio
    ordenadas = sorted(latencias)

    def _pct(p: float) -> float:
        if not ordenadas:
            return 0.0
        idx = min(len(ordenadas) - 1, int(round((p / 100) * (len(ordenadas) - 1))))
        return ordenadas[idx] * 1000

    informe = {
        "url": args.url,
        "iteraciones": args.iterations,
        "concurrencia": args.concurrency,
        "latencia_p50_ms": round(_pct(50), 1),
        "latencia_p95_ms": round(_pct(95), 1),
        "latencia_media_ms": round(statistics.mean(latencias) * 1000, 1) if latencias else 0.0,
        "latencia_max_ms": round(max(latencias) * 1000, 1) if latencias else 0.0,
        "throughput_fps": round(len(latencias) / wall, 2) if wall else 0.0,
        "detecciones_totales": detecciones,
        "segundos_totales": round(wall, 2),
    }
    print(json.dumps(informe, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
