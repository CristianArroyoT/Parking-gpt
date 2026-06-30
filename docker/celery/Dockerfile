# Imagen Celery: parte de la misma imagen del backend ya construida y
# cambia el CMD. Reutiliza todas las deps (FastAPI, SQLAlchemy, etc.).
FROM solidapp-backend:latest AS base

WORKDIR /app

# El CMD se sobreescribe en docker-compose según servicio:
#   celery-worker → celery -A app.workers.celery_app worker --loglevel=info
#   celery-beat   → celery -A app.workers.celery_app beat   --loglevel=info
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info"]