# Backups de PostgreSQL (T-12)

> «Un backup sin restaurar probado no es un backup.» — regla del plan de
> pendientes. Todo lo de aquí está **verificado ejecutándose** sobre el stack
> `parking`, no sólo escrito.

## Qué hay

| Fichero | Para qué |
|---|---|
| `backup.sh` | Volcado diario, cifrado en reposo, retención GFS, copia remota opcional, comprobación de frescura |
| `restore.sh` | Restauración en una base limpia **con verificación** de que la base restaurada sirve |

## Puesta en marcha

### 1. La passphrase

La clave de cifrado **no** va en el repositorio ni en el entorno. Vive en un
fichero con permisos `600`:

```bash
# en el host que hace los backups
sudo install -m 600 /dev/null /etc/solidapp/backup.pass
sudo sh -c 'openssl rand -base64 32 > /etc/solidapp/backup.pass'
```

Si se pierde la passphrase, **los backups existentes son inservibles**. Hay
que guardarla en el gestor de secretos del equipo, no en un ticket.

### 2. Variables de entorno

```bash
export PGHOST=db PGPORT=5432 PGUSER=parking PGDATABASE=parking
export BACKUP_DIR=/var/backups/solidapp          # en un volumen cifrado
export BACKUP_PASSPHRASE_FILE=/etc/solidapp/backup.pass
export BACKUP_RETENTION_DAYS=7
export BACKUP_RETENTION_WEEKS=4
export BACKUP_RETENTION_MONTHS=6
export BACKUP_MAX_AGE_HOURS=26
```

### 3. Copia fuera del host (LOPDGDD)

El backup no puede vivir sólo en la misma máquina que los datos. Con un
destino S3-compatible (MinIO, Backblaze B2, Wasabi, S3 de AWS):

```bash
export BACKUP_REMOTE="s3://solidapp-backups/parking"
export BACKUP_REMOTE_CMD='aws s3 cp "$1" "$BACKUP_REMOTE/" --endpoint-url "$S3_ENDPOINT"'
```

Sin `BACKUP_REMOTE` el script **avisa por log** de que el backup se queda sólo
en local, pero no falla: en desarrollo es el comportamiento deseado.

### 4. Programación

```cron
# /etc/cron.d/solidapp-backup
17 3 * * * root BACKUP_DIR=/var/backups/solidapp BACKUP_PASSPHRASE_FILE=/etc/solidapp/backup.pass /opt/solidapp/infra/backup/backup.sh >> /var/log/solidapp/backup.log 2>&1
```

### 5. La alerta (decisión D3)

`backup.sh --check` sale con código:

| Código | Significado |
|---|---|
| `0` | el último backup es más reciente que `BACKUP_MAX_AGE_HOURS` |
| `1` | **el último backup es demasiado antiguo** → alertar |
| `2` | **no hay ningún backup** → alertar |

```cron
# /etc/cron.d/solidapp-backup-alert
*/30 * * * * root /opt/solidapp/infra/backup/backup.sh --check || /opt/solidapp/infra/backup/alert.sh
```

El script de alerta no se incluye aquí porque su destino (email, Slack,
OpsGenie) depende del canal de alerta del equipo: lo que **sí** se incluye es
el contrato de salida, para que la integración sea trivial.

---

## Formato

- `pg_dump --format=custom --compress=9`: comprimido y restaurable con
  `pg_restore` (no `pg_restore` en modo SQL). El formato custom lleva la
  definición de la extensión PostGIS dentro.
- Cifrado `openssl enc -aes-256-cbc -pbkdf2 -iter 200000`.
- Nombre: `solidapp-<AAAAMMDDThhmmssZ>.dump.enc` (UTC). El timestamp es lo que
  permite la retención GFS (el primero de cada semana / de cada mes).

### Retención GFS

- **7 diarios** — los 7 ficheros más recientes.
- **4 semanales** — el primero de cada semana ISO.
- **6 mensuales** — el primero de cada mes.

Todo lo demás se borra. Los ficheros de cabecera de mes/semana nunca se
borran porque están en las tres categorías.

---

## Restauración (probada)

### Restauración completa en una base limpia

```bash
./restore.sh --file /var/backups/solidapp-20261021T030000Z.dump.enc \
             --target-db parking_restore_test
```

El script:

1. Descifra el dump a un temporal y **comprueba la firma `PGDMP`**.
2. **Borra** la base destino y la crea de cero.
3. Habilita la extensión `postgis` **antes** del restore.
4. `pg_restore --exit-on-error`.
5. **Verifica**: cuenta las tablas de `public`, las filas de `users` y de
   `geofences`, y si PostGIS quedó instalado. Si no hay ninguna tabla, falla.

Salida verificada en el stack `parking`:

```
[restore] tablas en public : 20
[restore] filas en users   : 4
[restore] filas en geofences: 0
[restore] postgis instalado: 1
[restore] RESTAURACIÓN CORRECTA
```

### Puesta en marcha contra la base restaurada

```bash
DATABASE_URL=postgresql+psycopg://parking:<pass>@db:5432/parking_restore_test \
  docker compose up -d backend
curl http://localhost:8000/health
```

### Limpieza

```bash
docker exec parking-db-1 psql -U parking -d postgres -c 'DROP DATABASE "parking_restore_test";'
```

---

## Simulacro trimestral (obligatorio)

La decisión **D3** fija que el procedimiento de restauración se prueba **cada
trimestre**. Checklist:

- [ ] Lanzar `backup.sh` y comprobar que sale con `hecho` y sin errores.
- [ ] Comprobar que el fichero `.enc` existe y **no** se puede leer sin la
      passphrase (`head -c 16 <fichero>` no debe mostrar texto plano).
- [ ] `restore.sh` contra `parking_restore_test` → debe salir con
      `RESTAURACIÓN CORRECTA`.
- [ ] Arrancar el backend contra la base restaurada y que `/health` dé 200.
- [ ] Comprobar que el backup se ha subido al destino remoto.
- [ ] Registrar fecha, resultado y responsable en el ticket del trimestre.
- [ ] **Borrar la base de prueba.**

Un simulacro fallido es un **incidente**, no un papel: se abre ticket y no se
cierra el trimestre.
