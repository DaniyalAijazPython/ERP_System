import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.departments.auth.models import User
from app.departments.production import services
from app.departments.production.schemas import (
    CheckOut,
    ProductionIn,
    ProductionOut,
    RecipeIn,
    RecipeOut,
    RecipeUpdateIn,
)

router = APIRouter(tags=["production"])

# Owner always passes. Everyone logged in can look.
recipe_writer = require_roles("manager", "production")
make_writer = require_roles("manager", "store", "production")


# ------------------------------------------------------------ Recipes
@router.post("/recipes", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(body: RecipeIn, user: User = Depends(recipe_writer), db: Session = Depends(get_db)):
    return services.create_recipe(db, user.tenant_id, body)


@router.get("/recipes", response_model=list[RecipeOut])
def list_recipes(include_inactive: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.list_recipes(db, user.tenant_id, include_inactive)


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.get_recipe(db, user.tenant_id, recipe_id)


@router.patch("/recipes/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: uuid.UUID, body: RecipeUpdateIn, user: User = Depends(recipe_writer),
                  db: Session = Depends(get_db)):
    return services.update_recipe(db, user.tenant_id, recipe_id, body)


@router.get("/recipes/{recipe_id}/check", response_model=CheckOut, summary="Can I make this?")
def can_i_make_this(
    recipe_id: uuid.UUID,
    quantity: Decimal = Query(gt=0, description="How many do you want to make?"),
    warehouse_id: uuid.UUID | None = Query(default=None, description="Where the materials are. Empty = main warehouse"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.check_recipe(db, user.tenant_id, recipe_id, quantity, warehouse_id)


# ------------------------------------------------------------ Make
@router.post("/production", response_model=ProductionOut, status_code=status.HTTP_201_CREATED,
             summary="Make items from a recipe")
def make_items(
    body: ProductionIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    user: User = Depends(make_writer),
    db: Session = Depends(get_db),
):
    return services.create_production(db, user, body, idempotency_key)


@router.get("/production", response_model=list[ProductionOut])
def list_production(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return services.list_production(db, user.tenant_id, limit, offset)


@router.get("/production/{production_id}", response_model=ProductionOut)
def get_production(production_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return services.get_production(db, user.tenant_id, production_id)


@router.post("/production/{production_id}/undo", response_model=ProductionOut)
def undo_production(production_id: uuid.UUID, user: User = Depends(make_writer), db: Session = Depends(get_db)):
    return services.undo_production(db, user, production_id)
