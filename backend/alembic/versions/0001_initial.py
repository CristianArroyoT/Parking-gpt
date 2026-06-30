"""Migración inicial: 13 tablas + extensión PostGIS.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-30 00:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="cliente"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "parkings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.String(512), nullable=False),
        sa.Column("city", sa.String(128), nullable=False),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("geom", Geometry(geometry_type="POINT", srid=4326), nullable=True),
    )
    op.create_index("ix_parkings_code", "parkings", ["code"], unique=True)

    op.create_table(
        "parking_memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parking_id", sa.Integer, sa.ForeignKey("parkings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_in_parking", sa.String(32), nullable=False, server_default="gestor"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "parking_id", name="uq_user_parking"),
    )
    op.create_index("ix_parking_memberships_user_id", "parking_memberships", ["user_id"])
    op.create_index("ix_parking_memberships_parking_id", "parking_memberships", ["parking_id"])

    op.create_table(
        "parking_spaces",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parking_id", sa.Integer, sa.ForeignKey("parkings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lane", sa.String(8), nullable=False),
        sa.Column("number", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_parking_spaces_parking_id", "parking_spaces", ["parking_id"])
    op.create_index("ix_parking_spaces_lane", "parking_spaces", ["lane"])

    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parking_id", sa.Integer, sa.ForeignKey("parkings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("rtsp_url", sa.String(1024), nullable=False),
        sa.Column("lane_hint", sa.String(8)),
        sa.Column("fps", sa.Integer, nullable=False, server_default="10"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_cameras_parking_id", "cameras", ["parking_id"])

    op.create_table(
        "camera_geofences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("camera_id", sa.Integer, sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parking_space_id", sa.Integer, sa.ForeignKey("parking_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("x", sa.Float, nullable=False),
        sa.Column("y", sa.Float, nullable=False),
        sa.Column("w", sa.Float, nullable=False),
        sa.Column("h", sa.Float, nullable=False),
        sa.Column("confidence_threshold", sa.Float, nullable=False, server_default="0.85"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("camera_id", "parking_space_id", name="uq_camera_space"),
    )
    op.create_index("ix_camera_geofences_camera_id", "camera_geofences", ["camera_id"])

    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plate", sa.String(16), nullable=False, unique=True),
        sa.Column("brand", sa.String(64)),
        sa.Column("model", sa.String(64)),
        sa.Column("color", sa.String(32)),
        sa.Column("vehicle_type", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vehicles_plate", "vehicles", ["plate"], unique=True)

    op.create_table(
        "vehicle_users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="propietario"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vehicle_id", "user_id", "role", name="uq_vehicle_user_role"),
    )
    op.create_index("ix_vehicle_users_vehicle_id", "vehicle_users", ["vehicle_id"])
    op.create_index("ix_vehicle_users_user_id", "vehicle_users", ["user_id"])

    op.create_table(
        "tariffs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parking_id", sa.Integer, sa.ForeignKey("parkings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("price_per_hour", sa.Float, nullable=False),
        sa.Column("price_per_fraction", sa.Float, nullable=False),
        sa.Column("fraction_minutes", sa.Integer, nullable=False, server_default="15"),
        sa.Column("max_daily", sa.Float),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tariffs_parking_id", "tariffs", ["parking_id"])

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("monthly_price", sa.Float, nullable=False),
        sa.Column("discount_percent", sa.Float, nullable=False),
        sa.Column("included_vehicles", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_plans_code", "plans", ["code"], unique=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer, sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parking_id", sa.Integer, sa.ForeignKey("parkings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parking_space_id", sa.Integer, sa.ForeignKey("parking_spaces.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="activo"),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_at", sa.DateTime(timezone=True)),
        sa.Column("amount", sa.Float),
        sa.Column("discount", sa.Float),
        sa.Column("total", sa.Float),
        sa.Column("payment_method", sa.String(32)),
        sa.Column("pdf_path", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tickets_parking_id", "tickets", ["parking_id"])
    op.create_index("ix_tickets_vehicle_id", "tickets", ["vehicle_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("ip", sa.String(64)),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource", sa.String(128)),
        sa.Column("payload", sa.JSON),
        sa.Column("confidence", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("parking_id", sa.Integer, sa.ForeignKey("parkings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="warn"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("context", sa.JSON),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_alerts_parking_id", "alerts", ["parking_id"])
    op.create_index("ix_alerts_type", "alerts", ["type"])


def downgrade() -> None:
    for tbl in [
        "alerts",
        "audit_logs",
        "tickets",
        "subscriptions",
        "plans",
        "tariffs",
        "vehicle_users",
        "vehicles",
        "camera_geofences",
        "cameras",
        "parking_spaces",
        "parking_memberships",
        "parkings",
        "users",
    ]:
        op.drop_table(tbl)
    op.execute("DROP EXTENSION IF EXISTS postgis")