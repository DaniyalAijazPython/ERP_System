import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.departments.auth.models import User
from app.departments.inventory.models import Item, Party, PartyKind, Warehouse
from app.departments.stock.models import (
    DocCounter,
    GoodsReceipt,
    GoodsReceiptLine,
    StockBalance,
    StockMove,
    StockMoveLine,
    StockMovement,
    StockOut,
    StockOutLine,
)
from app.departments.stock.schemas import StockFixIn, StockInIn, StockMoveIn, StockOutIn
from app.shared.base import utcnow

CASH_SUPPLIER_NAME = "Local market (cash)"


def fmt(n: Decimal) -> str:
    """40.000 -> '40', 2.500 -> '2.5'"""
    return format(Decimal(n).normalize(), "f")


# ------------------------------------------------------------ small helpers
def _next_number(db: Session, tenant_id: uuid.UUID, key: str) -> str:
    row = db.scalar(select(DocCounter).where(DocCounter.tenant_id == tenant_id, DocCounter.key == key).with_for_update())
    if row is None:
        row = DocCounter(tenant_id=tenant_id, key=key, last_number=0)
        db.add(row)
        db.flush()
    row.last_number += 1
    db.flush()
    return f"{key}-{row.last_number:04d}"


def _warehouse(db: Session, tenant_id: uuid.UUID, wid: uuid.UUID | None) -> Warehouse:
    if wid is None:
        w = db.scalar(select(Warehouse).where(
            Warehouse.tenant_id == tenant_id, Warehouse.is_default.is_(True), Warehouse.is_active.is_(True)))
        if w is None:
            raise Conflict("NO_WAREHOUSE", "Please add a warehouse first", field="warehouse_id")
        return w
    w = db.scalar(select(Warehouse).where(Warehouse.id == wid, Warehouse.tenant_id == tenant_id))
    if w is None:
        raise NotFound("WAREHOUSE_NOT_FOUND", "That warehouse does not exist", field="warehouse_id")
    if not w.is_active:
        raise Conflict("WAREHOUSE_OFF", f"Warehouse '{w.name}' is switched off", field="warehouse_id")
    return w


def _supplier(db: Session, tenant_id: uuid.UUID, sid: uuid.UUID | None) -> Party:
    if sid is None:
        p = db.scalar(select(Party).where(
            Party.tenant_id == tenant_id, Party.kind == PartyKind.supplier.value, Party.name == CASH_SUPPLIER_NAME))
        if p is None:
            raise Conflict("NO_SUPPLIER", "Please choose a supplier", field="supplier_id")
        return p
    p = db.scalar(select(Party).where(
        Party.id == sid, Party.tenant_id == tenant_id, Party.kind == PartyKind.supplier.value))
    if p is None:
        raise NotFound("SUPPLIER_NOT_FOUND", "That supplier does not exist", field="supplier_id")
    if not p.is_active:
        raise Conflict("SUPPLIER_OFF", f"Supplier '{p.name}' is switched off", field="supplier_id")
    return p


def _item(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID, field: str = "item_id") -> Item:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.tenant_id == tenant_id))
    if item is None:
        raise NotFound("ITEM_NOT_FOUND", "That item does not exist", field=field)
    return item


def _balance(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID, warehouse_id: uuid.UUID) -> StockBalance:
    """Get the stock row and lock it, so two people cannot change it at the same moment."""
    b = db.scalar(select(StockBalance).where(
        StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id).with_for_update())
    if b is None:
        b = StockBalance(tenant_id=tenant_id, item_id=item_id, warehouse_id=warehouse_id,
                         quantity=Decimal("0"), avg_cost=Decimal("0"))
        db.add(b)
        db.flush()
    return b


# Kinds that bring stock in at a known cost (cost average is worked out again)
COST_IN_KINDS = {"stock_in", "stock_out_undone", "move_in"}
# Kinds that take stock out at the current average cost
COST_OUT_KINDS = {"stock_out", "move_out"}


