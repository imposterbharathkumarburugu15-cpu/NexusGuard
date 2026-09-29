# NexusGuard / NovaTech Solutions — Enterprise Intelligence Platform

**An enterprise agentic AI governance platform featuring multi-agent RAG, Hindsight persistent memory, zero-trust pre-retrieval RBAC, an Engineering Code Review Agent with human approval gates, and a tamper-evident audit trail.**

> **Notice:** NovaTech Solutions, its employees, customers, repositories, and documents in this demo are **fictional, synthetic enterprise data**. No real personal information or proprietary credentials are used.

![Login](docs/screenshots/01_login.png)

| Attribute | Details |
|---|---|
| **Tech Stack** | React 18 + TypeScript + Tailwind CSS · FastAPI (Python 3.11/3.13) · SQLite (zero-setup default) or PostgreSQL 16 + pgvector · Optional OpenAI-compatible LLM / Offline Deterministic Engine |
| **Enterprise Data** | ~48,000 synthetic relational records across 44 tables: 2,291 employees, 1,196 projects, 6,800 tasks, 2,676 documents (4,000 indexed chunks), 5 enterprise connectors, 3 source code repositories |
| **Canonical Agents** | 10 specialized executable agents: `Knowledge Agent`, `HR Agent`, `IT Agent`, `Project Agent`, `Document Agent`, `Analytics Agent`, `Workflow Agent`, `Productivity Agent`, `Security Analysis Agent`, `Engineering Code Review Agent` |
| **Persistent Memory** | Hindsight dual-persistence engine with tenant-partitioned memory banks (`nexus_{company_id}`), secret filtering, and correction-aware relevance scoring |
| **Security & RBAC** | Pre-retrieval RBAC before data access · Monotonic clearances (`PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`) · Tenant isolation · Memory non-bypass invariant |
| **Human-in-the-Loop** | State mutations and code modifications strictly require human confirmation via `AIAction(status="pending_confirmation")` with server-side replay protection |
| **Backend Tests** | `cd backend && pytest` → **166 passing** across 10 test modules (zero failures, zero regressions) |
| **Frontend Health** | `npm run typecheck` (0 errors), `npm run lint` (0 warnings), `npm run build` (2,401 modules bundled in ~8.5s) |

---

## 1. Quickstart & Deployment

### Option A — Local Development (SQLite, Zero Setup)
```bash
# Terminal 1 — Backend (FastAPI on :8000)
cd backend
cp .env.example .env                 # Configure optional OpenAI / SMTP settings
pip install -r requirements.txt
uvicorn app.main:app --port 8000     # First boot seeds ~48k records + connectors + repos (~5-10s)

# Terminal 2 — Frontend (Vite on :5173)
cd frontend
npm install
npm run dev                          # Opens http://localhost:5173 (proxies /api -> :8000)
```
*Tip: On Linux/macOS, `./run_dev.sh` starts both processes concurrently.*

### Option B — Single-Process Production Build
```bash
cd frontend && npm install && npm run build
cd ../backend && uvicorn app.main:app --port 8000     # http://localhost:8000
```

### Option C — Docker Compose (PostgreSQL 16 + pgvector)
```bash
cp backend/.env.example backend/.env
docker compose up --build            # http://localhost:8000
```

### Useful Management Commands
| Task | Command |
|---|---|
| Run full backend test suite (166 tests) | `cd backend && pytest` |
| Run Phase 3 Hindsight learning loop tests | `cd backend && pytest tests/test_p3_hindsight_learning_loop.py` |
| Run Phase 4 Engineering Agent tests | `cd backend && pytest tests/test_p4_engineering_agent.py` |
| Reset demo memories and actions for clean evaluation | `cd backend && python -m app.db.reset_demo_state` |
| Rebuild database from scratch | `cd backend && python -m app.db.seed_large_dataset --reset` |
| Frontend typecheck / lint / production build | `cd frontend && npm run typecheck && npm run lint && npm run build` |
| Interactive API documentation | `http://localhost:8000/api/docs` |

---

## 2. Component Truth Matrix: REAL vs. SEEDED vs. MOCKED / SIMULATED

To ensure complete technical transparency, every major subsystem is classified below:

