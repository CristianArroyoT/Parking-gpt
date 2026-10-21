"""Entorno de Alembic: conecta los modelos del proyecto a la migración."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base
from app import models  # noqa: F401 — registra todos los modelos en Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata

#: Tablas de la imagen de PostGIS que NO son del proyecto: las de la
#: extension TIGER/Line (``tiger``, ``edges``, ``state``, ``addrfeat``,
#: ``zip_lookup``...). La imagen las crea al inicializar el cluster, asi
#: que si no se filtran, ``alembic check`` reporta como "operaciones
#: nuevas" un montón de tablas que jamas existieron en este proyecto.
#:
#: La columna ``parkings.geom`` viene de ``infra/seed.sql`` (la geometria
#: PostGIS de la sucursal), tampoco de una migracion.
POSTGIS_TABLAS_EXTERNAS = {
    "tiger", "edges", "state", "addrfeat", "zip_lookup", "place_lookup",
    "direction_lookup", "street_type_lookup", "loader_variables", "pagc_rules",
}


def incluir_objeto(
    objeto: object,
    name: str,
    tipo: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Filtro de la comparacion metadata <-> base de datos.

    Sin esto, ``alembic check`` (y ``alembic revision --autogenerate``)
    comparan los modelos contra la base ENTERA, incluidas las tablas
    que trae la imagen de PostGIS y la geometria que creo el seed.

    La firma es la que pide Alembic: ``(object, name, type_, reflected,
    compare_to)``.
    """
    if tipo == "table":
        if name in POSTGIS_TABLAS_EXTERNAS:
            return False
        return name in Base.metadata.tables
    if tipo == "column":
        # ``parkings.geom`` la crea ``infra/seed.sql``, no una migracion.
        # OJO: para una columna AÑADIDA, Alembic pasa la del modelo en
        # ``compare_to``; para una ELIMINADA pasa ``None`` y el objeto
        # es la columna reflejada. Hay que mirar las dos.
        origen = compare_to if compare_to is not None else objeto
        tabla = getattr(origen, "table", None)
        if getattr(tabla, "name", None) == "parkings" and name == "geom":
            return False
    if tipo == "index":
        # El indice espacial de ``parkings.geom`` tampoco es del app.
        return name != "idx_parkings_geom"
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=incluir_objeto,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=incluir_objeto,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()