def _move(
    db: Session,
    user: User,
    item: Item,
    warehouse_id: uuid.UUID,
    change: Decimal,
    kind: str,
    unit_cost: Decimal | None = None,
    reference_number: str | None = None,
    note: str | None = None,
) -> Decimal:
    """The ONE place where stock goes up or down. Returns the cost per unit used."""
    b = _balance(db, user.tenant_id, item.id, warehouse_id)
    new_qty = b.quantity + change
    if new_qty < 0:
        raise Conflict(
            "NOT_ENOUGH_STOCK",
            f"Not enough {item.name}: you have {fmt(b.quantity)} {item.unit.code}, you need {fmt(-change)} {item.unit.code}",
            field="quantity",
        )
    if change < 0 and kind in COST_OUT_KINDS:
        unit_cost = b.avg_cost  # stock leaves at what it cost us on average
    if kind in COST_IN_KINDS and unit_cost is not None and change > 0:
        value = b.quantity * b.avg_cost + change * unit_cost
        b.avg_cost = (value / new_qty).quantize(Decimal("0.0001"))
    b.quantity = new_qty
    db.add(StockMovement(
        tenant_id=user.tenant_id, item_id=item.id, warehouse_id=warehouse_id, quantity=change,
        unit_cost=unit_cost, kind=kind, reference_number=reference_number, note=note, created_by=user.id,
    ))
    db.flush()
    return unit_cost if unit_cost is not None else Decimal("0")


# ------------------------------------------------------------ Stock In
def create_stock_in(db: Session, user: User, data: StockInIn, idem_key: str | None) -> GoodsReceipt:
    tenant_id = user.tenant_id
    if idem_key:
        old = db.scalar(select(GoodsReceipt).where(
            GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.idempotency_key == idem_key))
        if old is not None:  # same request sent twice (bad network): give back the first answer
            return old

    supplier = _supplier(db, tenant_id, data.supplier_id)
    warehouse = _warehouse(db, tenant_id, data.warehouse_id)

    items: dict[uuid.UUID, Item] = {}
    for i, line in enumerate(data.lines):
        item = items.get(line.item_id) or _item(db, tenant_id, line.item_id, field=f"lines.{i}.item_id")
        if not item.is_active:
            raise Conflict("ITEM_OFF", f"Item '{item.name}' is switched off", field=f"lines.{i}.item_id")
        items[line.item_id] = item

    receipt = GoodsReceipt(
        tenant_id=tenant_id,
        number=_next_number(db, tenant_id, "GR"),
        supplier_id=supplier.id,
        warehouse_id=warehouse.id,
        payment_method=data.payment_method.value,
        supplier_invoice_no=(data.supplier_invoice_no or "").strip() or None,
        tax_amount=data.tax_amount,
        note=(data.note or "").strip() or None,
        idempotency_key=idem_key,
        created_by=user.id,
    )
    for pos, line in enumerate(data.lines):
        receipt.lines.append(GoodsReceiptLine(
            position=pos, item_id=line.item_id, quantity=line.quantity, unit_price=line.unit_price))
    db.add(receipt)
    db.flush()

    for line in data.lines:
        _move(db, user, items[line.item_id], warehouse.id, line.quantity, "stock_in",
              unit_cost=line.unit_price, reference_number=receipt.number)
    db.refresh(receipt)
    return receipt


def get_stock_in(db: Session, tenant_id: uuid.UUID, rid: uuid.UUID) -> GoodsReceipt:
    r = db.scalar(select(GoodsReceipt).where(GoodsReceipt.id == rid, GoodsReceipt.tenant_id == tenant_id))
    if r is None:
        raise NotFound("STOCK_IN_NOT_FOUND", "That Stock In does not exist")
    return r


def list_stock_in(db: Session, tenant_id: uuid.UUID, supplier_id: uuid.UUID | None, limit: int, offset: int):
    q = select(GoodsReceipt).where(GoodsReceipt.tenant_id == tenant_id)
    if supplier_id:
        q = q.where(GoodsReceipt.supplier_id == supplier_id)
    return list(db.scalars(q.order_by(GoodsReceipt.created_at.desc()).limit(limit).offset(offset)))


def undo_stock_in(db: Session, user: User, rid: uuid.UUID) -> GoodsReceipt:
    """A Stock In is never deleted. To fix a mistake we take the same stock back out and say so in the history."""
    r = get_stock_in(db, user.tenant_id, rid)
    if r.status == "undone":
        raise Conflict("ALREADY_UNDONE", f"{r.number} was already undone")
    for line in r.lines:
        _move(db, user, line.item, r.warehouse_id, -line.quantity, "stock_in_undone",
              reference_number=r.number, note=f"Undo of {r.number}")
    r.status = "undone"
    r.undone_at = utcnow()
    db.flush()
    return r


