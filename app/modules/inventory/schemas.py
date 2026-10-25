import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.inventory.models import ItemType


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- units
class UnitIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)


class UnitOut(_Out):
    id: uuid.UUID
    code: str
    name: str


# ---- items
class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    item_type: ItemType = ItemType.raw_material
    unit_id: uuid.UUID
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    reorder_level: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=3)


class ItemUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    item_type: ItemType | None = None
    unit_id: uuid.UUID | None = None
    sale_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    reorder_level: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=3)
    is_active: bool | None = None


class ItemOut(_Out):
    id: uuid.UUID
    sku: str
    name: str
    item_type: str
    unit_id: uuid.UUID
    unit: UnitOut
    sale_price: Decimal | None
    reorder_level: Decimal
    is_active: bool


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


# ---- warehouses
class WarehouseIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_default: bool = False


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_default: bool | None = None
    is_active: bool | None = None


class WarehouseOut(_Out):
    id: uuid.UUID
    name: str
    is_default: bool
    is_active: bool


# ---- parties (suppliers / customers)
class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=500)


class PartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class PartyOut(_Out):
    id: uuid.UUID
    kind: str
    name: str
    phone: str | None
    address: str | None
    is_system: bool
    is_active: bool
