import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.modules.inventory import services
from app.modules.inventory.models import ItemType, PartyKind
from app.modules.inventory.schemas import (
    ItemIn,
    ItemOut,
    ItemPage,
    ItemUpdate,
    PartyIn,
    PartyOut,
    PartyUpdate,
    UnitIn,
    UnitOut,
    WarehouseIn,
    WarehouseOut,
    WarehouseUpdate,
)
from app.modules.auth.models import User

router = APIRouter(tags=["inventory"])

# Owner always passes (see require_roles). Reading is open to every logged-in user.
store_writer = require_roles("manager", "store")
sales_writer = require_roles("manager", "sales")


# ---------------------------------------------------------------- units
@router.get("/units", response_model=list[UnitOut])
def list_units(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.list_units(db, user.tenant_id)


@router.post("/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED)
def create_unit(body: UnitIn, user: User = Depends(store_writer), db: Session = Depends(get_db)):
    return services.create_unit(db, user.tenant_id, body)


# ---------------------------------------------------------------- items
@router.get("/items", response_model=ItemPage)
def list_items(
    q: str | None = Query(default=None, description="Search name or item code"),
    item_type: ItemType | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows, total = services.list_items(
        db, user.tenant_id, q, item_type.value if item_type else None, include_inactive, limit, offset
    )
    return ItemPage(items=rows, total=total, limit=limit, offset=offset)


@router.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def create_item(body: ItemIn, user: User = Depends(store_writer), db: Session = Depends(get_db)):
    return services.create_item(db, user.tenant_id, body)


@router.get("/items/{item_id}", response_model=ItemOut)
def get_item(item_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.get_item(db, user.tenant_id, item_id)


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(item_id: uuid.UUID, body: ItemUpdate, user: User = Depends(store_writer), db: Session = Depends(get_db)):
    return services.update_item(db, user.tenant_id, item_id, body)


# ----------------------------------------------------------- warehouses
@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.list_warehouses(db, user.tenant_id)


@router.post("/warehouses", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED)
def create_warehouse(body: WarehouseIn, user: User = Depends(store_writer), db: Session = Depends(get_db)):
    return services.create_warehouse(db, user.tenant_id, body)


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut)
def update_warehouse(
    warehouse_id: uuid.UUID, body: WarehouseUpdate, user: User = Depends(store_writer), db: Session = Depends(get_db)
):
    return services.update_warehouse(db, user.tenant_id, warehouse_id, body)


# ------------------------------------------------ suppliers & customers
def _register_party_routes(kind: PartyKind, plural: str, writer) -> None:
    @router.get(f"/{plural}", response_model=list[PartyOut], name=f"list_{plural}")
    def _list(
        q: str | None = None,
        include_inactive: bool = False,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        return services.list_parties(db, user.tenant_id, kind.value, q, include_inactive)

    @router.post(f"/{plural}", response_model=PartyOut, status_code=status.HTTP_201_CREATED, name=f"create_{kind.value}")
    def _create(body: PartyIn, user: User = Depends(writer), db: Session = Depends(get_db)):
        return services.create_party(db, user.tenant_id, kind.value, body)

    @router.patch(f"/{plural}/{{party_id}}", response_model=PartyOut, name=f"update_{kind.value}")
    def _update(party_id: uuid.UUID, body: PartyUpdate, user: User = Depends(writer), db: Session = Depends(get_db)):
        return services.update_party(db, user.tenant_id, kind.value, party_id, body)


_register_party_routes(PartyKind.supplier, "suppliers", store_writer)
_register_party_routes(PartyKind.customer, "customers", sales_writer)
