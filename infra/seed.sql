-- Script PostGIS: se ejecuta automáticamente por la imagen postgis/postgis
-- al primer arranque del contenedor (docker-entrypoint-initdb.d/).
-- Crea la extensión si no existe (también la creamos desde Alembic en
-- la migración inicial como red de seguridad).
CREATE EXTENSION IF NOT EXISTS postgis;