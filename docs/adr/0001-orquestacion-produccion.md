# ADR-0001 · Orquestación en producción: Compose por sucursal + central

- **Estado**: Aceptada
- **Fecha**: 2026-10-21
- **Ítem del plan**: T-15 (Bloque 2 · I4 — Orquestación Swarm/K8s)
- **Contexto**: [`2026-10-21-plan-pendientes-solidapp-design.md`](../../superpowers/specs/2026-10-21-plan-pendientes-solidapp-design.md)

---

## Contexto

El despliegue actual es `docker compose` en un único host (un portátil de
QA). El objetivo de producto que describe la memoria del proyecto es:

> 50+ sucursales con servidores locales + cluster central HA.

Las dos halves del sistema tienen requisitos **distintos** y eso es lo que
condiciona la decisión:

| Parte | Qué necesita | Qué NO necesita |
|---|---|---|
| **Sucursal (edge)** | 1 servidor, unos pocos servicios, que funcione **sin internet**, arranque desatendido, coste mínimo | Alta disponibilidad, rolling updates, autoscaling, orquestadores multi-nodo |
| **Central** | HA, escalado, despliegue a 50 puntos a la vez, monitorización | Coste mínimo |

Equipo: pyme tecnológica de reciente creación. El coste de operación
(horas-persona, curva de aprendizaje, guardias) es la variable dominante,
no el coste de las máquinas.

## Opciones

### A. Docker Compose en todas partes

Un `docker-compose.yml` por sucursal (edge) + uno para el central.

- **A favor**: cero conceptos nuevos; el equipo ya lo usa; `docker compose up -d`
  en un portátil nuevo; los ficheros de configuración son los mismos; el
  despliegue a una sucursal es copiar un directorio y arrancar.
- **En contra**: no hay rolling update (caída de segundos al reiniciar un
  servicio), no hay HA en el central, no hay rolling deploy a 50 sucursales
  (hay que hacerlo por SSH/script), sin métricas de salud por servicio.
- **Coste**: ~0. Curva de aprendizaje: 0.

### B. Docker Swarm

- **A favor**: el CLI es casi el mismo (`docker stack deploy`), rolling updates
  y réplicas nativas, secretos y configs centralizados, `docker node ls` da
  una vista de la flota.
- **En contra**: Docker ha dejado de invertir en Swarm (la dirección del
  proyecto es Compose + Kubernetes); el ecosistema se ha movido a K8s; la
  documentación y el soporte community están congelados; el modo Swarm
  requiere un manager y_memory sizing distinto; **no resuelve el edge
  offline** igual que Compose (también necesita manager), lo que lo deja
  peor que Compose para la sucursal y peor que K8s para el central.
- **Coste**: bajo. Curva de aprendizaje: media.

### C. Kubernetes (k3s en edge, k3s/K8s en central)

- **A favor**: el estándar de facto, `kubectl` para todo, rolling updates
  reales, autoscaling, operators, ecosystems enorme (Prometheus, ArgoCD,
  cert-manager), y el **central** es exactamente el caso de uso para el que
  K8s existe.
- **En contra**: **el edge no lo quiere**. Una sucursal con 8 GB de RAM en un
  servidor pequeño no puede correr un k3s cómodo; el cluster queda
  Single-Node y sin HA (que es el objetivo de la sucursal: que funcione
  solo). Operación: hay que aprender K8s, que es un salto real de curva; el
  equipo es de 2-3 personas.
- **Coste**: bajo en licencias, **alto en tiempo-persona**.

### D. Híbrido: Compose en el edge, K8s en el central

- **A favor**: cada parte con la herramienta que le corresponde. La sucursal
  no necesita un orquestador; el central sí.
- **En contra**: dos formas de operar (Compose y kubectl) que mantener; los
  manifiestos del central no son los mismos ficheros que los del edge.

## Decisión

**Opción D — Compose en el edge, Kubernetes en el central**, con un matiz
importante: **el central empieza con Compose también** y se migra a k3s
sólo cuando se dispare un criterio objetivo.

### Por qué el edge va con Compose

1. La sucursal **debe funcionar sin internet** (si se cae el enlace, el
   parking sigue entrando coches y el OCR sigue leyendo matrículas). Un
   orquestador es un punto de fallo adicional y un componente que hay que
   actualizar.
2. `docker compose up -d` en un portátil es **todo** el proceso de alta de
   una sucursal. Con un técnico de campo, eso son 10 minutos; con K8s, un
   cluster que hay que bootstrapear, exponer puertos, tokens, etc.