# ------------------------------------------------------------ How much stock
def stock_rows(db: Session, tenant_id: uuid.UUID, q: str | None, warehouse_id: uuid.UUID | None, low_only: bool):
    iq = select(Item).where(Item.tenant_id == tenant_id, Item.is_active.is_(True)).order_by(Item.name)
    if q:
        like = f"%{q.strip()}%"
        iq = iq.where(Item.name.ilike(like) | Item.sku.ilike(like))
    items = list(db.scalars(iq))

    bq = select(StockBalance).where(StockBalance.tenant_id == tenant_id)
    if warehouse_id:
        bq = bq.where(StockBalance.warehouse_id == warehouse_id)
    by_item: dict[uuid.UUID, list[StockBalance]] = {}
    for b in db.scalars(bq):
        by_item.setdefault(b.item_id, []).append(b)

    rows = []
    for it in items:
        bs = by_item.get(it.id, [])
        qty = sum((b.quantity for b in bs), Decimal("0"))
        value = sum((b.quantity * b.avg_cost for b in bs), Decimal("0"))
        avg = (value / qty).quantize(Decimal("0.0001")) if qty > 0 else Decimal("0")
        low = it.reorder_level > 0 and qty <= it.reorder_level
        if low_only and not low:
            continue
        rows.append({
            "item_id": it.id, "sku": it.sku, "name": it.name, "unit_code": it.unit.code,
            "quantity": qty, "avg_cost": avg, "stock_value": value.quantize(Decimal("0.01")),
            "reorder_level": it.reorder_level, "is_low": low,
        })
    return rows


def list_movements(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID | None,
                   warehouse_id: uuid.UUID | None, limit: int, offset: int) -> list[StockMovement]:
    q = select(StockMovement).where(StockMovement.tenant_id == tenant_id)
    if item_id:
        q = q.where(StockMovement.item_id == item_id)
    if warehouse_id:
        q = q.where(StockMovement.warehouse_id == warehouse_id)
    return list(db.scalars(q.order_by(StockMovement.created_at.desc(), StockMovement.id).limit(limit).offset(offset)))


# ------------------------------------------------------------ Fix stock count
def fix_count(db: Session, user: User, data: StockFixIn) -> StockMovement:
    item = _item(db, user.tenant_id, data.item_id)
    warehouse = _warehouse(db, user.tenant_id, data.warehouse_id)
    b = _balance(db, user.tenant_id, item.id, warehouse.id)
    change = data.counted_quantity - b.quantity
    if change == 0:
        raise Conflict("COUNT_IS_SAME", f"You already have {fmt(b.quantity)} {item.unit.code} of {item.name}",
                       field="counted_quantity")
    _move(db, user, item, warehouse.id, change, "count_fix", note=data.reason.strip())
    return db.scalar(select(StockMovement).where(
        StockMovement.tenant_id == user.tenant_id, StockMovement.item_id == item.id
    ).order_by(StockMovement.created_at.desc()).limit(1))


# ------------------------------------------------------------ Stock Out
def _active_items(db: Session, tenant_id: uuid.UUID, lines) -> dict[uuid.UUID, Item]:
    items: dict[uuid.UUID, Item] = {}
    for i, line in enumerate(lines):
        item = items.get(line.item_id) or _item(db, tenant_id, line.item_id, field=f"lines.{i}.item_id")
        if not item.is_active:
            raise Conflict("ITEM_OFF", f"Item '{item.name}' is switched off", field=f"lines.{i}.item_id")
        items[line.item_id] = item
    return items


