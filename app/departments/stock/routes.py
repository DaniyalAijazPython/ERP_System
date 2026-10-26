import uuid

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.departments.auth.models import User
from app.departments.stock import services
from app.departments.stock.schemas import (
    MovementOut,
    StockFixIn,
    StockInIn,
    StockInOut,
    StockMoveIn,
    StockMoveOut,
    StockOutIn,
    StockOutOut,
    StockPage,
)

router = APIRouter(tags=["stock"])

# Owner always passes. Everyone logged in can look.
store_writer = require_roles("manager", "store")
# Production staff can also take stock out for production
stock_out_writer = require_roles("manager", "store", "production")


@router.post("/stock-in", response_model=StockInOut, status_code=status.HTTP_201_CREATED)
def create_stock_in(
    body: StockInIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    user: User = Depends(store_writer),
    db: Session = Depends(get_db),
):
    return services.create_stock_in(db, user, body, idempotency_key)


@router.get("/stock-in", response_model=list[StockInOut])
def list_stock_in(
    supplier_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_stock_in(db, user.tenant_id, supplier_id, limit, offset)


@router.get("/stock-in/{stock_in_id}", response_model=StockInOut)
def get_stock_in(stock_in_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.get_stock_in(db, user.tenant_id, stock_in_id)


@router.post("/stock-in/{stock_in_id}/undo", response_model=StockInOut)
def undo_stock_in(stock_in_id: uuid.UUID, user: User = Depends(store_writer), db: Session = Depends(get_db)):
    return services.undo_stock_in(db, user, stock_in_id)


@router.get("/stock", response_model=StockPage, summary="How much stock do I have?")
def how_much_stock(
    q: str | None = Query(default=None, description="Search name or item code"),
    warehouse_id: uuid.UUID | None = None,
    low_only: bool = Query(default=False, description="Show only items that are running low"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = services.stock_rows(db, user.tenant_id, q, warehouse_id, low_only)
    return StockPage(items=rows[offset: offset + limit], total=len(rows), limit=limit, offset=offset)


@router.get("/stock-history", response_model=list[MovementOut], summary="Every stock change, newest first")
def stock_history(
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_movements(db, user.tenant_id, item_id, warehouse_id, limit, offset)


@router.post("/stock-fix", response_model=MovementOut, status_code=status.HTTP_201_CREATED,
             summary="Fix the stock count")
def fix_stock_count(body: StockFixIn, user: User = Depends(store_writer), db: Session = Depends(get_db)):
    return services.fix_count(db, user, body)


# ------------------------------------------------------------ Stock Out
@router.post("/stock-out", response_model=StockOutOut, status_code=status.HTTP_201_CREATED)
def create_stock_out(
    body: StockOutIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    user: User = Depends(stock_out_writer),
    db: Session = Depends(get_db),
):
    return services.create_stock_out(db, user, body, idempotency_key)


@router.get("/stock-out", response_model=list[StockOutOut])
def list_stock_out(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_stock_out(db, user.tenant_id, limit, offset)


@router.get("/stock-out/{stock_out_id}", response_model=StockOutOut)
def get_stock_out(stock_out_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.get_stock_out(db, user.tenant_id, stock_out_id)


@router.post("/stock-out/{stock_out_id}/undo", response_model=StockOutOut)
def undo_stock_out(stock_out_id: uuid.UUID, user: User = Depends(stock_out_writer), db: Session = Depends(get_db)):
    return services.undo_stock_out(db, user, stock_out_id)


# ------------------------------------------------------------ Move stock
@router.post("/stock-move", response_model=StockMoveOut, status_code=status.HTTP_201_CREATED,
             summary="Move stock to another warehouse")
def create_stock_move(
    body: StockMoveIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    user: User = Depends(store_writer),
    db: Session = Depends(get_db),
):
    return services.create_stock_move(db, user, body, idempotency_key)


@router.get("/stock-move", response_model=list[StockMoveOut])
def list_stock_moves(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_stock_moves(db, user.tenant_id, limit, offset)


@router.get("/stock-move/{stock_move_id}", response_model=StockMoveOut)
def get_stock_move(stock_move_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.get_stock_move(db, user.tenant_id, stock_move_id)
