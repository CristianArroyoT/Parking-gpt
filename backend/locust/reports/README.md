# Informes de carga

Informes JSON que genera Locust (`--json-file`) y que consume
`backend/locust/check_slo.py` para comprobar el SLO de
`backend/locust/slo.json`.

| Fichero | Qué es |
|---|---|
| `2026-10-21-referencia.json` | Ejecución de referencia (2026-10-21): 6 usuarios virtuales (5 operadores + 1 visualizador) durante 180 s contra la instancia dedicada de carga (`parking-carga`). Es la línea base contra la que se comparan las ejecuciones siguientes. |
| `2026-10-21-referencia.contexto.json` | Contexto de esa ejecución (fecha, host, usuarios, cámaras, logins realizados). El informe de Locust no lo incluye, y sin él un número suelto no es reproducible. |

Formato: la lista de entradas que produce Locust (`serialize_stats()`), una
por métrica, con `method`, `name`, `num_requests`, `num_failures`,
`total_content_length` y el histograma `response_times` (milisegundos →
nº de peticiones). El verificador calcula los percentiles replicando el
algoritmo de Locust.

Regenerar el informe de referencia (el procedimiento completo, con la
instancia dedicada y las cámaras de carga, está en `../README.md` §4):

```bash
docker run --rm --network parking_default \
  -v D:/Parking/backend:/carga -w /carga \
  -e SOLIDAPP_CAMARA_IDS=81,154,155,156,157,158,159,160,161,162 \
  -e SOLIDAPP_INFORME_CONTEXTO=/carga/locust/reports/2026-10-21-referencia.contexto.json \
  locustio/locust -f /carga/locustfile.py --headless \
  --host http://parking-carga:8000 --users 6 --spawn-rate 2 --run-time 180s \
  --json-file /carga/locust/reports/2026-10-21-referencia

python backend/locust/check_slo.py --report backend/locust/reports/2026-10-21-referencia.json
```

Ojo con el nombre de la variable: es `SOLIDAPP_CAMARA_IDS` (una R). Antes
el locustfile leía en runtime `SOLIDAPP_CAMERA_IDS` (dos R), así que poner
la variable como dice este README no surtía efecto y la ejecución se
quedaba siempre con la cámara 81. Ahora se aceptan las dos.
