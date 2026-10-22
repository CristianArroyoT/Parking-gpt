"""Todo campo validado en el alta debe validarse igual en la edición.

POR QUÉ (2026-10-22): el detector estático de asimetrías
(``tools/revisar_esquemas.py``) llevaba desde su creación **sin
comparar nada**: buscaba la pareja con ``nombre[:-5]`` y ``"Create"``
tiene **seis** letras, así que la pareja se llamaba ``CameraCUpdate`` y
no se encontraba jamás. Su "OK" era vacío.

Y al arreglarlo, encontró una asimetría **viva**: ``CameraUpdate.name``
aceptaba un nombre de 1 carácter o de 500, mientras que
``CameraCreate.name`` exigía de 2 a 128. Es el mismo tipo de agujero que
el de ``CameraUpdate.rtsp_url`` (2026-10-21).

Este test convierte la regla en **permanente y general**: recorre
todos los pares Create/Update de todos los esquemas y compara sus
restricciones. Si alguien añade una validación en un alta y olvida el
PATCH, la suite lo dice (y no hace falta acordarse de pasar el
detector).
"""
from __future__ import annotations

import importlib
import pkgutil

from pydantic import BaseModel

import app.schemas

#: Atributos de restricción que se comparan entre Create y Update.
ATRIBUTOS_RESTRICCION = (
    "min_length",
    "max_length",
    "pattern",
    "ge",
    "le",
    "gt",
    "lt",
    "multiple_of",
    "max_digits",
    "decimal_places",
)


def _restricciones(campo) -> dict[str, object]:
    """Las restricciones de un campo de pydantic, como diccionario."""
    encontradas: dict[str, object] = {}
    for meta in getattr(campo, "metadata", []) or []:
        for atributo in ATRIBUTOS_RESTRICCION:
            if hasattr(meta, atributo):
                encontradas[atributo] = getattr(meta, atributo)
    return encontradas


def _pares_create_update() -> list[tuple[str, type[BaseModel], type[BaseModel]]]:
    """Todos los pares (Create, Update) de todos los módulos de esquemas."""
    pares: list[tuple[str, type[BaseModel], type[BaseModel]]] = []
    for info in pkgutil.iter_modules(app.schemas.__path__):
        modulo = importlib.import_module(f"app.schemas.{info.name}")
        for nombre, objeto in vars(modulo).items():
            if not isinstance(objeto, type) or not issubclass(objeto, BaseModel):
                continue
            if objeto.__module__ != modulo.__name__:
                continue
            if not nombre.endswith("Create"):
                continue
            pareja = nombre[: -len("Create")] + "Update"
            contraparte = getattr(modulo, pareja, None)
            if contraparte is None:
                continue
            pares.append((f"{info.name}.{nombre}", objeto, contraparte))
    return pares


def test_hay_pares_create_update_que_comprobar() -> None:
    """Si no hay pares, el test de abajo no comprobaría nada."""
    pares = _pares_create_update()
    assert len(pares) >= 5, f"solo hay {len(pares)} pares Create/Update"


def test_los_update_validan_lo_mismo_que_los_create() -> None:
    """Cada campo validado en el alta, validado igual en la edición."""
    problemas: list[str] = []
    for etiqueta, create, update in _pares_create_update():
        for nombre, campo_create in create.model_fields.items():
            if nombre not in update.model_fields:
                # Campo inmutable: no se edita, no hay asimetría posible.
                continue
            create_r = _restricciones(campo_create)
            if not create_r:
                continue
            update_r = _restricciones(update.model_fields[nombre])
            if create_r != update_r:
                problemas.append(
                    f"{etiqueta}: '{nombre}' valida {create_r} pero su Update "
                    f"valida {update_r or 'nada'}"
                )
    assert not problemas, "Asimetrias Create/Update:\n  " + "\n  ".join(problemas)


def test_el_patch_de_camara_rechaza_un_nombre_corto() -> None:
    """El caso concreto que se coló: el nombre del PATCH sin límites."""
    from app.schemas.parking import CameraUpdate

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CameraUpdate(name="x")
    with pytest.raises(ValidationError):
        CameraUpdate(name="x" * 200)
    # Y un nombre válido se sigue aceptando.
    assert CameraUpdate(name="Cámara").name == "Cámara"
