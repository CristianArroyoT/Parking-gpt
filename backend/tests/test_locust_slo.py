"""Tests del verificador del SLO de carga (T-13 del plan maestro).

POR QUÉ hay tests aquí
----------------------
El verificador (``backend/locust/check_slo.py``) es lo que hace que una
regresión de rendimiento rompa el build. Si el verificador se rompe (o
siempre dice "OK"), el SLO deja de proteger el producto y nadie se entera
hasta que un cliente lo ve. Estos tests cubren:

* el cálculo del percentil (tiene que dar el mismo número que Locust);
* la evaluación de las reglas (cumple / incumple / sin muestras);
* que el SLO versionado en el repo sea coherente;
* que **la ejecución de referencia guardada en el repo cumpla el SLO**
  (si alguien cambia un umbral sin volver a medir, este test lo delata).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

CARPETA_BACKEND: Path = Path(__file__).resolve().parent.parent
RUTA_CHECK_SLO: Path = CARPETA_BACKEND / "locust" / "check_slo.py"
RUTA_SLO: Path = CARPETA_BACKEND / "locust" / "slo.json"
RUTA_INFORME_REFERENCIA: Path = (
    CARPETA_BACKEND / "locust" / "reports" / "2026-10-21-referencia.json"
)


def _cargar_modulo() -> Any:
    """Carga ``check_slo.py`` por ruta.

    Se carga por ruta (y no como paquete) a propósito: el directorio
    ``backend/locust/`` NO lleva ``__init__.py`` para no ensombrecer la
    librería ``locust`` cuando el CLI de Locust añade el directorio del
    locustfile al ``sys.path``.
    """
    spec = importlib.util.spec_from_file_location("solidapp_check_slo", RUTA_CHECK_SLO)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


check_slo = _cargar_modulo()


def _entrada(
    nombre: str = "lectura_plazas",
    metodo: str = "GET",
    peticiones: int = 20,
    fallos: int = 0,
    tiempos: dict[int, int] | None = None,
    bytes_total: int = 0,
) -> dict[str, Any]:
    """Construye una entrada del informe de Locust para los tests."""
    if tiempos is None:
        tiempos = {50: peticiones}
    return {
        "method": metodo,
        "name": nombre,
        "num_requests": peticiones,
        "num_failures": fallos,
        "total_content_length": bytes_total,
        "response_times": {str(k): v for k, v in tiempos.items()},
    }


def _regla(**kwargs: Any) -> dict[str, Any]:
    """Regla de SLO mínima para los tests."""
    regla: dict[str, Any] = {
        "id": "regla_test",
        "method": "GET",
        "name": "lectura_plazas",
        "metrica": "percentil_ms",
        "percentil": 0.95,
        "umbral": 300,
        "min_mamples": 5,
    }
    regla.update(kwargs)
    return regla


# ─────────────────────────── Percentil ───────────────────────────


def test_percentil_histograma_usa_el_algoritmo_de_locust() -> None:
    """El p95 tiene que coincidir con el que muestra la web de Locust."""
    # 9 peticiones de 10 ms y 1 de 100 ms: el p95 cae en la lenta.
    assert check_slo.percentil_histograma({10: 9, 100: 1}, 10, 0.95) == 100
    # El p50 cae en la rápida.
    assert check_slo.percentil_histograma({10: 9, 100: 1}, 10, 0.5) == 10
    # Un solo valor: todos los percentiles dan ese valor.
    assert check_slo.percentil_histograma({42: 7}, 7, 0.95) == 42
    # Histograma vacío: 0 (no hay tiempos que medir).
    assert check_slo.percentil_histograma({}, 0, 0.95) == 0


def test_percentil_histograma_rechaza_percentiles_invalidos() -> None:
    with pytest.raises(ValueError, match="percentil"):
        check_slo.percentil_histograma({10: 1}, 1, 0)
    with pytest.raises(ValueError, match="percentil"):
        check_slo.percentil_histograma({10: 1}, 1, 1.5)


# ─────────────────────────── Evaluación de reglas ───────────────────────────


def test_regla_cumple_si_el_p95_no_supera_el_umbral() -> None:
    entradas = check_slo.entradas_desde_datos([_entrada(tiempos={50: 20})])
    resultado = check_slo.evaluar_regla(entradas[0], _regla())
    assert resultado.cumple is True
    assert resultado.valor == 50


def test_regla_incumple_si_el_p95_supera_el_umbral() -> None:
    """Éste es el test que da valor al verificador: el CI tiene que rojo."""
    entradas = check_slo.entradas_desde_datos([_entrada(tiempos={900: 20})])
    resultado = check_slo.evaluar_regla(entradas[0], _regla())
    assert resultado.cumple is False
    assert resultado.valor == 900


def test_regla_incumple_si_hay_fallos() -> None:
    entradas = check_slo.entradas_desde_datos([_entrada(fallos=3)])
    resultado = check_slo.evaluar_regla(entradas[0], _regla(metrica="max_fallos", umbral=0))
    assert resultado.cumple is False
    assert resultado.valor == 3


def test_regla_de_bytes_medios_detecta_un_stream_congelado() -> None:
    entradas = check_slo.entradas_desde_datos([_entrada(bytes_total=1000)])
    resultado = check_slo.evaluar_regla(
        entradas[0],
        _regla(metrica="min_bytes_medios", umbral=50000),
    )
    assert resultado.cumple is False


def test_regla_falla_si_no_hay_muestras_suficientes() -> None:
    """Sin muestras no se puede juzgar el SLO: se falla (no se "pasa")."""
    entradas = check_slo.entradas_desde_datos([_entrada(peticiones=2)])
    resultado = check_slo.evaluar_regla(entradas[0], _regla(min_muestras=5))
    assert resultado.cumple is False
    assert "muestras insuficientes" in resultado.detalle


def test_regla_falla_si_la_metrica_no_aparece_en_el_informe() -> None:
    """Si el escenario no llegó a ejecutarse, el SLO no se puede evaluar."""
    resultado = check_slo.evaluar_regla(None, _regla())
    assert resultado.cumple is False
    assert "no aparece en el informe" in resultado.detalle


def test_evaluar_devuelve_un_resultado_por_regla() -> None:
    entradas = check_slo.entradas_desde_datos([_entrada(tiempos={50: 20})])
    slo = {"reglas": [_regla(), _regla(id="otra", umbral=10)]}
    resultados = check_slo.evaluar(entradas, slo)
    assert len(resultados) == 2
    assert resultados[0].cumple is True
    assert resultados[1].cumple is False


def test_metrica_desconocida_falla_con_mensaje_util() -> None:
    entradas = check_slo.entradas_desde_datos([_entrada()])
    resultado = check_slo.evaluar_regla(entradas[0], _regla(metrica="no_existe"))
    assert resultado.cumple is False
    assert "métrica desconocida" in resultado.detalle


# ─────────────────── Ocurrencias (métrica max_peticiones) ───────────────────
#
# Los 409 del preview los cuenta Locust como "éxito" (un 409 es una regla
# de negocio: la cámara está ocupada), así que ninguna métrica basada en
# fallos los detectaría. La métrica ``max_peticiones`` cuenta las
# ocurrencias de una entrada, que es lo que permite que el SLO detecte una
# regresión del P2 del preview (T-13+6).


def test_max_peticiones_cumple_si_no_hay_ninguna_ocurrencia() -> None:
    entradas = check_slo.entradas_desde_datos(
        [_entrada(nombre="preview_mjpeg_omitido_409", peticiones=0)],
    )
    resultado = check_slo.evaluar_regla(
        entradas[0],
        _regla(nombre="preview_mjpeg_omitido_409", metrica="max_peticiones", umbral=0),
    )
    assert resultado.cumple is True
    assert resultado.valor == 0


def test_max_peticiones_incumple_si_hay_ocurrencias() -> None:
    """Éste es el detector de la regresión del P2: un solo 409 en el
    escenario de carga pone el SLO en rojo."""
    entradas = check_slo.entradas_desde_datos(
        [_entrada(nombre="preview_mjpeg_omitido_409", peticiones=1)],
    )
    resultado = check_slo.evaluar_regla(
        entradas[0],
        _regla(nombre="preview_mjpeg_omitido_409", metrica="max_peticiones", umbral=0),
    )
    assert resultado.cumple is False
    assert resultado.valor == 1


def test_max_peticiones_cumple_si_la_entrada_no_aparece_en_el_informe() -> None:
    """Si no hubo ningún 409, la entrada no aparece en el informe: eso
    son 0 ocurrencias, no "no se puede judging"."""
    resultado = check_slo.evaluar_regla(
        None,
        _regla(nombre="preview_mjpeg_omitido_409", metrica="max_peticiones", umbral=0),
    )
    assert resultado.cumple is True
    assert resultado.valor == 0


def test_el_slo_incluye_la_regla_de_409_del_preview() -> None:
    """El SLO versionado tiene que vigilar los 409 del preview: sin esta
    regla, una regresión del P2 pasaría inadvertida bajo carga."""
    slo = check_slo.cargar_slo(RUTA_SLO)
    reglas = {r["id"]: r for r in slo["reglas"]}
    assert "mjpeg_sin_409" in reglas, "el SLO no vigila los 409 del preview"
    regla = reglas["mjpeg_sin_409"]
    assert regla["name"] == "preview_mjpeg_omitido_409"
    assert regla["metrica"] == "max_peticiones"
    assert regla["umbral"] == 0


# ─────────────────────────── SLO e informe de referencia ───────────────────────────


def test_el_slo_versionado_es_coherente() -> None:
    slo = check_slo.cargar_slo(RUTA_SLO)
    assert slo.get("reglas"), "el SLO no define ninguna regla"
    for regla in slo["reglas"]:
        assert {"id", "method", "name", "metrica", "umbral"} <= set(regla), regla
        assert regla["metrica"] in check_slo.METRICAS, regla
        assert isinstance(regla["umbral"], (int, float)), regla
        assert regla.get("motivo"), f"la regla {regla['id']} no explica por qué"


def test_la_ejecucion_de_referencia_cumple_el_slo() -> None:
    """El informe guardado en el repo tiene que pasar el SLO versionado.

    Si alguien cambia un umbral sin volver a medir (o al revés, si el
    hardware de referencia se degrada), este test lo delata.
    """
    assert RUTA_INFORME_REFERENCIA.exists(), (
        f"falta la ejecución de referencia: {RUTA_INFORME_REFERENCIA}"
    )
    informe = check_slo.cargar_informe(RUTA_INFORME_REFERENCIA)
    slo = check_slo.cargar_slo(RUTA_SLO)
    resultados = check_slo.evaluar(informe, slo)
    fallan = [r for r in resultados if not r.cumple]
    assert not fallan, "\n".join(str(r) for r in fallan)


def test_el_informe_de_referencia_trae_los_cuatro_escenarios() -> None:
    """El informe tiene que cubrir los cuatro escenarios que pide el plan."""
    assert RUTA_INFORME_REFERENCIA.exists()
    informe = check_slo.cargar_informe(RUTA_INFORME_REFERENCIA)
    nombres = {entrada.name for entrada in informe}
    for esperado in (
        "login",
        "sse_mapa_primer_evento",
        "ticket_cerrar",
        "preview_mjpeg_primer_frame",
    ):
        assert esperado in nombres, f"el informe no recoge el escenario {esperado}"


def test_main_devuelve_codigo_de_salida_segun_el_informe(tmp_path: Path) -> None:
    """Código de salida: 0 si cumple, 1 si incumple, 2 si no puede leer."""
    slo = tmp_path / "slo.json"
    slo.write_text(
        json.dumps({"titulo": "test", "reglas": [_regla()]}),
        encoding="utf-8",
    )
    informe_ok = tmp_path / "ok.json"
    informe_ok.write_text(json.dumps([_entrada(tiempos={50: 20})]), encoding="utf-8")
    informe_malo = tmp_path / "malo.json"
    informe_malo.write_text(json.dumps([_entrada(tiempos={900: 20})]), encoding="utf-8")

    assert check_slo.main(["--report", str(informe_ok), "--slo", str(slo)]) == 0
    assert check_slo.main(["--report", str(informe_malo), "--slo", str(slo)]) == 1
    assert check_slo.main(["--report", str(tmp_path / "no_existe.json")]) == 2
