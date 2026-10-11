import os
import tempfile
import pytest
from app import create_app
from app.db import get_connection


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
        for ext in ["-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.remove(path + ext)
    except Exception:
        pass


@pytest.fixture
def app(temp_db):
    test_config = {
        "TESTING": True,
        "DB_PATH": temp_db,
        "SECRET_KEY": "test-secret-key-super-secure-123",
        "IP_HMAC_SECRET": "test-ip-hmac-secret-456",
        "IP_HMAC_KEY_VERSION": "v1",
        "DEFAULT_TIMEZONE": "Asia/Kolkata",
    }
    app = create_app(test_config)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """Client with authenticated admin session."""
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"
        sess["csrf_token"] = "test-csrf-token"
    return client
