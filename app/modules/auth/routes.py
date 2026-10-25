from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.modules.auth import services
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    CreateUserIn,
    LoginIn,
    RefreshIn,
    RegisterCompanyIn,
    TenantOut,
    TokenOut,
    UserOut,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/register-company", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register_company(body: RegisterCompanyIn, db: Session = Depends(get_db)) -> TokenOut:
    _, user = services.register_company(db, body)
    return services.login(db, user.email, body.password)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    return services.login(db, body.email, body.password)


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    return services.refresh(db, body.refresh_token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/tenant", response_model=TenantOut)
def tenant(user: User = Depends(get_current_user)):
    return user.tenant


@router.get("/users", response_model=list[UserOut])
def list_users(user: User = Depends(require_roles("manager")), db: Session = Depends(get_db)):
    return services.list_users(db, user.tenant_id)


@router.post("/create_users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserIn, user: User = Depends(require_roles("manager")), db: Session = Depends(get_db)):
    return services.create_user(db, user.tenant_id, body)
