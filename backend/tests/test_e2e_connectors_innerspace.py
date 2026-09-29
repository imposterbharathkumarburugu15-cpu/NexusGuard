"""Phase 2 End-to-End Enterprise Connector and Innerspace Verification Suite.

Tests the complete flow from Innerspace UI/Chat through backend API,
authentication, principal resolution, authorization policy engine, agent routing,
tool selection, connector providers, database records, and audit logging.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db.session import SessionLocal
from app.db.models import Connector, ConnectorItem, AIAction, AuditLog, User
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

PRIYA = "priya.reddy@novatech.demo"   # Engineering Lead (RESTRICTED clearance)
RAHUL = "rahul.sharma@novatech.demo"   # Staff Security Engineer
ANANYA = "ananya.rao@novatech.demo"   # Associate Engineer (CONFIDENTIAL clearance)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(c, email=PRIYA):
    r = c.post("/api/auth/sso/demo", json={"email": email})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def guest_auth(c):
    r = c.post("/api/auth/guest")
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def get_principal(email=PRIYA):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None
        return principal_from_user(u, "NovaTech Solutions")


# =============================================================================
# PART 1: END-TO-END CONNECTOR TESTING (VIA CHAT & API)
# =============================================================================

# -----------------------------------------------------------------------------
# TEST 1 — JIRA SEARCH
# -----------------------------------------------------------------------------
def test_p2_01_jira_search_chat_e2e(client):
    """Ask 'Show my Jira issues' via Chat and verify end-to-end trace."""
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "Show my Jira issues"}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 1. Request reached backend and assistant replied
    content = data["assistant_message"]["content"]
    meta = data["assistant_message"]["meta"]
    timeline = meta.get("timeline", [])

    # 2. User authenticated and correct tenant identified
    id_steps = [s for s in timeline if s.get("key") == "identity"]
    assert len(id_steps) > 0
    assert "Priya Reddy" in id_steps[0].get("detail", "")

    # 3. Correct agent selected: Project Agent
    route_steps = [s for s in timeline if "route_Project Agent" in s.get("key", "")]
    assert len(route_steps) > 0 or "Project Agent" in meta.get("agents", [])

    # 4. Jira tool selected
    tool_steps = [s for s in timeline if s.get("tool") == "search_jira_issues"]
    assert len(tool_steps) > 0

    # 5. Jira records retrieved and displayed in UI
    assert "Jira issue" in content or "NOVA-" in content

    # 6. Audit information recorded in database
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        audit_event = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.company_id == p.company_id,
                AuditLog.tool == "search_jira_issues",
            )
            .order_by(AuditLog.ts.desc())
        )
        assert audit_event is not None
        assert audit_event.permission_result == "ALLOWED"


def test_p2_02_jira_search_unauthorized_project_chat_e2e(client):
    """Ask 'Show Jira issues from an unauthorized project.' -> DENIED."""
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "Show Jira issues from an unauthorized project."}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    content = resp.json()["assistant_message"]["content"]
    assert "Access denied" in content or "🔒" in content
    assert "NOVA-" not in content


# -----------------------------------------------------------------------------
# TEST 2 — OUTLOOK SEARCH VS DRAFT
# -----------------------------------------------------------------------------
def test_p2_03_outlook_search_chat_e2e(client):
    """Ask 'Find the latest emails about the security review.'

    Verify: Productivity Agent -> Outlook search tool -> Mailbox data -> Result.
    CRITICAL: Must NOT create an email draft!
    """
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "Find the latest emails about the security review."}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    content = data["assistant_message"]["content"]
    meta = data["assistant_message"]["meta"]
    timeline = meta.get("timeline", [])

    # Agent: Productivity Agent
    prod_routes = [s for s in timeline if "route_Productivity Agent" in s.get("key", "")]
    assert len(prod_routes) > 0 or "Productivity Agent" in meta.get("agents", [])

    # Tool: search_emails
    email_tools = [s for s in timeline if s.get("tool") == "search_emails"]
    assert len(email_tools) > 0

    # Content contains Outlook email search results
    assert "Outlook email" in content or "Security Review" in content or "Found" in content

    # CRITICAL: No action draft created!
    actions = meta.get("actions", [])
    assert len(actions) == 0, "Email search must NOT create an email draft action!"


def test_p2_04_outlook_draft_email_chat_e2e(client):
    """Ask 'Draft an email to Alex about the security review.'

    Verify: Classified as communication/drafting -> Workflow Agent -> pending_confirmation action proposal.
    """
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "Draft an email to Alex about the security review."}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    meta = data["assistant_message"]["meta"]

    # Classified as communication / drafting
    assert meta.get("intent") in ("communication", "workflow_execution", "KNOWLEDGE_BASE_QUERY")

    # Creates pending_confirmation AIAction
    actions = meta.get("actions", [])
    assert len(actions) > 0
    assert actions[0]["tool"] in ("draft_email", "send_email")
    assert actions[0]["status"] == "pending_confirmation"


# -----------------------------------------------------------------------------
# TEST 3 — TEAMS SEARCH
# -----------------------------------------------------------------------------
def test_p2_05_teams_search_chat_e2e(client):
    """Ask 'What was discussed in Teams about the security issue?'

    Verify: Security Analysis Agent -> Teams search -> channel permission -> authorized messages -> response.
    """
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "What was discussed in Teams about the security issue?"}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    content = data["assistant_message"]["content"]
    meta = data["assistant_message"]["meta"]
    timeline = meta.get("timeline", [])

    # Agent: Security Analysis Agent
    sec_routes = [s for s in timeline if "route_Security Analysis Agent" in s.get("key", "")]
    assert len(sec_routes) > 0 or "Security Analysis Agent" in meta.get("agents", [])

    # Tool: search_teams_messages
    teams_tools = [s for s in timeline if s.get("tool") == "search_teams_messages"]
    assert len(teams_tools) > 0

    # Content contains Teams discussion messages
    assert "Teams discussion" in content or "Priya" in content or "#security-eng" in content


def test_p2_06_teams_search_unauthorized_channel_chat_e2e(client):
    """Ask 'Show Teams messages in channel #unauthorized' -> DENIED."""
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "Show Teams messages in channel #unauthorized"}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    content = resp.json()["assistant_message"]["content"]
    assert "Access denied" in content or "🔒" in content


# -----------------------------------------------------------------------------
# TEST 4 — ENTRA DIRECTORY LOOKUP & TENANT ISOLATION
# -----------------------------------------------------------------------------
def test_p2_07_entra_lookup_chat_e2e(client):
    """Authorized directory lookup via Security Analysis Agent."""
    auth_hdr = login(client, PRIYA)
    resp = client.post("/api/chat", json={"message": "Check Entra profile for me"}, headers=auth_hdr)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    content = data["assistant_message"]["content"]

    # Entra directory profile returned
    assert "Microsoft Entra ID Profile" in content or "Entra ID" in content
    assert "Priya Reddy" in content or "MFA Status" in content


def test_p2_08_entra_cross_tenant_isolation(client):
    """User from Tenant A requesting Tenant B data -> DENIED / Not found. Zero information leak."""
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Attempt lookup for a user in another company
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_test", request_id="req_test")
        out = t_lookup_entra_identity(ctx, query="foreign_user@othercompany.demo")
        assert out.status == "not_found"
        assert "not found" in out.summary.lower()


# -----------------------------------------------------------------------------
# TEST 5 — JIRA CREATE / HUMAN APPROVAL GATE
# -----------------------------------------------------------------------------
def test_p2_09_jira_create_human_approval_gate_e2e(client):
    """Trigger Jira creation request via Chat, verify AIAction created in pending_confirmation,

    then execute POST /api/actions/{id}/confirm, verify ConnectorItem created in DB,
    audit log recorded, and success returned.
    """
    auth_hdr = login(client, PRIYA)

    # Step 1: User request -> Agent -> Jira tool -> AIAction pending_confirmation
    chat_resp = client.post(
        "/api/chat",
        json={"message": "Create a Jira issue in NOVA titled 'Fix token expiry'"},
        headers=auth_hdr,
    )
    assert chat_resp.status_code == 200, chat_resp.text
    meta = chat_resp.json()["assistant_message"]["meta"]
    actions = meta.get("actions", [])
    assert len(actions) > 0, "Expected action proposal for Jira creation"
    action = actions[0]
    assert action["tool"] == "create_jira_issue"
    assert action["status"] == "pending_confirmation"
    action_id = action["id"]

    # Step 2: User clicks approval -> POST /api/actions/{id}/confirm
    confirm_resp = client.post(f"/api/actions/{action_id}/confirm", json={}, headers=auth_hdr)
    assert confirm_resp.status_code == 200, confirm_resp.text
    confirmed_data = confirm_resp.json()
    assert confirmed_data["status"] == "executed"
    ticket_ref = confirmed_data["result"]["reference"]
    assert ticket_ref.startswith("NOVA-")

    # Step 3: Verify ConnectorItem created in SQLite database (NO fake timeout!)
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        item = db.scalar(
            select(ConnectorItem)
            .where(
                ConnectorItem.company_id == p.company_id,
                ConnectorItem.external_id == ticket_ref,
            )
        )
        assert item is not None
        assert item.title == "Fix token expiry"
        assert item.provider == "jira"
        assert item.item_type == "jira_issue"

        # Step 4: Verify audit log recorded
        audit_row = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.company_id == p.company_id,
                AuditLog.action == "ai.action_executed",
                AuditLog.tool == "create_jira_issue",
                AuditLog.resource_id == ticket_ref,
            )
        )
        assert audit_row is not None
        assert audit_row.result == "EXECUTED"


# =============================================================================
# PART 2: NEGATIVE SECURITY TESTS MATRIX
# =============================================================================

def test_p2_10_negative_unauthorized_user_guest(client):
    """Guest / unauthorized user denied access to all enterprise connectors."""
    guest_hdr = guest_auth(client)

    # Jira search
    r = client.post("/api/chat", json={"message": "Show my Jira issues"}, headers=guest_hdr)
    assert r.status_code == 200
    assert "Guest Mode" in r.json()["assistant_message"]["content"] or "🔒" in r.json()["assistant_message"]["content"]

    # Jira creation
    r = client.post("/api/chat", json={"message": "Create a Jira issue in NOVA titled 'Leak'"}, headers=guest_hdr)
    assert r.status_code == 200
    assert "Guest Mode" in r.json()["assistant_message"]["content"] or "🔒" in r.json()["assistant_message"]["content"]


def test_p2_11_negative_insufficient_clearance():
    """Principal with PUBLIC clearance denied access to internal connectors."""
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Create a temporary public clearance principal
        public_p = Principal(**{**p.__dict__, "clearance": "PUBLIC"})
        for conn_id in ("conn_github", "conn_jira", "conn_teams", "conn_outlook", "conn_entra"):
            dec = check_connector_access(db, public_p, conn_id, "READ")
            assert dec.allowed is False
            assert "Clearance" in dec.reason


def test_p2_12_negative_unauthorized_agent():
    """Agent not present in allowed_agents is strictly denied."""
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Calling Jira connector from HR Agent must be denied
        dec = check_connector_access(db, p, "conn_jira", "READ", resource="NOVA", agent_name="HR Agent")
        assert dec.allowed is False
        assert "is not authorized to access" in dec.reason


def test_p2_13_negative_unauthorized_resource():
    """Resource not in allowed_resources is strictly denied before data query."""
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Jira project not in ["NOVA", "SEC", "DEVOPS"]
        dec = check_connector_access(db, p, "conn_jira", "READ", resource="TOP_SECRET_PRJ", agent_name="Project Agent")
        assert dec.allowed is False
        assert "outside the authorized scope" in dec.reason

        # Teams channel not in ["#general", "#security-eng", "#backend-platform"]
        dec_teams = check_connector_access(db, p, "conn_teams", "READ", resource="#executive-board", agent_name="Security Analysis Agent")
        assert dec_teams.allowed is False
        assert "outside the authorized scope" in dec_teams.reason


def test_p2_14_negative_disconnected_connector(client):
    """Disconnected connector operations are strictly blocked."""
    auth_hdr = login(client, PRIYA)
    with SessionLocal() as db:
        c = db.get(Connector, "conn_outlook")
        c.status = "disconnected"
        db.commit()

    try:
        # Search emails while disconnected
        resp = client.post("/api/chat", json={"message": "Find the latest emails about the security review."}, headers=auth_hdr)
        assert resp.status_code == 200
        content = resp.json()["assistant_message"]["content"]
        assert "Access denied" in content or "🔒" in content or "disconnected" in content.lower()
    finally:
        with SessionLocal() as db:
            c = db.get(Connector, "conn_outlook")
            c.status = "connected"
            db.commit()


def test_p2_15_negative_missing_crud_permission():
    """Connector configured without create permission blocks create operations."""
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        # Temporarily disable create on conn_jira
        c = db.get(Connector, "conn_jira")
        orig_access = dict(c.agent_access)
        modified = dict(orig_access)
        modified["read_write"] = {"read": True, "create": False, "update": False, "delete": False}
        c.agent_access = modified
        db.commit()

        try:
            dec = check_connector_access(db, p, "conn_jira", "CREATE", resource="NOVA", agent_name="Workflow Agent")
            assert dec.allowed is False
            assert "is not permitted by connector policy" in dec.reason
        finally:
            c.agent_access = orig_access
            db.commit()


# =============================================================================
# PART 3: INNERSPACE UI PERMISSION MANAGEMENT FLOW
# =============================================================================

def test_p2_16_innerspace_permission_persistence_and_enforcement_cycle(client):
    """Test full Innerspace UI flow:

    1. Open connector config
    2. Change authorized agents & CRUD permissions
    3. Save via PATCH /api/connectors/{id}/permissions
    4. Reload via GET /api/connectors and verify canonical schema persisted
    5. Execute authorized operation -> succeeds
    6. Remove permission via PATCH
    7. Execute same operation -> DENIED
    """
    auth_hdr = login(client, PRIYA)

    # 1. Fetch connectors list
    r = client.get("/api/connectors", headers=auth_hdr)
    assert r.status_code == 200
    connectors = r.json()["connectors"]
    jira_conn = next(c for c in connectors if c["id"] == "conn_jira")

    # 2. Update permissions to allow Workflow Agent and create=True
    policy = {
        "allowed_agents": ["Project Agent", "Workflow Agent", "Security Analysis Agent"],
        "allowed_resources": ["NOVA", "SEC", "DEVOPS"],
        "read_write": {"read": True, "create": True, "update": True, "delete": False}
    }
    patch_r = client.patch(
        f"/api/connectors/{jira_conn['id']}/permissions",
        json={"agent_access": policy},
        headers=auth_hdr,
    )
    assert patch_r.status_code == 200
    updated_access = patch_r.json()["agent_access"]
    assert updated_access["read_write"]["create"] is True

    # 3. Reload connectors to verify persistence
    reload_r = client.get("/api/connectors", headers=auth_hdr)
    reloaded_jira = next(c for c in reload_r.json()["connectors"] if c["id"] == "conn_jira")
    assert "Workflow Agent" in reloaded_jira["agent_access"]["allowed_agents"]
    assert reloaded_jira["agent_access"]["read_write"]["create"] is True

    # 4. Execute authorized operation: create Jira issue proposal
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_p2", request_id="req_p2_create")
        out = t_create_jira_issue(ctx, title="E2E UI Test Ticket", description="Testing authorized execution", project="NOVA")
        assert out.status == "pending_confirmation"

    # 5. Remove 'create' permission
    restrict_policy = {
        "allowed_agents": ["Project Agent"],
        "allowed_resources": ["NOVA"],
        "read_write": {"read": True, "create": False, "update": False, "delete": False}
    }
    client.patch(
        f"/api/connectors/{jira_conn['id']}/permissions",
        json={"agent_access": restrict_policy},
        headers=auth_hdr,
    )

    # 6. Execute same operation: verify now DENIED
    with SessionLocal() as db:
        p = get_principal(PRIYA)
        ctx = ToolContext(db=db, principal=p, conversation_id="conv_p2", request_id="req_p2_denied")
        out_denied = t_create_jira_issue(ctx, title="E2E UI Test Ticket", description="Testing blocked execution", project="NOVA")
        assert out_denied.status == "denied"
        assert "not permitted" in out_denied.summary.lower()

    # 7. Restore default permissions
    client.patch(
        f"/api/connectors/{jira_conn['id']}/permissions",
        json={"agent_access": policy},
        headers=auth_hdr,
    )


# =============================================================================
# PART 4: 1-CLICK LIVE DEMO WORKFLOW TRACE
# =============================================================================

def test_p2_17_1click_live_demo_composed_workflow_e2e(client):
    """Trace the 1-Click Live Demo workflow:

    GitHub -> Code Analysis -> Security Analysis -> Jira -> Teams -> Report -> Human Approval.
    Verify that AIAction is generated in pending_confirmation and can be confirmed.
    """
    auth_hdr = login(client, PRIYA)

    # Execute composed workflow
    r = client.post("/api/skills/execute", json={"skill_id": "composed_workflow", "target": "authentication service"}, headers=auth_hdr)
    assert r.status_code == 200, r.text
    result = r.json()

    # 1. Step: Pipeline structure
    pipeline_ids = [s["id"] for s in result["pipeline"]]
    assert "github" in pipeline_ids
    assert "security" in pipeline_ids
    assert "jira" in pipeline_ids
    assert "teams" in pipeline_ids
    assert "report" in pipeline_ids
    assert "approval" in pipeline_ids

    # 2. Step: Security Vulnerability Scan (CWE findings)
    assert len(result["findings"]) > 0
    assert any("CWE-384" in f["cwe"] for f in result["findings"])

    # 3. Step: Jira Issue Tracking & Report
    assert len(result["jira_issues"]) > 0
    assert "Security Assessment & Engineering Status Report" in result["report"]["report_title"]

    # 4. Step: Human Approval Proposal
    proposal = result["action_proposal"]
    assert proposal["title"].startswith("Create Jira Issue")
    action_id = proposal["action_id"]
    assert action_id is not None

    # 5. Confirm the proposal via POST /api/actions/{action_id}/confirm
    confirm_r = client.post(f"/api/actions/{action_id}/confirm", json={}, headers=auth_hdr)
    assert confirm_r.status_code == 200, confirm_r.text
    confirmed = confirm_r.json()
    assert confirmed["status"] == "executed"
    ref = confirmed["result"]["reference"]
    assert ref.startswith("NOVA-")
