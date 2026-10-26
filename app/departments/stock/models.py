import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base import Base, utcnow


class DocCounter(Base):
    """Gives each company its own numbers: GR-0001, GR-0002 ..."""

    __tablename__ = "doc_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class StockBalance(Base):
    """How much of an item is in a warehouse right now. A copy of the history, kept up to date."""

    __tablename__ = "stock_balances"

    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"), primary_key=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StockMovement(Base):
    """Stock history. Rows are only added. Never edited, never deleted."""

    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))  # + adds stock, - removes stock
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # stock_in, stock_in_undone, count_fix
    reference_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    item = relationship("Item")
    warehouse = relationship("Warehouse")

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def warehouse_name(self) -> str:
        return self.warehouse.name


class GoodsReceipt(Base):
    """'Stock In': a record of stock you received."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_receipts_tenant_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_receipts_tenant_idem"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(String(30))
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("parties.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    payment_method: Mapped[str] = mapped_column(String(10), default="cash")
    supplier_invoice_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="posted")  # posted, undone
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="GoodsReceiptLine.position"
    )
    supplier = relationship("Party")
    warehouse = relationship("Warehouse")

    @property
    def supplier_name(self) -> str:
        return self.supplier.name

    @property
    def warehouse_name(self) -> str:
        return self.warehouse.name

    @property
    def total(self) -> Decimal:
        return sum((l.line_total for l in self.lines), Decimal("0")).quantize(Decimal("0.01"))


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("goods_receipts.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))

    receipt: Mapped[GoodsReceipt] = relationship(back_populates="lines")
    item = relationship("Item")

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def unit_code(self) -> str:
        return self.item.unit.code

    @property
    def line_total(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class StockOut(Base):
    """'Stock Out': stock that leaves a warehouse (to production, damaged, sample ...)."""

    __tablename__ = "stock_outs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_stock_outs_tenant_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_stock_outs_tenant_idem"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(String(30))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    reason: Mapped[str] = mapped_column(String(20))  # production, damaged, sample, other
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="posted")  # posted, undone
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lines: Mapped[list["StockOutLine"]] = relationship(
        back_populates="stock_out", cascade="all, delete-orphan", order_by="StockOutLine.position"
    )
    warehouse = relationship("Warehouse")

    @property
    def warehouse_name(self) -> str:
        return self.warehouse.name

    @property
    def total_cost(self) -> Decimal:
        return sum((l.line_cost for l in self.lines), Decimal("0")).quantize(Decimal("0.01"))


class StockOutLine(Base):
    __tablename__ = "stock_out_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    stock_out_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stock_outs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))  # cost when it left

    stock_out: Mapped[StockOut] = relationship(back_populates="lines")
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


class StockMove(Base):
    """'Move stock': from one warehouse to another."""

    __tablename__ = "stock_moves"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_stock_moves_tenant_number"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_stock_moves_tenant_idem"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(String(30))
    from_warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("warehouses.id"))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    lines: Mapped[list["StockMoveLine"]] = relationship(
        back_populates="stock_move", cascade="all, delete-orphan", order_by="StockMoveLine.position"
    )
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])

    @property
    def from_warehouse_name(self) -> str:
        return self.from_warehouse.name

    @property
    def to_warehouse_name(self) -> str:
        return self.to_warehouse.name


class StockMoveLine(Base):
    __tablename__ = "stock_move_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    stock_move_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stock_moves.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))

    stock_move: Mapped[StockMove] = relationship(back_populates="lines")
    item = relationship("Item")

    @property
    def item_name(self) -> str:
        return self.item.name

    @property
    def unit_code(self) -> str:
        return self.item.unit.code
