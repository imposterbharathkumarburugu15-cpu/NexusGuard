"""Comprehensive Phase 1 RBAC, Agent Access, and Enterprise Connector Test Suite.

Covers:
1. Connector access with valid structured policy
2. Connector access after frontend permission update
3. Allowed agent
4. Unauthorized agent
5. Allowed resource
6. Unauthorized resource
7. Read permission
8. Create permission
9. Update permission
10. Delete permission
11. Tenant isolation
12. Clearance restriction
13. Tool authorization
14. Jira search
15. Jira create with approval
16. Teams search
17. Outlook search
18. Entra lookup
19. Connector authorization failure
20. Invalid connector configuration
21. Exact end-to-end bug reproduction and resolution test
"""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.session import SessionLocal
from app.db.models import Connector, ConnectorItem, AIAction, User
from app.core.security import Principal, principal_from_user
from app.services.connectors.permission_engine import (
    check_connector_access,
    normalize_agent_access,
    CANONICAL_AGENTS,
)
from app.services.tools import (
    ToolContext,
    run_tool,
    t_search_jira_issues,
    t_create_jira_issue,
    t_search_teams_messages,
    t_post_teams_message,
    t_search_emails,
    t_lookup_entra_identity,
    execute_action,
)

PRIYA = "priya.reddy@novatech.demo"  # Engineering Lead (RESTRICTED clearance, all engineering perms)
RAHUL = "rahul.sharma@novatech.demo"  # Staff Security Engineer
ANANYA = "ananya.rao@novatech.demo"  # Associate Engineer (CONFIDENTIAL clearance)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(c, email=PRIYA):
    r = c.post("/api/auth/sso/demo", json={"email": email})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def guest(c):
    r = c.post("/api/auth/guest")
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def get_principal(email=PRIYA):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None
        return principal_from_user(u, "NovaTech Solutions")


# -----------------------------------------------------------------------------
# 1. Connector access with valid structured policy
# -----------------------------------------------------------------------------
def test_01_connector_access_valid_structured_policy():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # conn_jira has valid structured policy seeded
        dec = check_connector_access(db, p, "conn_jira", "READ", resource="NOVA", agent_name="Project Agent")
        assert dec.allowed is True
        assert dec.connector.id == "conn_jira"


# -----------------------------------------------------------------------------
# 2. Connector access after frontend permission update
# -----------------------------------------------------------------------------
def test_02_connector_access_after_frontend_permission_update(client):
    auth_hdr = login(client, PRIYA)
    payload = {
        "agent_access": {
            "allowed_agents": ["Project Agent", "Workflow Agent"],
            "allowed_resources": ["NOVA", "SEC"],
            "read_write": {"read": True, "create": True, "update": False, "delete": False},
        }
    }
    r = client.patch("/api/connectors/conn_jira/permissions", json=payload, headers=auth_hdr)
    assert r.status_code == 200
    updated = r.json()
    assert "agent_access" in updated
    assert updated["agent_access"]["allowed_agents"] == ["Project Agent", "Workflow Agent"]
    assert updated["agent_access"]["read_write"]["create"] is True

    # Verify reloading gets the exact structured policy
    r_get = client.get("/api/connectors", headers=auth_hdr)
    jira = next(c for c in r_get.json()["connectors"] if c["id"] == "conn_jira")
    assert jira["agent_access"]["allowed_agents"] == ["Project Agent", "Workflow Agent"]
    assert jira["agent_access"]["read_write"]["read"] is True


# -----------------------------------------------------------------------------
# 3. Allowed agent
# -----------------------------------------------------------------------------
def test_03_allowed_agent():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        dec = check_connector_access(db, p, "conn_jira", "READ", agent_name="Project Agent")
        assert dec.allowed is True


# -----------------------------------------------------------------------------
# 4. Unauthorized agent
# -----------------------------------------------------------------------------
def test_04_unauthorized_agent():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # HR Agent is not permitted on Jira
        dec = check_connector_access(db, p, "conn_jira", "READ", agent_name="HR Agent")
        assert dec.allowed is False
        assert "not authorized" in dec.reason.lower()


# -----------------------------------------------------------------------------
# 5. Allowed resource
# -----------------------------------------------------------------------------
def test_05_allowed_resource():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        dec = check_connector_access(db, p, "conn_jira", "READ", resource="NOVA", agent_name="Project Agent")
        assert dec.allowed is True


