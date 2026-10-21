# tools/

Utilidades del repo que no forman parte de la aplicación.

| Script | Para qué |
|---|---|
| `escanear_texto.py` | Detecta **corrupción de texto** en los ficheros del repo: caracteres de otros alfabetos (CJK, cirílico, coreano), ficheros que no son UTF-8 válido y monedas que no son el euro. El modelo de lenguaje se cuela con estos caracteres al escribir en español, y llegan hasta el commit. El informe se escribe en un fichero UTF-8 (la consola de Windows se come los acentos) y el informe es un artefacto disposable (va al `.gitignore`). El modo `--tracked` escanea **exactamente lo versionado** por git (ni `node_modules`, ni `dist`): es el que usa el CI. |
| `comparar_informes.py` | Compara dos informes de Locust lado a lado: peticiones, fallos, bytes y el nº de previews descartados con un 409. Sirve para responder "¿esto ha sido una regresión o el ruido de siempre?" al comparar una ejecución nueva con la de referencia. |
| `resumir_qa_visual.py` | Resume el `informe.json` que produce `frontend/scripts/qa_visual.py`: cuántas pantallas quedan sin incidencias y qué errores de consola o de red hubo. |
| `extraer_api.py` | Extrae de los routers las **rutas y su RBAC** leyendo el código con `ast`, y las **comprueba contra el OpenAPI real**: si el extractor se deja alguna ruta fuera, sale con código 1. Es lo que alimenta el inventario de la API. |
| `generar_seccion_api.py` | Genera la sección 3 de `docs/API-INTERNAL.md` a partir del código (`--escribir` la deja en el documento). |
| `verificar_api_doc.py` | Comprueba que el inventario documentado coincide con el código y dice qué falta y qué sobra. Sale con 1 si hay deriva. Tiene autoprueba (`--autoprueba`). |
| `cobertura_api.py` | Mide **cuántos endpoints tienen test**. Distingue los que se prueban con la ruta literal de los que se prueban con una URL parametrizada, y de los que no tienen ningún test. La puerta es "todo endpoint tiene algún test"; además informa (de forma **indicativa**, con falsos positivos) de qué endpoints no tienen un test que compruebe el 401/403. |
| `verificar_despliegue_limpio.py` | Smoke test de un **despliegue limpio**: crea una base vacía, la migra de cero, la siembra, levanta la aplicación y comprueba que la API responde con los datos del seed. Borra la base al terminar. Es lo que faltaba: hasta ahora las migraciones y el seed nunca se habían probado juntos sobre una base vacía. |
| `escanear_secretos.py` | Busca credenciales en el **árbol versionado** (`--historial` para el historial completo de commits). El repositorio es público: un secreto commiteado no es un inconveniente, es una credencial filtrada. |
| `envolver_tablas.py` | Envuelve las tablas de las vistas del frontend en un contenedor desplazable (`overflow-x-auto min-w-0`) y les añade `min-w-max` **dentro** del atributo `class`. Sin esto, en el móvil la tabla se sale de su tarjeta y arrastra a la página entera en el scroll lateral. Muta la directiva `v-if`/`v-else` al envoltorio: si se deja en la tabla, Vue no compila. |
| `ejecutar_ci_local.py` | Ejecuta un job del workflow de GitHub Actions **leyendo el YAML** (sin duplicar los pasos a mano), con su `working-directory` y sus variables. Es la forma de comprobar el CI mientras la cuenta no tiene los jobs activados por facturación. `--all` replica **todos** los jobs con un resumen final, y honra `continue-on-error` igual que Actions. En Windows cambia `localhost` por `127.0.0.1` en las URLs de servicio (si no, cada conexión tarda 8 s esperando el timeout de IPv6). |
| `estado_ci.py` | Estado del CI remoto sobre `main`, con **diagnóstico**: distingue *verde*, *rojo de verdad* (un job ejecutó pasos y falló → es el código) y *rechazado por la cuenta* (los jobs terminan en `failure` **con 0 pasos** → es la facturación, no el código). Sale con 0 / 1 / 2 respectivamente. |
| `verificar_repo.py` | **El estado de salud del repo en un comando**: texto versionado, secretos, inventario de la API, cobertura de endpoints, esquemas, `alembic check`, SLO, PWA y (con `--completo`) el CI replicado en local y la QA visual en los 5 anchos. Devuelve 0 si todo está bien y 1 si algo falla. **Es la red de seguridad mientras el CI remoto no pueda arrancar** (ver §"Por qué el CI remoto no puede arrancar"). |

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

# Cobertura de tests por endpoint
python tools/cobertura_api.py                   # quien queda sin test

# Despliegue limpio (base vacia -> migrar -> sembrar -> servir)
$env:DATABASE_URL="postgresql+psycopg://parking:parking@localhost:5432/solidapp_despliegue"
python tools/verificar_despliegue_limpio.py

# Secretos
python tools/escanear_secretos.py            # arbol versionado
python tools/escanear_secretos.py --historial # historial completo

# Envolver las tablas del frontend para el movil
python tools/envolver_tablas.py

# Ejecutar un job del CI en local (lee el YAML del workflow)
python tools/ejecutar_ci_local.py --list
python tools/ejecutar_ci_local.py --job integration

# Replicar TODOS los jobs del workflow (la red de seguridad mientras el
# CI remoto esta bloqueado por la facturacion)
python tools/ejecutar_ci_local.py --all

# Un job suelto
python tools/ejecutar_ci_local.py --job backend

# Estado del CI remoto sobre main, con diagnostico
python tools/estado_ci.py

# Estado de salud del repo en un comando (la puerta mientras el CI remoto
# esta bloqueado por la facturacion)
python tools/verificar_repo.py            # rapido: ~1 min
python tools/verificar_repo.py --completo # + CI local y QA visual: ~40 min
```

### Requisitos para que la réplica local sea completa

| Qué | Por qué |
|---|---|
| El stack de Docker arriba | La réplica usa los servicios publicados en `127.0.0.1` (PostgreSQL, Redis) |
| Las bases `parking_test` y `parking_test_mavis` | Las usa el job de integración (`CREATE DATABASE`) |
| Dependencias del backend instaladas en el host | El paso "Instalar dependencias" es el único que la réplica no ejecuta (el entorno ya está listo) |

Los scripts devuelven codigo de salida 0 si no hay nada que mirar y 1 si lo
hay (para poder encadenarlos en un script).