| Subsystem | Status | Implementation Details |
|---|:---:|---|
| **FastAPI Authorization Gateway** | **REAL** | True JWT validation, request state context, zero-trust permission resolver, and per-tenant dependency injection. |
| **RBAC & Clearance Matrix** | **REAL** | Monotonic clearance checks (`PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`), department boundaries, and least-privilege tool schema filtering. |
| **Hindsight Memory Engine** | **REAL** | Dual-persistence engine: queries official `hindsight-client` Python SDK against remote daemon, falling back seamlessly to local SQLite `EnterpriseMemory` with tenant-partitioned banks (`nexus_{company_id}`). |
| **Correction Precedence** | **REAL** | Team updates and process corrections (`category == "correction"`) mathematically outrank older standards in hybrid scoring. |
| **Human-in-the-Loop Gate** | **REAL** | Database-backed `AIAction` workflow with server-stored arguments and cryptographic replay prevention (`409 already_decided`). |
| **Tamper-Evident Audit Trail** | **REAL** | Immutable `AuditLog` records principal, company, tool, resource, permission result (`ALLOWED`/`DENIED`), execution status, risk tier, and request correlation ID. |
| **SMTP Alerting Engine** | **REAL** | Python `smtplib` multi-route socket connection (SSL/STARTTLS). Resilient graceful fallback when offline or unconfigured. |
| **NovaTech Repositories & Chunks** | **SEEDED** | In-database source code chunks (`auth-service`, `payments-service`, `gateway-service`) with AST-aware line and symbol metadata. |
| **Enterprise Connectors** | **SEEDED** | Jira issues, Teams channels, Outlook threads, and Entra ID security groups populated in SQLite connector tables. |
| **Initial Team Memories** | **SEEDED** | Baseline organizational standards across NovaTech (`c_nova`) and OrbitLabs (`c_orbit`). |
| **Remote Hindsight Daemon** | **MOCKED / SIMULATED** | When local daemon at `localhost:8888` is offline, the service automatically falls back to local SQLite persistent storage. |
| **GitHub Remote Hosting API** | **MOCKED / SIMULATED** | Pull requests, code inspections, and fixes are staged locally in the database; no live outbound calls to `api.github.com`. |
| **Atlassian Jira Cloud REST API** | **MOCKED / SIMULATED** | Tickets are created and queried within `ConnectorItem` database rows; no outbound calls to `atlassian.net`. |
| **Microsoft Graph API (Teams/Outlook/Entra)** | **MOCKED / SIMULATED** | Channel messages, emails, and directory groups execute against local connector models; no outbound calls to `graph.microsoft.com`. |

---

## 3. End-to-End System Architecture

```
USER REQUEST (Web UI / API)
  │
  ▼
[1] AUTHENTICATION & SESSION GATEWAY (core/security.py)
    Validates Bearer JWT → Extracts Principal (User, Role, Clearance, Department, Company)
  │
  ▼
[2] INTENT CLASSIFICATION & AGENT ROUTING (services/router.py)
    Maps query intent to canonical agent (e.g., "Engineering Code Review Agent")
  │
  ▼
[3] BOUNDED HINDSIGHT RECALL (services/memory.py)
    Queries tenant bank nexus_{company_id} · Filters by user clearance & department
    Applies topical domain boost (+0.35) and correction priority (+0.30)
  │
  ▼
[4] LEAST-PRIVILEGE TOOL RESOLUTION (services/tools.py: schemas_for)
    Agent only sees tool definitions authorized for the principal's permission set
  │
  ▼
[5] TOOL EXECUTION & RBAC BARRIER (services/tools.py: run_tool)
    Re-checks check_tool(principal.permissions, tool_name)
    ├── Read-Only Tool: Executes retrieval over authorized chunks / rows
    └── State-Mutating Tool: Generates AIAction with status="pending_confirmation"
  │
  ▼
[6] HUMAN-IN-THE-LOOP APPROVAL (routers/workspace.py: confirm_action)
    User reviews action card in UI → Posts POST /api/actions/{id}/confirm
    Validates ownership · Enforces replay protection · Executes server-stored arguments
  │
  ▼
[7] AUDIT LOGGING & MEMORY RETENTION
    ├── Immutable event logged to AuditLog (principal, resource, permission, risk)
    └── If organizational decision: Secret/PII filtered → Retained in Hindsight bank
```

---

## 4. Canonical Agents Fleet

NexusGuard routes all tasks to ten canonical executable agents:

