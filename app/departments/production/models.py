import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base import Base, utcnow


class Recipe(Base):
    """What goes into a finished item. Example: 10 shirts = 20 m cloth + 10 spools thread."""

    __tablename__ = "recipes"
    __table_args__ = (UniqueConstraint("tenant_id", "item_id", name="uq_recipes_tenant_item"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))  # the finished item
    makes: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("1"))  # the lines below make this many
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    item = relationship("Item")
    lines: Mapped[list["RecipeLine"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeLine.position"
    )

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def unit_code(self) -> str:
        return self.item.unit.code


class RecipeLine(Base):
    __tablename__ = "recipe_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("recipes.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))  # the material
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))

    recipe: Mapped[Recipe] = relationship(back_populates="lines")
    item = relationship("Item")

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def unit_code(self) -> str:
        return self.item.unit.code


class ProductionOrder(Base):
    """'Make': materials go out, finished items come in, and we work out what each one cost."""

    __tablename__ = "production_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_production_tenant_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_production_tenant_idem"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(String(30))
    recipe_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("recipes.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    materials_warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    output_warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(10), default="done")  # done, undone
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    materials_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    extra_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    item = relationship("Item")
    materials_warehouse = relationship("Warehouse", foreign_keys=[materials_warehouse_id])
    output_warehouse = relationship("Warehouse", foreign_keys=[output_warehouse_id])
    materials: Mapped[list["ProductionMaterial"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="ProductionMaterial.position"
    )
    extra_costs: Mapped[list["ProductionExtraCost"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="ProductionExtraCost.position"
    )

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def unit_code(self) -> str:
        return self.item.unit.code

    @property
    def materials_warehouse_name(self) -> str:
        return self.materials_warehouse.name

    @property
    def output_warehouse_name(self) -> str:
        return self.output_warehouse.name


class ProductionMaterial(Base):
    __tablename__ = "production_materials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("production_orders.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))  # cost when it was used

    order: Mapped[ProductionOrder] = relationship(back_populates="materials")
    item = relationship("Item")

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def unit_code(self) -> str:
        return self.item.unit.code

    @property
    def line_cost(self) -> Decimal:
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"))


class ProductionExtraCost(Base):
    """Other costs, like daily-wage labour. Optional."""

    __tablename__ = "production_extra_costs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("production_orders.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    order: Mapped[ProductionOrder] = relationship(back_populates="extra_costs")
