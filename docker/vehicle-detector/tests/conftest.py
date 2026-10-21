"""Deja importable el módulo ``app`` del servicio desde los tests.

El servicio vive en ``docker/vehicle-detector/app.py`` y se copia a
``/app/app.py`` en la imagen. Los tests se ejecutan contra ese mismo
directorio, así que ``import app`` debe resolver al servicio real (no a
un paquete homónimo del entorno).
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