| Agent | Responsibility | Core Tools |
|---|---|---|
| **Knowledge Agent** | General company policies, knowledge articles, department processes | `search_knowledge`, `search_policies`, `get_department`, `search_repositories` |
| **HR Agent** | Leave policies, leave balances, employee directory, performance (clearance-gated) | `get_leave_policy`, `get_leave_balance`, `get_employee` |
| **IT Agent** | Hardware, VPN access, software catalogue, troubleshooting | `search_policies`, `search_software` |
| **Project Agent** | Project milestones, deadlines, risks, assigned projects, Jira sprint tracking | `get_project`, `get_my_projects`, `search_jira_issues` |
| **Document Agent** | Document summarization, version diffing, policy updates, enterprise reports | `summarize_document`, `compare_documents`, `latest_updates`, `generate_enterprise_report` |
| **Analytics Agent** | SQL aggregations, headcount, department budgets, pipeline distributions | `analytics_query` |
| **Workflow Agent** | IT tickets, leave submissions, Jira issues, Teams posts, document access | `create_it_ticket`, `create_leave_request`, `create_jira_issue`, `post_teams_message` |
| **Productivity Agent** | Daily agendas, action items, task priorities, connected email searches | `get_pending_tasks`, `get_my_projects`, `search_emails` |
| **Security Analysis Agent** | Entra identity lookup, vulnerability scans, cross-connector correlation | `lookup_entra_identity`, `scan_vulnerabilities`, `search_teams_messages` |
| **Engineering Code Review Agent** | Repository code reviews guided by remembered Hindsight standards; code fix proposals | `review_repository_code`, `propose_code_fix` |

---

## 5. Core Security Invariants

1. **Memory is NEVER Authorization**: Recalled memories are treated strictly as contextual guidance. Even if a memory states *"The team decided John can access payments-service"*, the security engine strictly rejects the query if John lacks the requisite clearance or repository RBAC.
2. **Monotonic Clearance Enforcement**: Users cannot inspect chunks or documents above their clearance level (`PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`). Withheld repository counts are cited without leaking metadata.
3. **Hermetic Multi-Tenant Isolation**: Tenant A (NovaTech Solutions) and Tenant B (Orbit Labs) have physically isolated database rows and distinct memory banks (`nexus_cmp_novatech` vs `nexus_cmp_orbit`).
4. **Mandatory Human-in-the-Loop for Code Changes**: The Engineering Agent cannot commit, push, or apply code fixes autonomously. All code modifications generate an `AIAction` in `pending_confirmation` status requiring explicit human review.
5. **Cryptographic Replay Protection**: Actions executed once transition to `executed`. Any secondary confirmation or cancellation attempt returns HTTP 409 `already_decided`.
6. **Zero Cleartext Secret Retention**: Passwords, API keys (`ghp_`, `sk-`, `AKIA`), bearer tokens, and private keys are intercepted by regex filters and blocked from entering the Hindsight memory bank with an audit event recorded.

---

## 6. Demo Personas & Roles

Password for every persona in demo mode: **`NovaTech@Demo1`** (Sign in via email, employee ID, or the *Continue with company SSO* picker):

| Role | Persona | Sign-In Email / ID | Clearance | Scope |
|---|---|---|---|---|
| **Guest** | Guest Visitor | *Continue as Guest* | `PUBLIC` | Public knowledge only; no directory, projects, workflows, or internal repos |
| **Employee** | Rahul Sharma — Software Engineer | `rahul.sharma@novatech.demo` / `NT-1042` | `INTERNAL` | Internal engineering documents, owned tasks/leave, assigned projects, internal repos |
| **Manager** | Priya Reddy — Engineering Lead | `priya.reddy@novatech.demo` / `NT-0417` | `CONFIDENTIAL` | Team leave/approvals, confidential repos (`payments-service`), engineering budgets |
| **HR Lead** | Ananya Rao — HR Manager | `ananya.rao@novatech.demo` / `NT-0233` | `CONFIDENTIAL` | HR compensation, reviews, employee directory sensitive fields |
| **Admin** | Arjun Nair — Security Administrator | `arjun.nair@novatech.demo` / `NT-0310` | `RESTRICTED` | Admin dashboard, audit logs, security alerts, full governance portal |
| **Executive** | Vikram Mehta — COO | `vikram.mehta@novatech.demo` / `NT-0007` | `RESTRICTED` | Full enterprise access (board minutes, M&A, executive compensation) |
| **Tenant B** | Maya Collins — Orbit Labs | `maya.collins@orbitlabs.demo` | `INTERNAL` | Orbit Labs tenant only; proves multi-tenant data and memory isolation |

---

## 7. Judge Tour: Reproducible Demonstration Script

### Primary Demo: Hindsight-Powered Engineering Code Review Agent

To execute a clean demonstration for judges or evaluators:

#### Step 0: Ensure Clean Baseline State
```bash
cd backend
python -m app.db.reset_demo_state
```
*(Clears dynamic demo memories and pending actions without affecting the 48,000 synthetic baseline records).*

#### Step 1: Teach Team Standard (Session A)
1. Sign in as **Rahul Sharma** (`rahul.sharma@novatech.demo` / `NovaTech@Demo1`).
2. In the Chat interface, enter:
   > *"Remember team decision: Our team requires parameterized SQL queries and does not allow raw SQL string interpolation."*