def create_stock_out(db: Session, user: User, data: StockOutIn, idem_key: str | None) -> StockOut:
    tenant_id = user.tenant_id
    if idem_key:
        old = db.scalar(select(StockOut).where(StockOut.tenant_id == tenant_id, StockOut.idempotency_key == idem_key))
        if old is not None:
            return old
    note = (data.note or "").strip() or None
    if data.reason.value == "other" and not note:
        raise Conflict("NOTE_NEEDED", "Please write why the stock is going out", field="note")
    warehouse = _warehouse(db, tenant_id, data.warehouse_id)
    items = _active_items(db, tenant_id, data.lines)

    out = StockOut(
        tenant_id=tenant_id, number=_next_number(db, tenant_id, "SO"), warehouse_id=warehouse.id,
        reason=data.reason.value, note=note, idempotency_key=idem_key, created_by=user.id,
    )
    db.add(out)
    db.flush()
    for pos, line in enumerate(data.lines):
        cost = _move(db, user, items[line.item_id], warehouse.id, -line.quantity, "stock_out",
                     reference_number=out.number, note=note)
        out.lines.append(StockOutLine(position=pos, item_id=line.item_id, quantity=line.quantity, unit_cost=cost))
    db.flush()
    db.refresh(out)
    return out


def get_stock_out(db: Session, tenant_id: uuid.UUID, oid: uuid.UUID) -> StockOut:
    o = db.scalar(select(StockOut).where(StockOut.id == oid, StockOut.tenant_id == tenant_id))
    if o is None:
        raise NotFound("STOCK_OUT_NOT_FOUND", "That Stock Out does not exist")
    return o


def list_stock_out(db: Session, tenant_id: uuid.UUID, limit: int, offset: int):
    q = select(StockOut).where(StockOut.tenant_id == tenant_id)
    return list(db.scalars(q.order_by(StockOut.created_at.desc()).limit(limit).offset(offset)))


def undo_stock_out(db: Session, user: User, oid: uuid.UUID) -> StockOut:
    """Puts the stock back at the same cost it left with. The history keeps both rows."""
    o = get_stock_out(db, user.tenant_id, oid)
    if o.status == "undone":
        raise Conflict("ALREADY_UNDONE", f"{o.number} was already undone")
    for line in o.lines:
        _move(db, user, line.item, o.warehouse_id, line.quantity, "stock_out_undone",
              unit_cost=line.unit_cost, reference_number=o.number, note=f"Undo of {o.number}")
    o.status = "undone"
    o.undone_at = utcnow()
    db.flush()
    return o


# ------------------------------------------------------------ Move stock
def create_stock_move(db: Session, user: User, data: StockMoveIn, idem_key: str | None) -> StockMove:
    tenant_id = user.tenant_id
    if idem_key:
        old = db.scalar(select(StockMove).where(StockMove.tenant_id == tenant_id, StockMove.idempotency_key == idem_key))
        if old is not None:
            return old
    if data.from_warehouse_id == data.to_warehouse_id:
        raise Conflict("SAME_WAREHOUSE", "Choose two different warehouses", field="to_warehouse_id")
    src = _warehouse(db, tenant_id, data.from_warehouse_id)
    dst = _warehouse(db, tenant_id, data.to_warehouse_id)
    items = _active_items(db, tenant_id, data.lines)

    mv = StockMove(
        tenant_id=tenant_id, number=_next_number(db, tenant_id, "MV"), from_warehouse_id=src.id,
        to_warehouse_id=dst.id, note=(data.note or "").strip() or None, idempotency_key=idem_key, created_by=user.id,
    )
    db.add(mv)
    db.flush()
    for pos, line in enumerate(data.lines):
        item = items[line.item_id]
        cost = _move(db, user, item, src.id, -line.quantity, "move_out",
                     reference_number=mv.number, note=f"To {dst.name}")
        _move(db, user, item, dst.id, line.quantity, "move_in", unit_cost=cost,
              reference_number=mv.number, note=f"From {src.name}")
        mv.lines.append(StockMoveLine(position=pos, item_id=line.item_id, quantity=line.quantity, unit_cost=cost))
    db.flush()
    db.refresh(mv)
    return mv


def get_stock_move(db: Session, tenant_id: uuid.UUID, mid: uuid.UUID) -> StockMove:
    m = db.scalar(select(StockMove).where(StockMove.id == mid, StockMove.tenant_id == tenant_id))
    if m is None:
        raise NotFound("STOCK_MOVE_NOT_FOUND", "That stock move does not exist")
    return m


def list_stock_moves(db: Session, tenant_id: uuid.UUID, limit: int, offset: int):
    q = select(StockMove).where(StockMove.tenant_id == tenant_id)
    return list(db.scalars(q.order_by(StockMove.created_at.desc()).limit(limit).offset(offset)))
