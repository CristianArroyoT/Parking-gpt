# tools/

Utilidades del repo que no forman parte de la aplicación.

| Script | Para qué |
|---|---|
| `escanear_texto.py` | Detecta **corrupción de texto** en los ficheros del repo: caracteres de otros alfabetos (CJK, cirílico, coreano), ficheros que no son UTF-8 válido y monedas que no son el euro. El modelo de lenguaje se cuela con estos caracteres al escribir en español, y llegan hasta el commit. El informe se escribe en un fichero UTF-8 (la consola de Windows se come los acentos) y el informe es un artefacto disposable (va al `.gitignore`). |
| `comparar_informes.py` | Compara dos informes de Locust lado a lado: peticiones, fallos, bytes y el nº de previews descartados con un 409. Sirve para responder "¿esto ha sido una regresión o el ruido de siempre?" al comparar una ejecución nueva con la de referencia. |
| `resumir_qa_visual.py` | Resume el `informe.json` que produce `frontend/scripts/qa_visual.py`: cuántas pantallas quedan sin incidencias y qué errores de consola o de red hubo. |
| `extraer_api.py` | Extrae de los routers las **rutas y su RBAC** leyendo el código con `ast`, y las **comprueba contra el OpenAPI real**: si el extractor se deja alguna ruta fuera, sale con código 1. Es lo que alimenta el inventario de la API. |
| `generar_seccion_api.py` | Genera la sección 3 de `docs/API-INTERNAL.md` a partir del código (`--escribir` la deja en el documento). |
| `verificar_api_doc.py` | Comprueba que el inventario documentado coincide con el código y dice qué falta y qué sobra. Sale con 1 si hay deriva. |

## Uso

```bash
# Corrupcion de texto (antes de commitear)
python tools/escanear_texto.py backend docs tools frontend/README.md

# Comparar dos ejecuciones de carga
python tools/comparar_informes.py \
  backend/locust/reports/2026-10-21-referencia.json \
  backend/locust/reports/2026-10-22-nueva.json

# Resumen de la QA visual
python tools/resumir_qa_visual.py D:/tmp/qa-solidapp/informe.json

# Inventario de la API
python tools/extraer_api.py                     # rutas + RBAC
python tools/generar_seccion_api.py --escribir  # regenera el documento
python tools/verificar_api_doc.py               # detecta la deriva
```

Los scripts devuelven codigo de salida 0 si no hay nada que mirar y 1 si lo
hay (para poder encadenarlos en un script).