3. El hardware de una sucursal es pequeño (4-8 GB). K3s se come 1-2 GB en
   idle. En ese presupuesto, K3s se come la RAM del OCR.
4. Un `docker-compose.yml` es **un fichero legible y versionable**. El
   técnico de campo puede leerlo.

### Por qué el central sí es caso de K8s (y cuándo)

El central sí tiene el perfil de K8s: muchos servicios, rolling deploys,
HA. **Pero** el salto se hace cuando se cumpla **al menos uno** de estos
criterios (y no antes):

| # | Criterio | Por qué |
|---|---|---|
| 1 | > 5 servicios con dependencias y ciclos de despliegue | Compose no ordena los despliegues; K8s sí (y `helm`) |
| 2 | Se necesita **rolling update sin caída** en el central | Compose reinicia: hay ventana de error |
| 3 | > 2 réplicas de la API con balanceo | Compose no reasigna VIP de forma nativa |
| 4 | Hay que desplegar cambios a 50 sucursales sin tocar cada una | K8s + ArgoCD / Fleet |
| 5 | Coste-persona disponible para operar K8s | Sin dueño, K8s se pudre |

**Hasta que se cumpla uno de ellos: central en Compose**, con dos
réplicas de la API detrás de un proxy (nginx) y una VIP Keepalived si hace
falta. Es menos elegante y mucho más barato de operar.

### La condición que no se puede negociar

**Nada de HA sin backups probados.** Un central con dos réplicas y una base
de datos única no es HA: es un punto de fallo con más piezas. Por eso
**T-12 (backups con restauración probada) es requisito previo** a cualquier
paso de HA, y por eso el simulacro trimestral no es opcional.

Ver [`infra/backup/README.md`](../../../infra/backup/README.md).

## Consecuencias

### Positivas

- El alta de una sucursal es un `rsync` + `docker compose up -d`. Escala a
  50 sucursales sin equipo de plataforma.
- El central no se toca hasta que hace falta: el coste de operación del
  MVP es el de hoy (Compose), no el de un cluster.
- El estado de la base de datos es **uno y el mismo** para edge y central:
  Postgres con pg_dump + retención GFS + restauración probada.
- Si mañana hace falta K8s, se migra **el central**, y el edge (50
  sucursales) no se toca. El coste de la decisión se paga una vez y en un
  sitio.

### Negativas / costes asumidos

- **No hay rolling update en el edge**: reiniciar un servicio corta las
  peticiones durante unos segundos. Aceptable: la sucursal degrada, no
  cae (el OCR y la API son independientes; el MJPEG es lo único que se
  nota).
- **El despliegue a 50 sucursales es manual** hasta que se active el
  criterio 4. Mitigación: un `docker-compose.override.yml` por entorno
  (dev/QA/prod) versionado, y un script de despliegue por SSH.
- **Dosque monitorizar**: central y edge. El central tiene Prometheus +
  Grafana + Loki (ya montados en `infra/`); el edge, como mínimo, el health
  check de sus contenedores y un ping al central.

### follow-ups

