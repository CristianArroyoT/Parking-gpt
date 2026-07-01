"""Decorador ``@audited`` para instrumentar handlers FastAPI (sprint Fase 3A).

Envuelve un handler y, al finalizar (éxito o excepción capturada),
inserta una fila en ``audit_logs`` con la duración del handler,
el resultado (success/failure) y el correlation_id del request.

Uso::

    from app.core.audit import audited

    @router.post("/some-resource/{res_id}", response_model=...)
    @audited("create_some_resource", resource_arg="res_id")
    def create_some_resource(
        res_id: int,
        payload: SomeCreate,
        request: Request,
        db: Session = Depends(get_db),
    ) -> SomeRead:
        ...

El decorador:
  - Detecta si la función es ``async`` o sync y aplica el wrapper adecuado.
  - Inyecta ``Request`` en la firma (FastAPI lo satisface automáticamente).
  - Mide ``duration_ms`` con ``time.monotonic()``.
  - En éxito → ``record_audit_from_request(..., result="success", ...)``.
  - En excepción → ``record_audit_from_request(..., result="failure",
    payload={"error": str(exc)})`` y re-lanza la excepción (no swallow).
  - Si por la razón que sea no hay ``request`` o ``db`` en el scope
    (caso patológico), el audit se omite — el handler NUNCA falla por
    culpa del decorador.
"""
from __future__ import annotations

import functools
import inspect
import time
from typing import Any, Callable

from fastapi import Request
from sqlalchemy.orm import Session

from app.services.audit import record_audit_from_request


def audited(action: str, *, resource_arg: str | None = None) -> Callable:
    """Decora un handler FastAPI para registrar ``audit_logs`` automáticamente."""

    def _decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)

        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs):
            started = time.monotonic()
            request: Request | None = kwargs.get("request")
            db: Session | None = kwargs.get("db")
            try:
                result = await func(*args, **kwargs)
                _safe_audit(
                    request, db, action, resource_arg, kwargs,
                    result_str="success",
                    duration_ms=_elapsed_ms(started),
                )
                return result
            except Exception as exc:
                _safe_audit(
                    request, db, action, resource_arg, kwargs,
                    result_str="failure",
                    duration_ms=_elapsed_ms(started),
                    error=str(exc),
                )
                raise

        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            started = time.monotonic()
            request: Request | None = kwargs.get("request")
            db: Session | None = kwargs.get("db")
            try:
                result = func(*args, **kwargs)
                _safe_audit(
                    request, db, action, resource_arg, kwargs,
                    result_str="success",
                    duration_ms=_elapsed_ms(started),
                )
                return result
            except Exception as exc:
                _safe_audit(
                    request, db, action, resource_arg, kwargs,
                    result_str="failure",
                    duration_ms=_elapsed_ms(started),
                    error=str(exc),
                )
                raise

        wrapper = _async_wrapper if inspect.iscoroutinefunction(func) else _sync_wrapper
        # FastAPI introspects __signature__ para resolver los Depends.
        wrapper.__signature__ = sig  # type: ignore[attr-defined]
        return wrapper

    return _decorator


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _safe_audit(
    request: Request | None,
    db: Session | None,
    action: str,
    resource_arg: str | None,
    kwargs: dict[str, Any],
    *,
    result_str: str,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Inserta audit con try/except defensivo. NUNCA rompe el handler."""
    if request is None or db is None:
        return
    resource: str | None = None
    if resource_arg and resource_arg in kwargs:
        value = kwargs[resource_arg]
        # Convierte `alert_id` → `alerts/123`, `ticket_id` → `tickets/123`.
        kind = resource_arg.replace("_id", "s")
        resource = f"{kind}/{value}"
    payload: dict[str, Any] = {"duration_ms": duration_ms}
    if error:
        payload["error"] = error[:200]
    try:
        record_audit_from_request(
            request, db,
            action=action,
            resource=resource,
            payload=payload,
            result=result_str,
            duration_ms=duration_ms,
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


__all__ = ["audited"]