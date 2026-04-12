"""
Integration tests for WebSocket runner log streaming.
"""

import json
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


def _make_test_app():
    from fastapi import FastAPI
    from app.api.ws_runners import router

    app = FastAPI()
    app.include_router(router)
    return app


class TestRunnerLogsWebSocket:
    def test_websocket_auth_disabled_connects(self, redis_client):
        """When auth is disabled, WebSocket connects without token."""
        app = _make_test_app()

        with (
            patch("app.auth._auth_enabled", return_value=False),
            patch("app.api.ws_runners.redis_lib.from_url", return_value=redis_client),
        ):
            client = TestClient(app)
            with client.websocket_connect("/ws/runners/1/logs") as ws:
                # Connection established = success
                pass

    def test_websocket_auth_failure_closes(self):
        """When auth is enabled and token is invalid, WebSocket is rejected."""
        app = _make_test_app()

        with (
            patch("app.auth._auth_enabled", return_value=True),
            patch("app.auth.verify_token", return_value=None),
        ):
            client = TestClient(app)
            with pytest.raises(Exception):
                with client.websocket_connect("/ws/runners/1/logs?token=bad-token"):
                    pass

    def test_websocket_auth_success_connects(self, redis_client):
        """When auth is enabled and token is valid, WebSocket connects."""
        app = _make_test_app()

        with (
            patch("app.auth._auth_enabled", return_value=True),
            patch("app.auth.verify_token", return_value={"sub": "owner"}),
            patch("app.api.ws_runners.redis_lib.from_url", return_value=redis_client),
        ):
            client = TestClient(app)
            with client.websocket_connect("/ws/runners/1/logs?token=valid-token") as ws:
                pass  # Connection accepted = success

    def test_websocket_no_token_when_auth_enabled(self):
        """When auth is enabled and no token provided, WebSocket is rejected."""
        app = _make_test_app()

        with patch("app.auth._auth_enabled", return_value=True):
            client = TestClient(app)
            with pytest.raises(Exception):
                with client.websocket_connect("/ws/runners/1/logs"):
                    pass
