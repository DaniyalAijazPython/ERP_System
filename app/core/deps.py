import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.departments.auth.models import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise Unauthorized("NOT_AUTHENTICATED", "Missing bearer token")
    try:
        payload = decode_token(creds.credentials, expected_type="access")
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise Unauthorized("INVALID_TOKEN", "Access token is invalid or expired")
    if user is None or not user.is_active or str(user.tenant_id) != payload.get("tid"):
        raise Unauthorized("INVALID_TOKEN", "Access token is invalid or expired")
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    """Dependency factory: allow only the listed roles (owner always passes)."""
    allowed = set(roles) | {"owner"}

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise Forbidden("FORBIDDEN", "Your role does not allow this action")
        return user

    return checker