- Script de despliegue a una sucursal (`infra/deploy/branch.sh`).
- Fichero `docker-compose.prod.yml` con los valores por defecto del
  producto (JWT secret por entorno, `CORS_ORIGINS` correctos, volúmenes).
  **Avanzado (2026-10-21)**: mientras ese fichero no exista, la
  aplicación **se niega a arrancar** en `staging`/`production` si
  `JWT_SECRET` sigue siendo el valor por defecto (`change-me-in-production`),
  que está escrito en este repositorio público. Es un fallo temprano y
  explícito, en vez de un 401 sin explicación a mitad de una sesión.
  **Hecho (2026-10-22, T-74)**: el fichero existe y es
  `docker-compose.prod.yml` (un *override* del de desarrollo). El
  despliegue de una sucursal es:

  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  # Las migraciones (OBLIGATORIO: sin ellas la base se queda sin tablas
  # y todas las peticiones devuelven 500):
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
      exec backend alembic upgrade head
  # El primer administrador (OBLIGATORIO: sin el, nadie puede entrar):
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
      exec -e SOLIDAPP_ADMIN_EMAIL -e SOLIDAPP_ADMIN_PASSWORD backend \
      python -m app.scripts.create_admin
  ```

  Los dos pasos son **obligatorios** y no se pueden saltar en silencio
  (medido el 2026-10-25, T-185): sin migraciones el despliegue arrancaba
  «sano» y rompía en cada petición; sin administrador no había forma de
  entrar (la aplicación sólo crea usuarios si ya hay un admin).

  Con él: `ENVIRONMENT=production`, el **secreto, la URL pública y los
  orígenes son obligatorios** (si faltan, `docker compose` falla al
  arrancar, con un mensaje que dice qué falta), y el frontend se sirve
  con la imagen de producción (nginx), no con el dev-server de Vite.
  El `docker-compose.yml` de la raíz sigue siendo el de **desarrollo**
  (para el portátil de QA). La puerta `tools/verificar_compose_produccion.py`
  lo vigila.
- Alertas de "la sucursal lleva X horas sin conectar al central".

### La superficie de red de una sucursal (2026-10-21)

El `docker-compose.yml` **es** el fichero que se copia a una sucursal
(`rsync` + `docker compose up -d`), así que su configuración de puertos
es configuración de producción, no del portátil de QA.

> **Ojo (2026-10-22, T-74)**: a la sucursal se copia el fichero **con el
> override de producción**: `docker compose -f docker-compose.yml
> -f docker-compose.prod.yml up -d`. Con el `docker-compose.yml` a
> secas, el backend arrancaría en `development` (sin exigir el secreto
> JWT real, que es público en este repositorio) y el frontend lo
> serviría el dev-server de Vite. Lo que se publica
en la red de la sucursal es sólo lo que la sucursal tiene que atender:

| Servicio | Puerto | ¿Quién lo necesita? |
|---|---|---|
| `backend` | 8000 | El central y los dispositivos de la sucursal: **sí, publicado** |
| `frontend` | 5173 | Los técnicos y los dispositivos: **sí, publicado** |
| `db` | 5432 | Nadie fuera de Docker: **loopback** |
| `redis` | 6379 | Nadie fuera de Docker (y **no tiene contraseña**): **loopback** |
| `ocr` | 8801 | Nadie fuera de Docker: **loopback** |
| `vehicle-detector` | 8802 | Nadie fuera de Docker: **loopback** |
| `loki` | 3100 | Nadie fuera de Docker: **loopback** |
| `grafana` | 3000 | Nadie fuera de Docker (y lleva la contraseña por defecto `admin`): **loopback** |

Comprobado: desde la IP de la red local los puertos 5432, 6379 y 3000 ya
**no responden**; desde el propio host, sí. Los servicios se siguen
hablando por la red de Docker (`db:5432`, `redis:6379`…), que es
privada por definición.

### Los requisitos de despliegue (2026-10-22)

Lo que el código exige y hay que cumplir al desplegar. Están escritos
también en `frontend/README.md` ("Requisitos del despliegue") y los vigila
`tools/verificar_compose_produccion.py`:

| Requisito | Por qué | Qué pasa si falta |
|---|---|---|
| **Un TLS delante** (https) | Los navegadores no registran *service workers* en HTTP sin cifrar | La app funciona, pero **no es instalable ni arranca sin red**: es exactamente lo que hace la PWA |
| `FRONTEND_BASE_URL` con la URL real | Es la URL que va en los correos (el de recuperar contraseña) | La aplicación **no arranca** en `staging`/`production` (fallo temprano y explícito) |
| `TRUSTED_PROXIES` con la IP del proxy | El backend tiene que saber qué IP es la del cliente | El rate-limit de login se comparte para **toda la sucursal** (10 intentos / 5 min contados como si fueran la misma persona) y la auditoría guarda la IP del proxy |
| `JWT_SECRET` real | Está en un repositorio público | Tokens de administrador falsificables |
| Módulo `realip` de nginx si hay un CDN delante | Para que `$remote_addr` sea la IP real del visitante | Se registra la IP del CDN |

## Alternativas descartadas (y por qué)

| Alternativa | Por qué no |
|---|---|
| Kubernetes también en el edge | El hardware de la sucursal no lo aguanta y el objetivo (funcionar solo) no lo necesita |
| Swarm en todas partes | Docker ya no lo mantiene; peor que Compose en edge y peor que K8s en central |
| K8s desde ya | Coste-persona desproporcionado para el escenario; además el central no necesita HA hoy |
| Un único central multi-tenant con 50 sucursales en la nube | Cambia el modelo de producto: el MVP es «servidor local en la sucursal» |
| Sin backups, confiado en snapshots del hipervisor | Un snapshot no es un backup: no se ha probado a restaurar, y no protege del error humano |
