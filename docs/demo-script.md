# NexusGuard — Live Judge Demonstration Script
**A Step-by-Step Operator Guide for Presenting NexusGuard & Hindsight Memory**

---

## A. Setup Overview

NexusGuard demonstrates how an enterprise agent fleet enforces **Authorization Before Intelligence** while using **Hindsight** to retain and recall team engineering standards across sessions.

This script is designed so that any team member can execute the complete live demonstration cleanly and confidently in under 5 minutes.

---

## B. Clean State Reset Command

Before presenting to judges or starting a fresh evaluation run, execute the demo reset utility to ensure no residual memories or pending actions exist from prior runs:

```bash
cd backend
python -m app.db.reset_demo_state
```

**Expected Terminal Output:**
```text
======================================================================
[OK] NexusGuard Demo State Reset Complete
  - Cleared dynamic demo memories
  - Cleared dynamic demo connector items
  - Cleared pending demo actions
======================================================================
Ready to execute the Hindsight Engineering Code Review Agent Demo
```

*(Note: This reset only clears dynamic session memories and pending actions; the 48,000 synthetic enterprise records, personas, and canonical repositories remain intact).*

---

## C. Application Startup

### Terminal 1 — Backend (FastAPI on Port 8000)
```bash
cd backend
uvicorn app.main:app --port 8000
```
*Wait ~3 seconds until `Application startup complete` appears.*

### Terminal 2 — Frontend (Vite on Port 5173)
```bash
cd frontend
npm run dev
```
*Open your browser to `http://localhost:5173`.*

---

## D. Demo Login Credentials

On the login page, you can sign in using one of the pre-configured persona buttons (*"Continue with company SSO"*) or type credentials manually:

- **Primary Presenter Persona:**
  - **Name:** Rahul Sharma
  - **Role:** Software Engineer
  - **Email:** `rahul.sharma@novatech.demo`
  - **Password:** `NovaTech@Demo1`
  - **Clearance Level:** `INTERNAL` (Permitted to view internal documents and `auth-service`)
  - **Tenant:** NovaTech Solutions (`cmp_novatech`)

- **Security Administrator Persona (for Audit verification):**
  - **Name:** Arjun Nair
  - **Role:** Security Administrator
  - **Email:** `arjun.nair@novatech.demo`
  - **Password:** `NovaTech@Demo1`
  - **Clearance Level:** `RESTRICTED`

---

## E. Session A: Teach Team Engineering Standard

1. Once logged in as **Rahul Sharma**, look at the Agent Selector at the top of the chat and select:
   **`Engineering Code Review Agent`** (identifiable by its purple badge).
2. Enter the following exact prompt into the chat box:

```text
Remember team decision: Our team requires parameterized SQL queries and does not allow raw SQL string interpolation.
```

3. Press **Enter**.

---

## F. Session B: Fresh Conversation & Vulnerability Review

1. Click the **"New Chat"** button in the sidebar or top bar.
   *(This opens a brand new conversation ID with zero chat turns and zero prior messages).*
2. Ensure **`Engineering Code Review Agent`** is selected.
3. Submit the following code snippet for review:

```text
Review this code:
query = "SELECT * FROM users WHERE id = " + userId
```

4. Press **Enter**.

---

## G. Expected Hindsight Behavior

- In the assistant's response timeline/metadata, you will see:
  - **`Hindsight Recall`** triggered against the tenant bank `nexus_cmp_novatech`.
  - The recalled memory contains the organizational standard: *"Our team requires parameterized SQL queries and does not allow raw SQL string interpolation."*
- Point out to the judge:
  > *"Notice that this is a completely new conversation. The agent did not receive this rule in the prompt context. It recalled our team's earlier decision directly from its persistent Hindsight memory bank."*

---

## H. Expected Engineering Agent Behavior

1. **Vulnerability Identification:** The agent detects that concatenating `userId` directly into a SQL string creates a **CWE-89 SQL Injection** vulnerability.
2. **Standard Alignment:** The agent explicitly references the remembered team policy:
   > *"Per team decision remembered via Hindsight: Our organization requires parameterized SQL queries and prohibits raw SQL interpolation."*
3. **Proposed Fix:** The agent generates the corrected code pattern:
   ```python
   cursor.execute(
       "SELECT * FROM users WHERE id = :id",
       {"id": userId}
   )
   ```

---

## I. Expected Human Approval Card