# -----------------------------------------------------------------------------
# 6. Unauthorized resource
# -----------------------------------------------------------------------------
def test_06_unauthorized_resource():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        dec = check_connector_access(db, p, "conn_jira", "READ", resource="UNAUTHORIZED_PROJ_999", agent_name="Project Agent")
        assert dec.allowed is False
        assert "resource" in dec.reason.lower()


# -----------------------------------------------------------------------------
# 7. Read permission
# -----------------------------------------------------------------------------
def test_07_read_permission():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        dec = check_connector_access(db, p, "conn_jira", "READ", agent_name="Project Agent")
        assert dec.allowed is True


# -----------------------------------------------------------------------------
# 8. Create permission
# -----------------------------------------------------------------------------
def test_08_create_permission():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        dec = check_connector_access(db, p, "conn_jira", "CREATE", agent_name="Workflow Agent")
        assert dec.allowed is True


# -----------------------------------------------------------------------------
# 9. Update permission
# -----------------------------------------------------------------------------
def test_09_update_permission():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # conn_teams has update: False by default
        dec = check_connector_access(db, p, "conn_teams", "UPDATE", agent_name="Workflow Agent")
        assert dec.allowed is False
        assert "update" in dec.reason.lower()


# -----------------------------------------------------------------------------
# 10. Delete permission
# -----------------------------------------------------------------------------
def test_10_delete_permission():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        dec = check_connector_access(db, p, "conn_jira", "DELETE", agent_name="Workflow Agent")
        assert dec.allowed is False
        assert "delete" in dec.reason.lower()


# -----------------------------------------------------------------------------
# 11. Tenant isolation
# -----------------------------------------------------------------------------
def test_11_tenant_isolation():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        p.company_id = "comp_alien_tenant_999"
        dec = check_connector_access(db, p, "conn_jira", "READ", agent_name="Project Agent")
        assert dec.allowed is False
        assert "not found" in dec.reason.lower() or "tenant" in dec.reason.lower()


# -----------------------------------------------------------------------------
# 12. Clearance restriction
# -----------------------------------------------------------------------------
def test_12_clearance_restriction():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        p.clearance = "PUBLIC"
        p.permissions = []
        dec = check_connector_access(db, p, "conn_jira", "READ", agent_name="Project Agent")
        assert dec.allowed is False


# -----------------------------------------------------------------------------
# 13. Tool authorization
# -----------------------------------------------------------------------------
def test_13_tool_authorization():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Guest or user without permission
        p.permissions = []
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")
        out = run_tool(ctx, "search_jira_issues", {"query": "token"})
        assert out.status == "denied"
        assert "lacks" in out.summary.lower() or "denied" in out.llm_view.lower()


# -----------------------------------------------------------------------------
# 14. Jira search
# -----------------------------------------------------------------------------
def test_14_jira_search():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")
        out = t_search_jira_issues(ctx, query="token", project="NOVA")
        assert out.status == "ok"
        assert len(out.data["issues"]) > 0
        assert any("token" in iss["title"].lower() or "session" in iss["title"].lower() for iss in out.data["issues"])


# -----------------------------------------------------------------------------
# 15. Jira create with approval
# -----------------------------------------------------------------------------
def test_15_jira_create_with_approval():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")
        out = t_create_jira_issue(
            ctx,
            title="Enforce Redis token revocation",
            description="Remediation for SEC-VULN-01 token bypass",
            project="NOVA",
            priority="High"
        )
        assert out.status == "pending_confirmation"
        assert out.action is not None
        act_id = out.action.id

        # Now simulate user confirmation via execute_action
        action_row = db.get(AIAction, act_id)
        assert action_row.status == "pending_confirmation"

        res = execute_action(db, p, action_row)
        assert "reference" in res
        assert "created successfully" in res["message"]

        # Verify real ConnectorItem is created in DB
        created_item = db.scalar(select(ConnectorItem).where(ConnectorItem.external_id == res["reference"]))
        assert created_item is not None
        assert created_item.title == "Enforce Redis token revocation"
        assert created_item.provider == "jira"


# -----------------------------------------------------------------------------
# 16. Teams search
# -----------------------------------------------------------------------------
def test_16_teams_search():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")
        out = t_search_teams_messages(ctx, query="token", channel="#security-eng")
        assert out.status == "ok"
        assert len(out.data["messages"]) > 0


