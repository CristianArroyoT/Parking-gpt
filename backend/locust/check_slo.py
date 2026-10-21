"""Verificador del SLO de carga de solidAPP.

Lee el informe JSON que genera Locust (``--json-file``) y comprueba que
se cumple el SLO definido en ``backend/locust/slo.json``. Devuelve un
código de salida distinto de cero si alguna regla se incumple, de modo que
es integrable tal cual en un job de CI (nocturno o no).

Uso::

    python backend/locust/check_slo.py --report backend/locust/reports/xxx.json
    python backend/locust/check_slo.py --report informe.json --slo otro_slo.json

Códigos de salida::

    0  todas las reglas se cumplen
    1  alguna regla se incumple (o no hay muestras suficientes para juzgarla)
    2  error de uso o de lectura de ficheros

POR QUÉ el percentil se calcula aquí y no se lee del informe
-------------------------------------------------------------
El informe de Locust guarda el HISTOGRAMA de tiempos de respuesta
(``response_times``: ``{milisegundos: numero_de_peticiones}``), no el
percentil. Para que el verificador dé el mismo número que el ``p95`` que
muestra la web de Locust, se replica aquí su algoritmo
(``calculate_response_time_percentile``): percentil más cercano por rango.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUTA_SLO_POR_DEFECTO: Path = Path(__file__).resolve().parent / "slo.json"

#: Métricas soportadas por el verificador.
METRICAS = ("percentil_ms", "max_fallos", "min_bytes_medios", "max_tasa_fallo", "max_peticiones")


class InformeError(ValueError):
    """El informe no tiene el formato esperado."""


@dataclass(frozen=True)
class Entrada:
    """Una entrada del informe de Locust (un ``StatsEntryDict``)."""

    method: str
    name: str
    num_requests: int
    num_failures: int
    total_content_length: int
    response_times: dict[int, int]

    @property
    def muestras(self) -> int:
        """Peticiones con tiempo de respuesta conocido."""
        return sum(self.response_times.values())

    @property
    def bytes_medios(self) -> float:
        """Bytes medios recibidos por petición."""
        if not self.num_requests:
            return 0.0
        return self.total_content_length / self.num_requests

    @property
    def tasa_fallo(self) -> float:
        """Proporción de peticiones fallidas (0.0 - 1.0)."""
        if not self.num_requests:
            return 0.0
        return self.num_failures / self.num_requests


@dataclass
class Resultado:
    """Resultado de evaluar una regla del SLO."""

    id: str
    metrica: str
    valor: float | None
    umbral: float
    cumple: bool
    detalle: str = ""
    contexto: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        marca = "OK  " if self.cumple else "FALLO"
        valor = "-" if self.valor is None else f"{self.valor:.1f}"
        return f"[{marca}] {self.id}: {self.metrica}={valor} (umbral {self.umbral}) {self.detalle}"


def percentil_histograma(response_times: dict[int, int], num_peticiones: int, percentil: float) -> int:
    """Percentil de un histograma de tiempos de respuesta.

    Réplica del algoritmo de Locust (``calculate_response_time_percentile``)
    para que el número del verificador sea el mismo que muestra la web de
    Locust: percentil más cercano por rango sobre el histograma.
    """
    if percentil <= 0 or percentil > 1:
        raise ValueError("el percentil debe estar en (0, 1]")
    objetivo = int(num_peticiones * percentil)
    procesados = 0
    for tiempo in sorted(response_times.keys(), reverse=True):
        procesados += response_times[tiempo]
        if num_peticiones - procesados <= objetivo:
            return tiempo
    return 0


def entradas_desde_datos(datos: Any, origen: str = "informe") -> list[Entrada]:
    """Convierte el JSON de Locust (lista de entradas) en objetos ``Entrada``."""
    if isinstance(datos, dict):
        # Locust escribe una lista; se tolera un envoltorio {"stats": [...]}.
        datos = datos.get("stats", [])
    if not isinstance(datos, list):
        raise InformeError(f"{origen}: se esperaba una lista de entradas de Locust")
    entradas: list[Entrada] = []
    for bruto in datos:
        if not isinstance(bruto, dict):
            raise InformeError(f"{origen}: entrada no válida: {bruto!r}")
        response_times = bruto.get("response_times") or {}
        entradas.append(
            Entrada(
                method=str(bruto.get("method") or ""),
                name=str(bruto.get("name") or ""),
                num_requests=int(bruto.get("num_requests") or 0),
                num_failures=int(bruto.get("num_failures") or 0),
                total_content_length=int(bruto.get("total_content_length") or 0),
                response_times={int(k): int(v) for k, v in response_times.items()},
            )
        )
    return entradas


def cargar_informe(ruta: Path) -> list[Entrada]:
    """Lee el informe JSON de Locust y devuelve sus entradas."""
    with open(ruta, encoding="utf-8") as fh:
        datos = json.load(fh)
    return entradas_desde_datos(datos, origen=str(ruta))


def cargar_slo(ruta: Path) -> dict[str, Any]:
    """Lee la definición del SLO."""
    with open(ruta, encoding="utf-8") as fh:
        slo = json.load(fh)
    if not isinstance(slo, dict) or "reglas" not in slo:
        raise InformeError(f"{ruta}: el SLO debe ser un objeto con la clave 'reglas'")
    return slo


def buscar_entrada(entradas: list[Entrada], method: str, name: str) -> Entrada | None:
    """Busca la entrada del informe que corresponde a una regla.

    El método se compara sin distinguir mayusculas (Locust escribe ``GET``,
    ``POST``…) y el nombre tiene que coincidir exactamente.
    """
    for entrada in entradas:
        if entrada.name == name and entrada.method.upper() == method.upper():
            return entrada
    return None


def evaluar_regla(entrada: Entrada | None, regla: dict[str, Any]) -> Resultado:
    """Evalúa una regla del SLO contra la entrada del informe."""
    metrica = str(regla.get("metrica", ""))
    umbral = float(regla.get("umbral", 0))
    id_regla = str(regla.get("id", "?"))
    min_muestras = int(regla.get("min_muestras", 0))

    if entrada is None:
        if metrica == "max_peticiones":
            # La métrica cuenta *ocurrencias* de una entrada: que no
            # aparezca en el informe significa 0 ocurrencias, no
            # "no se puede juzgar".
            return Resultado(
                id=id_regla,
                metrica=metrica,
                valor=0.0,
                umbral=umbral,
                cumple=umbral >= 0.0,
                detalle="la entrada no aparece en el informe (0 ocurrencias)",
            )
        return Resultado(
            id=id_regla,
            metrica=metrica,
            valor=None,
            umbral=umbral,
            cumple=False,
            detalle="la métrica no aparece en el informe (el escenario no llegó a ejecutarse)",
        )
    if entrada.num_requests == 0:
        if metrica == "max_peticiones":
            return Resultado(
                id=id_regla,
                metrica=metrica,
                valor=0.0,
                umbral=umbral,
                cumple=umbral >= 0.0,
                detalle="0 ocurrencias",
            )
        return Resultado(
            id=id_regla,
            metrica=metrica,
            valor=None,
            umbral=umbral,
            cumple=False,
            detalle="la métrica no tiene peticiones registradas",
        )
    if min_muestras and entrada.muestras < min_muestras:
        return Resultado(
            id=id_regla,
            metrica=metrica,
            valor=None,
            umbral=umbral,
            cumple=False,
            detalle=(
                f"muestras insuficientes ({entrada.muestras} < {min_muestras}): "
                "no se puede juzgar el SLO"
            ),
            contexto={"peticiones": entrada.num_requests, "muestras": entrada.muestras},
        )

    if metrica == "percentil_ms":
        percentil = float(regla.get("percentil", 0.95))
        valor = float(percentil_histograma(entrada.response_times, entrada.num_requests, percentil))
        cumple = valor <= umbral
        detalle = (
            f"p{int(percentil * 100)}={valor:.0f} ms con {entrada.num_requests} peticiones "
            f"({entrada.num_failures} fallos)"
        )
    elif metrica == "max_fallos":
        valor = float(entrada.num_failures)
        cumple = valor <= umbral
        detalle = f"{entrada.num_failures} fallos en {entrada.num_requests} peticiones"
    elif metrica == "min_bytes_medios":
        valor = entrada.bytes_medios
        cumple = valor >= umbral
        detalle = f"{valor:.0f} bytes/petición de media"
    elif metrica == "max_tasa_fallo":
        valor = entrada.tasa_fallo
        cumple = valor <= umbral
        detalle = f"{valor * 100:.2f}% de fallos en {entrada.num_requests} peticiones"
    elif metrica == "max_peticiones":
        # Nº de veces que ocurrió la entrada. Sirve para las entradas
        # que Locust cuenta como "éxito" pero que en realidad son un
        # síntoma: por ejemplo los previews omitidos con un 409 (la
        # cámara ocupada), que el locustfile registra aparte porque un
        # 409 es una regla de negocio y no un fallo.
        valor = float(entrada.num_requests)
        cumple = valor <= umbral
        detalle = f"{entrada.num_requests} ocurrencias"
    else:
        return Resultado(
            id=id_regla,
            metrica=metrica,
            valor=None,
            umbral=umbral,
            cumple=False,
            detalle=f"métrica desconocida: {metrica} (soportadas: {', '.join(METRICAS)})",
        )

    return Resultado(
        id=id_regla,
        metrica=metrica,
        valor=valor,
        umbral=umbral,
        cumple=cumple,
        detalle=detalle,
        contexto={"peticiones": entrada.num_requests, "fallos": entrada.num_failures},
    )


def evaluar(informe: list[Entrada], slo: dict[str, Any]) -> list[Resultado]:
    """Evalúa todas las reglas del SLO contra el informe."""
    resultados: list[Resultado] = []
    for regla in slo.get("reglas", []):
        entrada = buscar_entrada(informe, str(regla.get("method", "")), str(regla.get("name", "")))
        resultados.append(evaluar_regla(entrada, regla))
    return resultados


def formatear(resultados: list[Resultado], informe: list[Entrada], slo: dict[str, Any]) -> str:
    """Texto legible del resultado (para el log del CI)."""
    lineas = [
        f"SLO: {slo.get('titulo', 'sin título')}",
        f"Referencia: {slo.get('referencia', '-')}",
        "",
        "Métricas del informe:",
    ]
    for entrada in sorted(informe, key=lambda e: (e.method, e.name)):
        lineas.append(
            f"  {entrada.method:<5} {entrada.name:<32} "
            f"peticiones={entrada.num_requests:<6} fallos={entrada.num_failures:<5} "
            f"p95={percentil_histograma(entrada.response_times, entrada.num_requests, 0.95):>7} ms"
        )
    lineas.append("")
    lineas.append("Reglas:")
    for resultado in resultados:
        lineas.append(f"  {resultado}")
    incumplidas = [r for r in resultados if not r.cumple]
    lineas.append("")
    if incumplidas:
        lineas.append(f"SLO INCUMPLIDO: {len(incumplidas)} de {len(resultados)} reglas fallan.")
    else:
        lineas.append(f"SLO CUMPLIDO: {len(resultados)} reglas OK.")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada. Devuelve 0 (cumple), 1 (incumple) o 2 (error)."""
    parser = argparse.ArgumentParser(
        description="Comprueba el informe de carga de Locust contra el SLO de solidAPP.",
    )
    parser.add_argument("--report", required=True, help="Informe JSON de Locust (--json-file)")
    parser.add_argument(
        "--slo",
        default=str(RUTA_SLO_POR_DEFECTO),
        help="Definición del SLO (por defecto: slo.json junto a este script)",
    )
    parser.add_argument(
        "--solo-incumplidas",
        action="store_true",
        help="Muestra sólo las reglas que fallan",
    )
    args = parser.parse_args(argv)

    try:
        informe = cargar_informe(Path(args.report))
        slo = cargar_slo(Path(args.slo))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: no se pudo leer el informe o el SLO: {exc}", file=sys.stderr)
        return 2

    resultados = evaluar(informe, slo)
    if args.solo_incumplidas:
        fallan = [r for r in resultados if not r.cumple]
        if not fallan:
            print("SLO CUMPLIDO: ninguna regla incumplida.")
            return 0
        print("\n".join(f"  {r}" for r in fallan))
        print(f"SLO INCUMPLIDO: {len(fallan)} de {len(resultados)} reglas fallan.")
        return 1

    print(formatear(resultados, informe, slo))
    return 1 if any(not r.cumple for r in resultados) else 0


if __name__ == "__main__":
    raise SystemExit(main())