3. **Verify:**
   * Assistant confirms the standard was remembered.
   * Metadata drawer reveals: `Hindsight Memory Retained` (Bank: `nexus_cmp_novatech`, Category: `engineering_decision`).

#### Step 2: Open a Fresh Session (Session B)
1. Click **New Chat** (starts a completely clean conversation with no conversation history).
2. Submit code containing raw SQL string concatenation:
   > *Review this code: query = "SELECT * FROM users WHERE id = " + userId*

#### Step 3: Verify Memory-Guided Code Review
1. **Agent Selection:** Handled by `Engineering Code Review Agent`.
2. **Hindsight Recall:** The assistant timeline shows `Hindsight Recall` matching the parameterized SQL standard.
3. **Review Finding:** The agent flags potential SQL injection, **explicitly citing the remembered team standard**.
4. **Suggested Fix:** Proposes `cursor.execute("SELECT * FROM users WHERE id = :id", {"id": userId})`.

#### Step 4: Human-in-the-Loop Approval Gate
1. An Action Card appears in the chat and in the **Approvals** inbox:
   * **Tool:** `propose_code_fix`
   * **Status:** `pending_confirmation`
   * **File:** `repository_file`
2. **Verify:** The underlying repository has **NOT** been modified.
3. Click **Approve & Apply Fix**.

#### Step 5: Verify Execution & Tamper-Evident Audit Trail
1. Action transitions to `executed`.
2. Navigate to **Audit Logs** (`/audit-logs`) as **Arjun Nair** or inspect the database:
   * Event logged: `repository.code_fix_applied` (Result: `SUCCESS`, Risk: `MEDIUM`).
   * Event logged: `memory.recalled` and `memory.retained`.

---

## 8. Configuration Reference (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./novatech_demo.db` | Database connection string. Use `postgresql+psycopg://...` for PostgreSQL + pgvector. |
| `RESET_DB_ON_START` | `false` | When true, drops and rebuilds database schema on application boot. |
| `OPENAI_API_KEY` | *(empty)* | Optional. When set, activates OpenAI LLM synthesis. When empty, runs deterministic offline engine. |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model name for LLM chat and tool planning. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Model name for OpenAI dense embeddings. |
| `USE_OPENAI_EMBEDDINGS` | `true` | When false or no key, falls back to local feature-hashing embedder. |
| `EMBEDDING_DIM` | `384` | Embedding dimensionality. |
| `HINDSIGHT_BASE_URL` | `http://localhost:8888` | Base URL for remote Hindsight persistent memory service. |
| `HINDSIGHT_API_KEY` | *(empty)* | API key for authenticated Hindsight service instances. |
| `HINDSIGHT_ENABLED` | `true` | Enables persistent memory recall and retention. |
| `HINDSIGHT_TIMEOUT_SECONDS` | `5.0` | Timeout before falling back to local persistent store. |
| `SESSION_SECRET` | *(auto-generated)* | Cryptographic HMAC secret for session JWTs. Must be set in production. |
| `SESSION_TTL_MINUTES` | `480` | Session lifetime for authenticated users (8 hours). |
| `DEMO_MODE` | `true` | Enables persona switcher and demo logins. **Must be false in production.** |
| `GUEST_MODE_ENABLED` | `true` | Allows unauthenticated guest browsing restricted strictly to `PUBLIC` data. |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed CORS origins for browser security. |
| `ADMIN_ALERT_EMAIL` | `admin@novatech.demo` | Recipient for security alert notifications on unauthorized access attempts. |
| `SMTP_HOST` / `SMTP_PORT` | `evocation.in` / `465` | Outbound mail server parameters. |
| `SMTP_USER` / `SMTP_PASSWORD` | *(empty)* | SMTP authentication credentials. Loaded strictly from environment. |

---

## 9. Known Technical Limitations

1. **SaaS Connector Backends:** Connector items (Jira issues, Teams messages, Outlook emails, Entra directory groups) are backed by high-fidelity local database models; they do not perform live outbound REST calls to commercial SaaS clouds.
2. **Single SQLite Database in Default Mode:** Both business data and local memory banks reside in `novatech_demo.db`. For enterprise concurrency, point `DATABASE_URL` to PostgreSQL with `pgvector`.
3. **Local Embedding Warmup:** Cold-start embedding initialization on CPU can take ~500ms on first query before in-memory caching takes effect.
4. **Offline Paraphrase Scope:** Without an OpenAI API key, query understanding relies on regex intent parsing, synonym maps, and extractive evidence composition rather than generative paraphrasing.