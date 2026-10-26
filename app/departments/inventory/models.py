import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base import Base, utcnow


class ItemType(str, enum.Enum):
    raw_material = "raw_material"
    finished_good = "finished_good"
    consumable = "consumable"


class PartyKind(str, enum.Enum):
    supplier = "supplier"
    customer = "customer"


class _Stamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Unit(Base, _Stamped):
    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_units_tenant_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))


class Item(Base, _Stamped):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_items_tenant_sku"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    sku: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200), index=True)
    item_type: Mapped[str] = mapped_column(String(20), default=ItemType.raw_material.value)
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("units.id"))
    # Cost is NOT stored here: it comes from the price actually paid on goods receipts.
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    unit: Mapped[Unit] = relationship()


class Warehouse(Base, _Stamped):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_warehouses_tenant_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Party(Base, _Stamped):
    """A supplier or a customer."""

    __tablename__ = "parties"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "name", name="uq_parties_tenant_kind_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)  # e.g. "Local market (cash)"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
