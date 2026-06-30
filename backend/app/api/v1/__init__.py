"""Concentrador de routers v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, cameras, parkings, spaces, tariffs, tickets, users, vehicles

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(parkings.router)
api_router.include_router(spaces.router)
api_router.include_router(cameras.router)
api_router.include_router(vehicles.router)
api_router.include_router(tariffs.router)
api_router.include_router(tickets.router)

__all__ = ["api_router"]
