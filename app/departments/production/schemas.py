import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------ Recipe
class RecipeLineIn(BaseModel):
    item_id: uuid.UUID = Field(description="The material")
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)


class RecipeIn(BaseModel):
    item_id: uuid.UUID = Field(description="The finished item you make")
    makes: Decimal = Field(default=Decimal("1"), gt=0, max_digits=18, decimal_places=3,
                           description="How many finished items the lines below make")
    note: str | None = Field(default=None, max_length=500)
    lines: list[RecipeLineIn] = Field(min_length=1, max_length=100)


class RecipeUpdateIn(BaseModel):
    makes: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    note: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    lines: list[RecipeLineIn] | None = Field(default=None, min_length=1, max_length=100)


class RecipeLineOut(_Out):
    item_id: uuid.UUID
    item_name: str
    unit_code: str
    quantity: Decimal


class RecipeOut(_Out):
    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str
    unit_code: str
    makes: Decimal
    note: str | None
    is_active: bool
    lines: list[RecipeLineOut]


class CheckLineOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    unit_code: str
    needed: Decimal
    have: Decimal
    short: Decimal
    ok: bool


class CheckOut(BaseModel):
    recipe_id: uuid.UUID
    item_name: str
    unit_code: str
    quantity: Decimal
    can_make: bool
    lines: list[CheckLineOut]
    est_materials_cost: Decimal
    est_unit_cost: Decimal


# ------------------------------------------------------------ Make (production)
class ExtraCostIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="Example: Stitching labour")
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class ProductionIn(BaseModel):
    recipe_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3, description="How many to make")
    materials_warehouse_id: uuid.UUID | None = Field(default=None, description="Take materials from here. Empty = main warehouse")
    output_warehouse_id: uuid.UUID | None = Field(default=None, description="Put finished items here. Empty = main warehouse")
    extra_costs: list[ExtraCostIn] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=500)


class MaterialOut(_Out):
    item_id: uuid.UUID
    item_name: str
    unit_code: str
    quantity: Decimal
    unit_cost: Decimal
    line_cost: Decimal


class ExtraCostOut(_Out):
    name: str
    amount: Decimal


class ProductionOut(_Out):
    id: uuid.UUID
    number: str
    status: str
    recipe_id: uuid.UUID
    item_id: uuid.UUID
    item_name: str
    unit_code: str
    quantity: Decimal
    materials_warehouse_id: uuid.UUID
    materials_warehouse_name: str
    output_warehouse_id: uuid.UUID
    output_warehouse_name: str
    note: str | None
    materials_cost: Decimal
    extra_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    created_at: datetime
    materials: list[MaterialOut]
    extra_costs: list[ExtraCostOut]