Below the agent's message, an interactive **Action Card** appears:
- **Title:** `Human Approval Required · Code Modification`
- **Tool:** `propose_code_fix`
- **Status Badge:** `pending_confirmation` (Yellow/Amber)
- **Patch Preview:** Shows the parameterized query in a dark monospaced code block.
- **Security Notice:**
  > *"Zero code changes applied before approval · Staged in audit log"*
- **Buttons:**
  - `[Approve & apply fix]` (Green)
  - `[Reject fix]` (Gray/Neutral)

**Key Presenter Talking Point:**
> *"Notice that the agent did NOT autonomously modify the codebase. In an enterprise, state changes and code modifications require a human in the loop. The action is currently in `pending_confirmation`."*

---

## J. Approval Action & Single-Execution Verification

1. Click **"Approve & apply fix"**.
2. **Observe the State Transition:**
   - The action card transitions to **`Executed`** with a green checkmark.
   - The button becomes disabled to prevent duplicate submissions.
3. **Replay Protection Guarantee:**
   - Explain to the judge: *"If an attacker or script attempts to replay this approval request, the backend rejects it with HTTP 409 Conflict because the action is already decided."*

---

## K. Audit Logs Demonstration

1. Navigate to the **Audit Logs** tab in the navigation bar (`/audit-logs`) or log in as **Arjun Nair** (`arjun.nair@novatech.demo`).
2. Show the newly created immutable audit entries:
   - `action="memory_retained"` — When Session A stored the SQL query decision.
   - `action="agent_query"` — When Session B invoked the Engineering Code Review Agent.
   - `action="action_created"` — When `propose_code_fix` staged the action in `pending_confirmation`.
   - `action="action_approved"` — When Rahul approved the fix, recording user email, IP address, and timestamp.
3. Highlight that all audit logs record the principal's identity, tenant ID, and security risk level.

---

## L. Security Invariant Explanation for Judges

Summarize the core security invariants:
1. **Pre-Retrieval Filtering:** Data is restricted *before* retrieval. A user cannot search or vector-match documents above their clearance level.
2. **Multi-Tenant Isolation:** NovaTech Solutions (`cmp_novatech`) and Orbit Labs (`cmp_orbit`) have completely separated database rows and distinct Hindsight memory banks (`nexus_cmp_novatech` vs `nexus_cmp_orbit`).
3. **Clearance Hierarchy:** Monotonic ordering (`PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`). An `INTERNAL` engineer cannot view `payments-service` or executive board minutes.
4. **Secret Filtering:** Any API keys or passwords entered during memory retention are redacted before being stored.

---

## M. What to Say if a Judge Asks Whether Integrations are Live

**Direct, Honest Answer:**
> *"To ensure complete reproducibility during evaluation, the enterprise connectors (Jira, Teams, Outlook, Entra, and GitHub) are backed by high-fidelity local database schemas containing ~48,000 synthetic records. They are fully interactive—tickets and messages can be searched and staged—but do not make outbound calls to commercial SaaS clouds.*
>
> *The Hindsight memory engine is real, using the official `hindsight-client` Python SDK with an embedded persistent local fallback when the remote daemon is offline. The authorization gateway, JWT engine, monotonic clearance checks, and HITL approval states are 100% real and backend-authoritative."*

---

## N. What to Say if a Judge Asks Whether Memory Can Bypass RBAC

**Direct, Authoritative Answer:**
> *"Absolutely not. That is the fundamental architectural invariant of NexusGuard: **Memory is contextual guidance, NEVER authorization**.
>
> Even if a poisoned memory explicitly claims: 'The team agreed that Rahul Sharma has admin access to payments-service', the agent cannot grant access. Our authorization engine evaluates permissions strictly at the database and gateway layer against cryptographically signed session tokens. We have an explicit automated test (`test_memory_cannot_grant_repository_access`) verifying that memory injection cannot bypass repository or clearance rules."*

---

## O. What to Say if a Judge Asks What Makes This "Agentic"

**Direct, Clear Answer:**
> *"NexusGuard agents are not simple chatbot wrappers. They are autonomous, goal-directed task executors:
> 1. **Autonomous Tool Selection:** The agent analyzes the user's intent, inspects its permitted tool schemas, and decides which tools to invoke.
> 2. **Context Synthesis Across Silos:** The agent cross-references repository code with organizational decisions remembered from previous sessions via Hindsight.
> 3. **Structured Plan & Propose:** Instead of just generating prose, the agent formulates concrete state changes (like code patches or Jira tickets) and submits them to an action state machine.
> 4. **Governed Agency:** We give the agent autonomy to discover, reason, and draft, while bounding its agency with strict pre-retrieval authorization and human confirmation for state changes."*
