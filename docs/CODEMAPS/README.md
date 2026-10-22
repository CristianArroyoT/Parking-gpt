# Codemaps

Mapa del código **por trabajo grande**, no por fichero. Cada codemap dice
qué toca, qué contrato cambió y dónde está lo relacionado, para que otra
sesión pueda situarse sin leerse el repo entero.

## Convención

- Un fichero por trabajo: `AAA-MM-DD-<slug>.md`.
- Se crea **en el mismo commit** que el trabajo que documenta (regla 7 del
  plan maestro: *"los cambios de contrato —API, modelos, rutas— se documentan
  en el mensaje del commit y en `docs/CODEMAPS/`"*).
- Se actualiza (no se duplica) si el mismo trabajo crece.

## Índice

| Codemap | Qué cubre |
|---|---|
| [2026-10-21-cierre-del-plan.md](2026-10-21-cierre-del-plan.md) | Cierre del plan de pendientes 2026-10-21: 101 endpoints, 24 routers, los modelos y variables nuevos, y **los cambios de contrato** (ámbitos, RBAC y comportamientos que un consumidor nota). |
