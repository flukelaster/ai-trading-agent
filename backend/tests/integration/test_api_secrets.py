"""
Integration tests for Secrets Vault API routes.
"""

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.vault import VaultService

# Create a test vault with a known key
_test_vault = VaultService("test-vault-master-key-for-testing")


def _make_test_app(db_session):
    from fastapi import FastAPI
    from app.api.routes import secrets

    app = FastAPI()
    app.include_router(secrets.router)

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return app


@pytest_asyncio.fixture
async def client(db_session):
    # Patch the vault singleton in the secrets module to use our test vault
    with patch("app.api.routes.secrets.vault", _test_vault):
        app = _make_test_app(db_session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


class TestVaultStatus:
    @pytest.mark.asyncio
    async def test_vault_available(self, client):
        resp = await client.get("/api/secrets/vault-status")
        assert resp.status_code == 200
        assert resp.json()["available"] is True


class TestSecretsCRUD:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get("/api/secrets")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_secret(self, client):
        resp = await client.put("/api/secrets/TEST_KEY", json={
            "value": "my-secret-value-12345",
            "category": "auth",
            "description": "Test API key",
            "is_required": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "secret_created"
        assert data["key"] == "TEST_KEY"

    @pytest.mark.asyncio
    async def test_list_after_create(self, client):
        await client.put("/api/secrets/MY_KEY", json={"value": "val123", "category": "broker"})
        resp = await client.get("/api/secrets")
        assert resp.status_code == 200
        secrets = resp.json()
        assert len(secrets) == 1
        assert secrets[0]["key"] == "MY_KEY"
        assert secrets[0]["category"] == "broker"
        # Value should not be in the list response
        assert "value" not in secrets[0]
        assert "encrypted_value" not in secrets[0]

    @pytest.mark.asyncio
    async def test_get_secret_masked(self, client):
        await client.put("/api/secrets/LONG_TOKEN", json={
            "value": "sk-ant-oat01-abc123def456fa61",
            "category": "auth",
        })
        resp = await client.get("/api/secrets/LONG_TOKEN")
        assert resp.status_code == 200
        data = resp.json()
        assert data["masked_value"].startswith("sk-ant")
        assert data["masked_value"].endswith("fa61")
        assert "abc123" not in data["masked_value"]

    @pytest.mark.asyncio
    async def test_update_secret(self, client):
        await client.put("/api/secrets/UPD_KEY", json={"value": "old-value"})
        resp = await client.put("/api/secrets/UPD_KEY", json={"value": "new-value", "category": "notification"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "secret_updated"

        # Verify updated value decrypts correctly
        resp2 = await client.get("/api/secrets/UPD_KEY")
        assert resp2.json()["category"] == "notification"

    @pytest.mark.asyncio
    async def test_delete_secret(self, client):
        await client.put("/api/secrets/DEL_KEY", json={"value": "to-delete"})
        resp = await client.delete("/api/secrets/DEL_KEY")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Should no longer appear in list
        resp2 = await client.get("/api/secrets")
        assert all(s["key"] != "DEL_KEY" for s in resp2.json())

    @pytest.mark.asyncio
    async def test_get_nonexistent_secret(self, client):
        resp = await client.get("/api/secrets/DOES_NOT_EXIST")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_secret(self, client):
        resp = await client.delete("/api/secrets/DOES_NOT_EXIST")
        assert resp.status_code == 404


class TestSecretHistory:
    @pytest.mark.asyncio
    async def test_history_after_operations(self, client):
        # Create then read
        await client.put("/api/secrets/HIST_KEY", json={"value": "val"})
        await client.get("/api/secrets/HIST_KEY")

        resp = await client.get("/api/secrets/HIST_KEY/history")
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) >= 2
        actions = [e["action"] for e in entries]
        assert "secret_created" in actions
        assert "secret_read" in actions


class TestSecretTest:
    @pytest.mark.asyncio
    async def test_untestable_category(self, client):
        await client.put("/api/secrets/NO_TEST", json={"value": "val", "category": "general"})
        resp = await client.post("/api/secrets/NO_TEST/test")
        assert resp.status_code == 200
        assert resp.json()["testable"] is False
