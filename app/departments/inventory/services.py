import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.departments.inventory.models import Item, Party, PartyKind, Unit, Warehouse
from app.departments.inventory.schemas import (
    ItemIn,
    ItemUpdate,
    PartyIn,
    PartyUpdate,
    UnitIn,
    WarehouseIn,
    WarehouseUpdate,
)

DEFAULT_UNITS = [
    ("pcs", "Pieces"),
    ("kg", "Kilogram"),
    ("g", "Gram"),
    ("m", "Meter"),
    ("ltr", "Litre"),
    ("box", "Box"),
    ("bag", "Bag"),
]
CASH_SUPPLIER_NAME = "Local market (cash)"
DEFAULT_WAREHOUSE_NAME = "Main store"


def seed_tenant_defaults(db: Session, tenant_id: uuid.UUID) -> None:
    """Starter data so a new company can add its first item in one minute."""
    for code, name in DEFAULT_UNITS:
        db.add(Unit(tenant_id=tenant_id, code=code, name=name))
    db.add(Warehouse(tenant_id=tenant_id, name=DEFAULT_WAREHOUSE_NAME, is_default=True))
    db.add(Party(tenant_id=tenant_id, kind=PartyKind.supplier.value, name=CASH_SUPPLIER_NAME, is_system=True))
    db.flush()


# ---------------------------------------------------------------- units
def list_units(db: Session, tenant_id: uuid.UUID) -> list[Unit]:
    return list(db.scalars(select(Unit).where(Unit.tenant_id == tenant_id).order_by(Unit.code)))


def create_unit(db: Session, tenant_id: uuid.UUID, data: UnitIn) -> Unit:
    code = data.code.strip().lower()
    exists = db.scalar(select(Unit.id).where(Unit.tenant_id == tenant_id, Unit.code == code))
    if exists:
        raise Conflict("UNIT_EXISTS", f"You already have a unit called '{code}'", field="code")
    unit = Unit(tenant_id=tenant_id, code=code, name=data.name.strip())
    db.add(unit)
    db.flush()
    return unit


def _get_unit(db: Session, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> Unit:
    unit = db.scalar(select(Unit).where(Unit.id == unit_id, Unit.tenant_id == tenant_id))
    if unit is None:
        raise NotFound("UNIT_NOT_FOUND", "That unit does not exist", field="unit_id")
    return unit


# ---------------------------------------------------------------- items
def _sku_taken(db: Session, tenant_id: uuid.UUID, sku: str, exclude: uuid.UUID | None = None) -> bool:
    q = select(Item.id).where(Item.tenant_id == tenant_id, Item.sku == sku)
    if exclude:
        q = q.where(Item.id != exclude)
    return db.scalar(q) is not None


def create_item(db: Session, tenant_id: uuid.UUID, data: ItemIn) -> Item:
    sku = data.sku.strip().upper()
    if _sku_taken(db, tenant_id, sku):
        raise Conflict("SKU_EXISTS", f"Item code '{sku}' is already used", field="sku")
    _get_unit(db, tenant_id, data.unit_id)
    item = Item(
        tenant_id=tenant_id,
        sku=sku,
        name=data.name.strip(),
        item_type=data.item_type.value,
        unit_id=data.unit_id,
        sale_price=data.sale_price,
        reorder_level=data.reorder_level,
    )
    db.add(item)
    db.flush()
    db.refresh(item)
    return item


def get_item(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID) -> Item:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.tenant_id == tenant_id))
    if item is None:
        raise NotFound("ITEM_NOT_FOUND", "That item does not exist")
    return item


def list_items(
    db: Session,
    tenant_id: uuid.UUID,
    q: str | None,
    item_type: str | None,
    include_inactive: bool,
    limit: int,
    offset: int,
) -> tuple[list[Item], int]:
    where = [Item.tenant_id == tenant_id]
    if not include_inactive:
        where.append(Item.is_active.is_(True))
    if item_type:
        where.append(Item.item_type == item_type)
    if q:
        like = f"%{q.strip()}%"
        where.append(or_(Item.name.ilike(like), Item.sku.ilike(like)))
    total = db.scalar(select(func.count()).select_from(Item).where(*where)) or 0
    rows = db.scalars(select(Item).where(*where).order_by(Item.name).limit(limit).offset(offset))
    return list(rows), total


def update_item(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID, data: ItemUpdate) -> Item:
    item = get_item(db, tenant_id, item_id)
    changes = data.model_dump(exclude_unset=True)
    if "sku" in changes and changes["sku"] is not None:
        sku = changes["sku"].strip().upper()
        if _sku_taken(db, tenant_id, sku, exclude=item.id):
            raise Conflict("SKU_EXISTS", f"Item code '{sku}' is already used", field="sku")
        item.sku = sku
    if "name" in changes and changes["name"] is not None:
        item.name = changes["name"].strip()
    if "item_type" in changes and changes["item_type"] is not None:
        item.item_type = changes["item_type"].value
    if "unit_id" in changes and changes["unit_id"] is not None:
        _get_unit(db, tenant_id, changes["unit_id"])
        item.unit_id = changes["unit_id"]
    if "sale_price" in changes:
        item.sale_price = changes["sale_price"]
    if "reorder_level" in changes and changes["reorder_level"] is not None:
        item.reorder_level = changes["reorder_level"]
    if "is_active" in changes and changes["is_active"] is not None:
        item.is_active = changes["is_active"]
    db.flush()
    db.refresh(item)
    return item


