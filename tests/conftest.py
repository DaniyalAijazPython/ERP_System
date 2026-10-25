import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from main import create_app
from app.shared.base import Base


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    engine.dispose()


COMPANY = {
    "company_name": "Karachi Steel Works",
    "full_name": "Ayesha Khan",
    "email": "Owner@Example.com",
    "password": "s3cret-pass",
}


@pytest.fixture()
def owner_tokens(client):
    r = client.post("/api/v1/auth/register-company", json=COMPANY)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def owner_headers(owner_tokens):
    return {"Authorization": f"Bearer {owner_tokens['access_token']}"}
