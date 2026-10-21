"""Cierra la deriva entre los modelos y el esquema real (T-25+3).

Nada de esto estaba en el plan: salió al comprobar con ``alembic
check`` si los modelos y las migraciones contaban la misma historia.
Contaban dos, y en los dos sentidos.

**1. Índices que los modelos declaraban y la base no tenía.** El
modelo dice ``index=True`` en ``cameras.code``,
``parking_spaces.number``, ``camera_geofences.parking_space_id`` y
``tickets.parking_space_id``, pero ninguna migración los creó: se
crearon las columnas y ya. No es un problema de corrección (las
consultas funcionan), pero sí de rendimiento: son columnas por las que
se filtra en cada listado, y sin índice es un Seq Scan por petición.

**2. Restricciones UNIQUE redundantes.** La migración inicial
(0001) creó, en las columnas con unicidad, *las dos cosas*: la
restricción ``UNIQUE`` a nivel de columna (``users_email_key``…) y un
índice único (``ix_users_email``…). El modelo, en cambio, declara
``unique=True, index=True``, que en SQLAlchemy produce **un único
índice único** y nada más. La base tenía, por tanto, una restricción
de sobra en cuatro tablas.

Esto último era una trampa de verdad: ``alembic check`` fallaba, así
que el siguiente que autogenerase una migración se habría llevado por
delante un ``DROP CONSTRAINT`` de las cuatro unicidades — y los
emails, matrículas y códigos habrían dejado de ser únicos sin que
nadie se enterase. Por eso la migración se escribe **a mano** y con un
``downgrade`` que las restituye.

**Lo que NO se toca**: ``parkings.geom`` y su índice espacial los crea
``infra/seed.sql`` (no una migración), y las tablas TIGER/Line las trae
la imagen de PostGIS. El ``alembic/env.py`` las filtra para que
``alembic check`` compare sólo las tablas del proyecto.

Revisa: 0013_incident_attachments
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_indices_y_uniques"
down_revision: str | None = "0013_incident_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: (tabla, índice) que los modelos declaran y faltaban en la base.
INDICES_FALTANTES = [
    ("cameras", "ix_cameras_code", ["code"]),
    ("parking_spaces", "ix_parking_spaces_number", ["number"]),
    ("camera_geofences", "ix_camera_geofences_parking_space_id", ["parking_space_id"]),
    ("tickets", "ix_tickets_parking_space_id", ["parking_space_id"]),
]

#: (tabla, restricción, columna) que sobraban: la unicidad ya la
#: garantiza el índice único de la misma columna, así que la
#: restricción es redundante. Al quitarla NO se pierde la unicidad.
UNIQUES_REDUNDANTES = [
    ("users", "users_email_key", "email"),
    ("vehicles", "vehicles_plate_key", "plate"),
    ("parkings", "parkings_code_key", "code"),
    ("plans", "plans_code_key", "code"),
]


def upgrade() -> None:
    # ── 1. Índices que faltaban ───────────────────────────────────────────
    for tabla, nombre, columnas in INDICES_FALTANTES:
        op.create_index(nombre, tabla, columnas)

    # ── 2. Restricciones UNIQUE redundantes ──────────────────────────────
    # Se quitan con ``batch_alter_table`` para que la migración también
    # funcione en SQLite (que no admite ``ALTER TABLE ... DROP
    # CONSTRAINT``). El índice único de la columna se queda: la
    # unicidad sigue garantizada.
    for tabla, restriccion, _columna in UNIQUES_REDUNDANTES:
        with op.batch_alter_table(tabla) as batch:
            batch.drop_constraint(restriccion, type_="unique")


def downgrade() -> None:
    # Se restituyen las restricciones UNIQUE (el estado anterior).
    for tabla, restriccion, columna in UNIQUES_REDUNDANTES:
        with op.batch_alter_table(tabla) as batch:
            batch.create_unique_constraint(restriccion, [columna])

    for tabla, nombre, _columnas in reversed(INDICES_FALTANTES):
        op.drop_index(nombre, table_name=tabla)