# ----------------------------------------------------------- warehouses
def list_warehouses(db: Session, tenant_id: uuid.UUID) -> list[Warehouse]:
    return list(db.scalars(select(Warehouse).where(Warehouse.tenant_id == tenant_id).order_by(Warehouse.name)))


def _get_warehouse(db: Session, tenant_id: uuid.UUID, wid: uuid.UUID) -> Warehouse:
    w = db.scalar(select(Warehouse).where(Warehouse.id == wid, Warehouse.tenant_id == tenant_id))
    if w is None:
        raise NotFound("WAREHOUSE_NOT_FOUND", "That warehouse does not exist")
    return w


def _clear_default(db: Session, tenant_id: uuid.UUID, keep: uuid.UUID | None = None) -> None:
    for w in db.scalars(select(Warehouse).where(Warehouse.tenant_id == tenant_id, Warehouse.is_default.is_(True))):
        if w.id != keep:
            w.is_default = False


def _warehouse_name_taken(db: Session, tenant_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
    q = select(Warehouse.id).where(Warehouse.tenant_id == tenant_id, Warehouse.name == name)
    if exclude:
        q = q.where(Warehouse.id != exclude)
    return db.scalar(q) is not None


def create_warehouse(db: Session, tenant_id: uuid.UUID, data: WarehouseIn) -> Warehouse:
    name = data.name.strip()
    if _warehouse_name_taken(db, tenant_id, name):
        raise Conflict("WAREHOUSE_EXISTS", f"You already have a warehouse called '{name}'", field="name")
    if data.is_default:
        _clear_default(db, tenant_id)
    w = Warehouse(tenant_id=tenant_id, name=name, is_default=data.is_default)
    db.add(w)
    db.flush()
    return w


def update_warehouse(db: Session, tenant_id: uuid.UUID, wid: uuid.UUID, data: WarehouseUpdate) -> Warehouse:
    w = _get_warehouse(db, tenant_id, wid)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        name = changes["name"].strip()
        if _warehouse_name_taken(db, tenant_id, name, exclude=w.id):
            raise Conflict("WAREHOUSE_EXISTS", f"You already have a warehouse called '{name}'", field="name")
        w.name = name
    if changes.get("is_default") is True:
        _clear_default(db, tenant_id, keep=w.id)
        w.is_default = True
    elif changes.get("is_default") is False and w.is_default:
        raise Conflict("DEFAULT_REQUIRED", "Choose another warehouse as the default first", field="is_default")
    if changes.get("is_active") is False and w.is_default:
        raise Conflict("DEFAULT_REQUIRED", "The default warehouse cannot be switched off", field="is_active")
    if changes.get("is_active") is not None:
        w.is_active = changes["is_active"]
    db.flush()
    return w


# -------------------------------------------------------------- parties
def list_parties(db: Session, tenant_id: uuid.UUID, kind: str, q: str | None, include_inactive: bool) -> list[Party]:
    where = [Party.tenant_id == tenant_id, Party.kind == kind]
    if not include_inactive:
        where.append(Party.is_active.is_(True))
    if q:
        where.append(Party.name.ilike(f"%{q.strip()}%"))
    return list(db.scalars(select(Party).where(*where).order_by(Party.name)))


def _party_name_taken(db: Session, tenant_id: uuid.UUID, kind: str, name: str, exclude: uuid.UUID | None = None) -> bool:
    q = select(Party.id).where(Party.tenant_id == tenant_id, Party.kind == kind, Party.name == name)
    if exclude:
        q = q.where(Party.id != exclude)
    return db.scalar(q) is not None


def create_party(db: Session, tenant_id: uuid.UUID, kind: str, data: PartyIn) -> Party:
    name = data.name.strip()
    if _party_name_taken(db, tenant_id, kind, name):
        raise Conflict("PARTY_EXISTS", f"You already have a {kind} called '{name}'", field="name")
    p = Party(tenant_id=tenant_id, kind=kind, name=name, phone=data.phone, address=data.address)
    db.add(p)
    db.flush()
    return p


def update_party(db: Session, tenant_id: uuid.UUID, kind: str, pid: uuid.UUID, data: PartyUpdate) -> Party:
    p = db.scalar(select(Party).where(Party.id == pid, Party.tenant_id == tenant_id, Party.kind == kind))
    if p is None:
        raise NotFound("PARTY_NOT_FOUND", f"That {kind} does not exist")
    if p.is_system:
        raise Conflict("SYSTEM_RECORD", f"'{p.name}' is built in and cannot be changed")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        name = changes["name"].strip()
        if _party_name_taken(db, tenant_id, kind, name, exclude=p.id):
            raise Conflict("PARTY_EXISTS", f"You already have a {kind} called '{name}'", field="name")
        p.name = name
    for f in ("phone", "address"):
        if f in changes:
            setattr(p, f, changes[f])
    if changes.get("is_active") is not None:
        p.is_active = changes["is_active"]
    db.flush()
    return p
