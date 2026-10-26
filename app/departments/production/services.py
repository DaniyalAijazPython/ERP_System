import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.departments.auth.models import User
from app.departments.inventory.models import Item
from app.departments.production.models import (
    ProductionExtraCost,
    ProductionMaterial,
    ProductionOrder,
    Recipe,
    RecipeLine,
)
from app.departments.production.schemas import ProductionIn, RecipeIn, RecipeLineIn, RecipeUpdateIn
from app.departments.stock.models import StockBalance
from app.departments.stock.services import _item, _move, _next_number, _warehouse, fmt
from app.shared.base import utcnow

D0 = Decimal("0")


def _r3(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------ Recipe
def _check_lines(db: Session, tenant_id: uuid.UUID, finished_id: uuid.UUID, lines: list[RecipeLineIn]) -> None:
    seen: set[uuid.UUID] = set()
    for i, line in enumerate(lines):
        field = f"lines.{i}.item_id"
        item = _item(db, tenant_id, line.item_id, field=field)
        if line.item_id == finished_id:
            raise Conflict("SAME_ITEM", "An item cannot be made out of itself", field=field)
        if line.item_id in seen:
            raise Conflict("DUPLICATE_MATERIAL", f"'{item.name}' is in the list two times. Use one line", field=field)
        seen.add(line.item_id)


def create_recipe(db: Session, tenant_id: uuid.UUID, data: RecipeIn) -> Recipe:
    finished = _item(db, tenant_id, data.item_id)
    old = db.scalar(select(Recipe.id).where(Recipe.tenant_id == tenant_id, Recipe.item_id == data.item_id))
    if old is not None:
        raise Conflict("RECIPE_EXISTS", f"'{finished.name}' already has a recipe. Change that one", field="item_id")
    _check_lines(db, tenant_id, data.item_id, data.lines)
    r = Recipe(tenant_id=tenant_id, item_id=data.item_id, makes=data.makes, note=(data.note or "").strip() or None)
    for pos, line in enumerate(data.lines):
        r.lines.append(RecipeLine(position=pos, item_id=line.item_id, quantity=line.quantity))
    db.add(r)
    db.flush()
    db.refresh(r)
    return r


def get_recipe(db: Session, tenant_id: uuid.UUID, rid: uuid.UUID) -> Recipe:
    r = db.scalar(select(Recipe).where(Recipe.id == rid, Recipe.tenant_id == tenant_id))
    if r is None:
        raise NotFound("RECIPE_NOT_FOUND", "That recipe does not exist")
    return r


def list_recipes(db: Session, tenant_id: uuid.UUID, include_inactive: bool) -> list[Recipe]:
    q = select(Recipe).join(Item, Item.id == Recipe.item_id).where(Recipe.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(Recipe.is_active.is_(True))
    return list(db.scalars(q.order_by(Item.name)))


def update_recipe(db: Session, tenant_id: uuid.UUID, rid: uuid.UUID, data: RecipeUpdateIn) -> Recipe:
    r = get_recipe(db, tenant_id, rid)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("makes") is not None:
        r.makes = changes["makes"]
    if "note" in changes:
        r.note = (changes["note"] or "").strip() or None
    if changes.get("is_active") is not None:
        r.is_active = changes["is_active"]
    if data.lines is not None:
        _check_lines(db, tenant_id, r.item_id, data.lines)
        r.lines.clear()
        db.flush()
        for pos, line in enumerate(data.lines):
            r.lines.append(RecipeLine(position=pos, item_id=line.item_id, quantity=line.quantity))
    db.flush()
    db.refresh(r)
    return r


# ------------------------------------------------------------ "Can I make this?"
def _needs(recipe: Recipe, quantity: Decimal) -> list[tuple[RecipeLine, Decimal]]:
    return [(l, _r3(l.quantity * quantity / recipe.makes)) for l in recipe.lines]


def _have(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID, warehouse_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    b = db.scalar(select(StockBalance).where(
        StockBalance.tenant_id == tenant_id, StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id))
    return (b.quantity, b.avg_cost) if b else (D0, D0)


def check_recipe(db: Session, tenant_id: uuid.UUID, rid: uuid.UUID, quantity: Decimal,
                 warehouse_id: uuid.UUID | None) -> dict:
    r = get_recipe(db, tenant_id, rid)
    wh = _warehouse(db, tenant_id, warehouse_id)
    rows, est = [], D0
    for line, needed in _needs(r, quantity):
        have, avg = _have(db, tenant_id, line.item_id, wh.id)
        short = max(needed - have, D0)
        est += needed * avg
        rows.append({"item_id": line.item_id, "item_name": line.item.name, "unit_code": line.item.unit.code,
                     "needed": needed, "have": have, "short": short, "ok": short == 0})
    return {
        "recipe_id": r.id, "item_name": r.item.name, "unit_code": r.item.unit.code, "quantity": quantity,
        "can_make": all(x["ok"] for x in rows), "lines": rows,
        "est_materials_cost": est.quantize(Decimal("0.01")),
        "est_unit_cost": (est / quantity).quantize(Decimal("0.0001")),
    }


# ------------------------------------------------------------ Make
def create_production(db: Session, user: User, data: ProductionIn, idem_key: str | None) -> ProductionOrder:
    tenant_id = user.tenant_id
    if idem_key:
        old = db.scalar(select(ProductionOrder).where(
            ProductionOrder.tenant_id == tenant_id, ProductionOrder.idempotency_key == idem_key))
        if old is not None:
            return old

    recipe = get_recipe(db, tenant_id, data.recipe_id)
    finished = recipe.item
    if not recipe.is_active:
        raise Conflict("RECIPE_OFF", f"The recipe for '{finished.name}' is switched off", field="recipe_id")
    if not finished.is_active:
        raise Conflict("ITEM_OFF", f"Item '{finished.name}' is switched off", field="recipe_id")
    mw = _warehouse(db, tenant_id, data.materials_warehouse_id)
    ow = _warehouse(db, tenant_id, data.output_warehouse_id)

    needs = _needs(recipe, data.quantity)
    short = []
    for line, needed in needs:
        have, _ = _have(db, tenant_id, line.item_id, mw.id)
        if have < needed:
            u = line.item.unit.code
            short.append(f"{line.item.name} (need {fmt(needed)} {u}, have {fmt(have)} {u})")
    if short:
        raise Conflict("NOT_ENOUGH_MATERIAL",
                       f"You cannot make {fmt(data.quantity)} {finished.name} yet. Short: " + "; ".join(short),
                       field="quantity")

    order = ProductionOrder(
        tenant_id=tenant_id, number=_next_number(db, tenant_id, "PD"), recipe_id=recipe.id, item_id=finished.id,
        quantity=data.quantity, materials_warehouse_id=mw.id, output_warehouse_id=ow.id,
        note=(data.note or "").strip() or None, idempotency_key=idem_key, created_by=user.id,
    )
    db.add(order)
    db.flush()

    materials_cost = D0
    for pos, (line, needed) in enumerate(needs):
        cost = _move(db, user, line.item, mw.id, -needed, "make_use", reference_number=order.number)
        order.materials.append(ProductionMaterial(position=pos, item_id=line.item_id, quantity=needed, unit_cost=cost))
        materials_cost += needed * cost
    extra = D0
    for pos, ec in enumerate(data.extra_costs):
        order.extra_costs.append(ProductionExtraCost(position=pos, name=ec.name.strip(), amount=ec.amount))
        extra += ec.amount

    total = (materials_cost + extra).quantize(Decimal("0.01"))
    unit_cost = (total / data.quantity).quantize(Decimal("0.0001"))
    order.materials_cost = materials_cost.quantize(Decimal("0.01"))
    order.extra_cost = extra.quantize(Decimal("0.01"))
    order.total_cost = total
    order.unit_cost = unit_cost
    _move(db, user, finished, ow.id, data.quantity, "make_done", unit_cost=unit_cost, reference_number=order.number)
    db.flush()
    db.refresh(order)
    return order


def get_production(db: Session, tenant_id: uuid.UUID, oid: uuid.UUID) -> ProductionOrder:
    o = db.scalar(select(ProductionOrder).where(ProductionOrder.id == oid, ProductionOrder.tenant_id == tenant_id))
    if o is None:
        raise NotFound("PRODUCTION_NOT_FOUND", "That production does not exist")
    return o


def list_production(db: Session, tenant_id: uuid.UUID, limit: int, offset: int):
    q = select(ProductionOrder).where(ProductionOrder.tenant_id == tenant_id)
    return list(db.scalars(q.order_by(ProductionOrder.created_at.desc()).limit(limit).offset(offset)))


def undo_production(db: Session, user: User, oid: uuid.UUID) -> ProductionOrder:
    """Takes the finished items out and puts the materials back at the cost they had."""
    o = get_production(db, user.tenant_id, oid)
    if o.status == "undone":
        raise Conflict("ALREADY_UNDONE", f"{o.number} was already undone")
    _move(db, user, o.item, o.output_warehouse_id, -o.quantity, "make_done_undone",
          reference_number=o.number, note=f"Undo of {o.number}")
    for m in o.materials:
        _move(db, user, m.item, o.materials_warehouse_id, m.quantity, "make_use_undone",
              unit_cost=m.unit_cost, reference_number=o.number, note=f"Undo of {o.number}")
    o.status = "undone"
    o.undone_at = utcnow()
    db.flush()
    return o
