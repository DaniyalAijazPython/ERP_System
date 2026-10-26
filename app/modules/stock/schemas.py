import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PaymentMethod(str, Enum):
    cash = "cash"
    bank = "bank"
    credit = "credit"


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------ Stock In
class StockInLineIn(BaseModel):
    item_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4, description="Price you paid for 1 unit")


class StockInIn(BaseModel):
    supplier_id: uuid.UUID | None = Field(default=None, description="Leave empty for 'Local market (cash)'")
    warehouse_id: uuid.UUID | None = Field(default=None, description="Leave empty for your main warehouse")
    payment_method: PaymentMethod = PaymentMethod.cash
    supplier_invoice_no: str | None = Field(default=None, max_length=50)
    tax_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)
    lines: list[StockInLineIn] = Field(min_length=1, max_length=200)


class StockInLineOut(_Out):
    item_id: uuid.UUID
    item_name: str
    unit_code: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class StockInOut(_Out):
    id: uuid.UUID
    number: str
    status: str
    supplier_id: uuid.UUID
    supplier_name: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    payment_method: str
    supplier_invoice_no: str | None
    tax_amount: Decimal | None
    note: str | None
    total: Decimal
    created_at: datetime
    lines: list[StockInLineOut]


# ------------------------------------------------------------ How much stock
class StockRowOut(BaseModel):
    item_id: uuid.UUID
    sku: str
    name: str
    unit_code: str
    quantity: Decimal
    avg_cost: Decimal
    stock_value: Decimal
    reorder_level: Decimal
    is_low: bool


class StockPage(BaseModel):
    items: list[StockRowOut]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------ Stock history
class MovementOut(_Out):
    id: uuid.UUID
    created_at: datetime
    item_id: uuid.UUID
    item_name: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    quantity: Decimal
    unit_cost: Decimal | None
    kind: str
    reference_number: str | None
    note: str | None


# ------------------------------------------------------------ Fix stock count
class StockFixIn(BaseModel):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID | None = None
    counted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3, description="What you really have now")
    reason: str = Field(min_length=3, max_length=300, description="Why the count was wrong")