# -----------------------------------------------------------------------------
# 17. Outlook search
# -----------------------------------------------------------------------------
def test_17_outlook_search():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")
        out = t_search_emails(ctx, query="security")
        assert out.status == "ok"
        assert "emails" in out.data


# -----------------------------------------------------------------------------
# 18. Entra lookup
# -----------------------------------------------------------------------------
def test_18_entra_lookup():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")
        out = t_lookup_entra_identity(ctx, query="me")
        assert out.status == "ok"
        assert out.data["userPrincipalName"] == PRIYA
        assert "memberOf" in out.data


# -----------------------------------------------------------------------------
# 19. Connector authorization failure
# -----------------------------------------------------------------------------
def test_19_connector_authorization_failure():
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Disconnect connector temporarily
        conn = db.get(Connector, "conn_jira")
        orig_status = conn.status
        try:
            conn.status = "not_connected"
            db.flush()
            dec = check_connector_access(db, p, "conn_jira", "READ", agent_name="Project Agent")
            assert dec.allowed is False
            assert "not connected" in dec.reason.lower()
        finally:
            conn.status = orig_status
            db.flush()


# -----------------------------------------------------------------------------
# 20. Invalid connector configuration
# -----------------------------------------------------------------------------
def test_20_invalid_connector_configuration():
    # Corrupt or unexpected format
    normalized = normalize_agent_access(None)
    assert isinstance(normalized["allowed_agents"], list)
    assert isinstance(normalized["read_write"], dict)

    normalized2 = normalize_agent_access({"unknown_field": 123})
    assert isinstance(normalized2["allowed_agents"], list)
    assert normalized2["read_write"]["read"] is True


# -----------------------------------------------------------------------------
# 21. Exact end-to-end bug reproduction and resolution test:
# 1. Open connector permissions UI
# 2. Change agent access
# 3. Save
# 4. Reload connector
# 5. Verify structured agent_access is preserved
# 6. Execute an authorized connector tool -> succeeds
# 7. Execute unauthorized connector tool -> denied
# -----------------------------------------------------------------------------
def test_21_exact_bug_flow_resolution(client):
    auth_hdr = login(client, PRIYA)

    # 1. Open connector permissions UI (GET /api/connectors)
    r1 = client.get("/api/connectors", headers=auth_hdr)
    assert r1.status_code == 200

    # 2 & 3. Change agent access & Save (PATCH with structured policy)
    policy = {
        "agent_access": {
            "allowed_agents": ["Project Agent"],
            "allowed_resources": ["NOVA"],
            "read_write": {
                "read": True,
                "create": False,
                "update": False,
                "delete": False,
            },
        }
    }
    r2 = client.patch("/api/connectors/conn_jira/permissions", json=policy, headers=auth_hdr)
    assert r2.status_code == 200

    # 4 & 5. Reload connector and verify structured agent_access is preserved
    r3 = client.get("/api/connectors", headers=auth_hdr)
    jira = next(c for c in r3.json()["connectors"] if c["id"] == "conn_jira")
    assert jira["agent_access"]["allowed_agents"] == ["Project Agent"]
    assert jira["agent_access"]["read_write"]["read"] is True
    assert jira["agent_access"]["read_write"]["create"] is False

    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_1", request_id="req_1")

        # 6 & 7. Execute authorized connector tool (Project Agent on READ) -> succeeds
        out_auth = t_search_jira_issues(ctx, query="token", project="NOVA")
        assert out_auth.status == "ok"
        assert len(out_auth.data["issues"]) > 0

        # 8 & 9. Execute unauthorized connector action (CREATE is disabled in policy) -> denied
        out_denied = t_create_jira_issue(ctx, title="Blocked Ticket", description="Desc", project="NOVA")
        assert out_denied.status == "denied"
        assert "not permitted" in out_denied.summary.lower() or "denied" in out_denied.summary.lower()

    # Restore full Jira access for other tests
    restore_policy = {
        "agent_access": {
            "allowed_agents": ["Project Agent", "Workflow Agent", "Security Analysis Agent", "Knowledge Agent"],
            "allowed_resources": ["NOVA", "SEC", "DEVOPS"],
            "read_write": {
                "read": True,
                "create": True,
                "update": True,
                "delete": False,
            },
        }
    }
    client.patch("/api/connectors/conn_jira/permissions", json=restore_policy, headers=auth_hdr)
