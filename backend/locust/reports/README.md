# Informes de carga

Informes JSON que genera Locust (`--json-file`) y que consume
`backend/locust/check_slo.py` para comprobar el SLO de
`backend/locust/slo.json`.

| Fichero | Qué es |
|---|---|
| `2026-10-21-referencia.json` | Ejecución de referencia (2026-10-21): 11 usuarios virtuales durante 90 s contra el stack de QA. Es la línea base contra la que se comparan las ejecuciones siguientes. |
| `2026-10-21-referencia.contexto.json` | Contexto de esa ejecución (fecha, host, usuarios, cámaras, logins realizados). El informe de Locust no lo incluye, y sin él un número suelto no es reproducible. |

Formato: la lista de entradas que produce Locust (`serialize_stats()`), una
por métrica, con `method`, `name`, `num_requests`, `num_failures`,
`total_content_length` y el histograma `response_times` (milisegundos →
nº de peticiones). El verificador calcula los percentiles replicando el
algoritmo de Locust.

Regenerar el informe de referencia (ver `../README.md`):

```bash
docker run --rm --network parking_default \
  -v D:/Parking/backend:/carga -w /carga \
  -e SOLIDAPP_CAMERA_IDS=81,136,137,138,139 \
  -e SOLIDAPP_INFORME_CONTEXTO=/carga/locust/reports/2026-10-21-referencia.contexto.json \
  locustio/locust -f /carga/locustfile.py --headless \
  --host http://parking-backend-1:8000 --users 11 --spawn-rate 5 --run-time 90s \
  --json-file /carga/locust/reports/2026-10-21-referencia

python backend/locust/check_slo.py --report backend/locust/reports/2026-10-21-referencia.json
```
