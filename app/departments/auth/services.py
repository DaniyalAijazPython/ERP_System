import uuid

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.departments.auth.models import Role, Tenant, User
from app.departments.auth.schemas import CreateUserIn, RegisterCompanyIn, TokenOut


def _normalize(email: str) -> str:
    return email.strip().lower()


def _issue_tokens(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.tenant_id),
        refresh_token=create_refresh_token(user.id, user.tenant_id),
    )


def _email_taken(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None


def register_company(db: Session, data: RegisterCompanyIn) -> tuple[Tenant, User]:
    email = _normalize(data.email)
    if _email_taken(db, email):
        raise Conflict("EMAIL_TAKEN", "An account with this email already exists", field="email")

    tenant = Tenant(name=data.company_name.strip(), base_currency=data.base_currency.upper())
    db.add(tenant)
    db.flush()
    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
        role=Role.owner.value,
    )
    db.add(user)
    db.flush()
    return tenant, user


def login(db: Session, email: str, password: str) -> TokenOut:
    user = db.scalar(select(User).where(User.email == _normalize(email)))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise Unauthorized("INVALID_CREDENTIALS", "Email or password is incorrect")
    return _issue_tokens(user)


def refresh(db: Session, refresh_token: str) -> TokenOut:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise Unauthorized("INVALID_TOKEN", "Refresh token is invalid or expired")
    if user is None or not user.is_active:
        raise Unauthorized("INVALID_TOKEN", "Refresh token is invalid or expired")
    return _issue_tokens(user)


def create_user(db: Session, tenant_id: uuid.UUID, data: CreateUserIn) -> User:
    email = _normalize(data.email)
    if _email_taken(db, email):
        raise Conflict("EMAIL_TAKEN", "An account with this email already exists", field="email")
    if data.role not in {r.value for r in Role} or data.role == Role.owner.value:
        raise Conflict("INVALID_ROLE", "Role must be one of manager, store, production, sales, viewer", field="role")
    user = User(
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
        role=data.role,
    )
    db.add(user)
    db.flush()
    return user


def list_users(db: Session, tenant_id: uuid.UUID) -> list[User]:
    return list(db.scalars(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)))
