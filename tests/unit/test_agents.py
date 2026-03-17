"""
Unit tests for agent and group management routes.
Uses FastAPI TestClient with mocked DB and auth.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# Patch auth before importing app so require_agent is bypassed
TEST_AGENT_ID = "urn:cb:agent:00000000-0000-0000-0000-000000000001"
TEST_AGENT_ID_2 = "urn:cb:agent:00000000-0000-0000-0000-000000000002"


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.id = TEST_AGENT_ID
    agent.display_name = "Test Agent"
    agent.public_key = "dGVzdA"
    agent.created_at = datetime(2026, 3, 16, tzinfo=timezone.utc)
    return agent


def test_agent_routes_registered():
    """Verify agent and group routes are registered on the app."""
    with patch("contentbank.auth.tokens.verify_agent_token",
               return_value=TEST_AGENT_ID):
        from contentbank.main import app
        paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/v1/agents/me" in paths
        assert "/api/v1/agents/{agent_id}" in paths
        assert "/api/v1/groups" in paths
        assert "/api/v1/groups/{group_id}" in paths
        assert "/api/v1/groups/{group_id}/members" in paths
        assert "/api/v1/groups/{group_id}/members/{agent_id}" in paths


def test_group_type_validation():
    """group_type must be 'family' or 'group'."""
    from contentbank.api.routes.agents import ScopeGroupCreate
    from pydantic import ValidationError

    # Valid
    ScopeGroupCreate(name="Test", group_type="family")
    ScopeGroupCreate(name="Test", group_type="group")
