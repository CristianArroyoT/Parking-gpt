"""Esquemas del flujo de recuperación de contraseña (T-22).

Se separan en su propio módulo (y no en ``app/schemas/__init__.py``) para
no tocar un fichero compartido mientras otros agentes trabajan en paralelo
sobre el mismo repo.
"""

from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas import ORMModel


class ForgotPasswordRequest(ORMModel):
    """Petición de "olvidé mi contraseña".

    Sólo lleva el email: la respuesta es SIEMPRE la misma exista o no la
    cuenta (responder distinto revelaría qué emails están registrados →
    enumeración de cuentas).
    """

    email: EmailStr


class ResetPasswordRequest(ORMModel):
    """Payload del restablecimiento con el token recibido por correo.

    ``token`` es el valor en claro que llega en el enlace del correo; el
    servidor sólo guarda su hash SHA-256.
    ``new_password`` sigue la misma política que el alta de usuario
    (mínimo 8 caracteres).
    """

    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)


__all__ = ["ForgotPasswordRequest", "ResetPasswordRequest"]
