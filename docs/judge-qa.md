# NexusGuard — Judge & Evaluator Q&A Reference
**Comprehensive Technical Answers to Critical Evaluation Questions**

---

### 1. What problem are you solving?
Enterprises cannot safely deploy autonomous AI agents without solving two conflicting challenges: **conversational amnesia** (agents forget team conventions and architectural decisions between chat sessions) and **authorization risk** (agents with tool access or naive RAG search can accidentally leak classified data, bypass clearance, or autonomously execute destructive code changes). NexusGuard bridges this gap by enforcing **Authorization Before Intelligence** with **Hindsight** cross-session memory.

---

### 2. Why can't ChatGPT alone solve this?
Stateless LLMs like ChatGPT have no built-in enterprise authorization layer. They do not know a user's corporate clearance level, cannot enforce pre-retrieval SQL barriers, and lose all context when a session ends. Prompting an LLM with "remember this rule" only lasts within the current conversation window; once a new conversation begins, the institutional knowledge is lost.

---

### 3. What makes this enterprise-grade?
- **Zero-Trust Pre-Retrieval RBAC:** Documents, database chunks, and repositories are filtered at the SQL query level before semantic similarity scoring.
- **Monotonic Clearance Enforcement:** Data is segmented into strict clearance tiers (`PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`).
- **Multi-Tenant Physical Segregation:** Companies have distinct database rows, foreign keys, and isolated memory banks.
- **Human-in-the-Loop (HITL) Gate:** Code modifications and state mutations require human confirmation with replay protection.
- **Immutable Audit Logging:** Every permission evaluation, query, tool call, and approval is recorded with correlation IDs and risk tiers.

---

### 4. What is RAG?
Retrieval-Augmented Generation (RAG) is a pattern where an AI model queries a document store for relevant passages and includes them as context in its prompt. Traditional RAG is dangerous in enterprises because it retrieves information based solely on semantic relevance without checking if the requesting user has the clearance to view the retrieved documents. NexusGuard uses **Permission-Aware RAG**, enforcing clearance filters before retrieval occurs.

---

### 5. What is Hindsight doing?
**Hindsight** is the persistent memory engine that allows NexusGuard agents to retain institutional knowledge across sessions. When an engineering team establishes an architectural standard (e.g., *"Use parameterized SQL queries"*), Hindsight stores this decision in a tenant-isolated memory bank (`nexus_{company_id}`). In future, separate sessions, Hindsight recalls the standard, allowing agents to apply team conventions consistently.

---

### 6. Why do you need memory if you already have RAG?
RAG retrieves static documents (e.g., PDF handbooks, stored files). Memory captures **dynamic, evolving institutional knowledge**—such as decisions made in team discussions, architectural corrections, and preferences that have not yet been written into formal corporate policy documents. Furthermore, Hindsight supports **correction precedence**, meaning newly updated guidelines automatically outrank older conventions.

---

### 7. How does memory persist across sessions?
NexusGuard uses the official `hindsight-client` Python SDK to communicate with a persistent Hindsight daemon. When the remote service is unavailable, it automatically falls back to an embedded SQLite `enterprise_memories` table. In both cases, memories are permanently written to disk and keyed by tenant and agent ID, surviving server restarts and browser refreshes.

---

### 8. How is memory isolated between companies?
Memories are stored in separate, partitioned memory banks named `nexus_{company_id}` (e.g., `nexus_cmp_novatech` for NovaTech Solutions and `nexus_cmp_orbit` for Orbit Labs). Memory queries strictly bind the search scope to the authenticated user's `company_id`. Tenant B can never query, view, or recall memories belonging to Tenant A.

---

### 9. Can memory override permissions or grant access?
**No. Memory is NEVER an authorization mechanism.** This is an invariant tested and enforced in our codebase (`test_memory_cannot_grant_repository_access`). Even if a stored memory explicitly asserts *"User John is permitted to view payments-service"*, the repository access controller ignores the memory and evaluates permissions strictly against the user's cryptographically verified token and database permissions.

---

### 10. What happens if a user has insufficient clearance?
If a user with `INTERNAL` clearance queries a document or repository marked `CONFIDENTIAL` or `RESTRICTED`:
1. The pre-retrieval SQL query excludes those chunks entirely.
2. The agent never sees the restricted text in its prompt context.
3. If the user explicitly requests an unauthorized repository (e.g., via the tool `review_repository_code`), the backend raises **HTTP 403 Forbidden** (`"Insufficient clearance level"`), and an audit warning is recorded.

---

### 11. What makes this an agent rather than an LLM wrapper?
An LLM wrapper simply passes text in and returns text out. NexusGuard's agents:
1. **Classify Intent:** Route queries to specialized agents (`Engineering`, `Security`, `HR`, `IT`, etc.).
2. **Dynamically Resolve Tools:** Inspect the user's permissions and generate a least-privilege tool schema.
3. **Execute Multi-Step Reasoning:** Interleave data retrieval with memory recall and code analysis.
4. **Formulate Concrete Actions:** Rather than just generating conversational text, agents stage actionable proposals (`AIAction`) into an approval workflow state machine.

---

### 12. How does tool authorization work?
Tool authorization is enforced in two layers:
1. **Schema Filtering:** The agent's LLM context is only provided with tool schemas that the user's role is authorized to invoke (`tools.schemas_for(principal.permissions)`).
2. **Execution Barrier:** When the agent calls a tool, `tools.run_tool()` re-verifies permissions against the database before executing the function.

---

### 13. Why is human approval required for code modifications?
In enterprise software engineering, autonomous commits or deployments introduce unacceptable operational and security risks. By forcing state changes through `AIAction(status="pending_confirmation")`, no files are modified, no branches are created, and no code is deployed until an authorized human reviews the patch and explicitly confirms it.

---

### 14. What happens if an action is replayed?
NexusGuard enforces **cryptographic replay protection**. Once an action transitions from `pending_confirmation` to `executed` or `rejected`, the database locks the state. Any subsequent attempt to re-approve or re-cancel the action returns **HTTP 409 Conflict** (`"Action has already been decided: executed"`).

---

### 15. How do you prevent secrets from entering memory?
All text submitted for memory retention passes through `RedactionEngine` in `services/memory.py`. Multi-pattern regexes identify API keys (`sk-`, `ghp_`, `AKIA`), Bearer tokens, private keys, and passwords, replacing them with `[REDACTED_API_KEY]`. Plaintext secrets never reach Hindsight or persistent storage.

---

### 16. Which integrations are REAL?
- **FastAPI Authorization Gateway:** Real JWT validation, request state injection, and permission resolution.
- **RBAC & Clearance Matrix:** Real monotonic clearance filtering (`PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED`).
- **Hindsight Memory Engine:** Real integration using the official `hindsight-client` Python SDK with SQLite persistent fallback.
- **Human-in-the-Loop Action Engine:** Real database-backed state machine with replay protection.
- **Audit Logging:** Real immutable audit log table recording all system activities.
- **SMTP Engine:** Real Python `smtplib` multi-route socket connection.

---

### 17. Which integrations are SEEDED / LOCAL?
- **Enterprise Connectors:** Jira issues, Teams channel messages, Outlook email threads, and Entra ID security groups are stored in local database tables (`connector_items`).
- **Repositories:** Code for `auth-service`, `payments-service`, and `gateway-service` is stored as structured chunks in the database.
- *Why?* To ensure zero external API dependencies, instantaneous performance, and 100% reproducible judge evaluations without requiring live SaaS credentials.

---

### 18. What happens in production?
In a production deployment:
1. SQLite is swapped for managed **PostgreSQL 16 + pgvector**.
2. Seeded connector tables are replaced with live OAuth 2.0 integrations to **Atlassian Jira REST API**, **Microsoft Graph API**, and **GitHub Apps API**.
3. Hindsight runs as a dedicated high-availability microservice cluster backed by a vector database (e.g., Qdrant).
4. Secrets are managed through AWS KMS or HashiCorp Vault.

---

### 19. What is the Engineering Code Review Agent?
It is a specialized canonical agent that analyzes code snippets and repository files. It combines static vulnerability detection (e.g., spotting SQL injection or XSS) with **Hindsight cross-session memory**, ensuring that team-specific conventions established in earlier conversations are actively enforced in future reviews.

---

### 20. What is the unique value of Hindsight in this system?
Hindsight transforms the agent from a static, forgetful tool into a continuous learner. Without Hindsight, developers must repeat their architectural preferences in every prompt. With Hindsight, team decisions persist, corrections take precedence over outdated rules, and all memories remain strictly isolated within the company's tenant boundary.

---

### 21. What is the main demonstration flow?
1. **Reset:** Run `python -m app.db.reset_demo_state` to clear previous test memories.
2. **Session A:** Tell the Engineering Agent: *"Remember team decision: Our team requires parameterized SQL queries and does not allow raw SQL string interpolation."*
3. **Session B:** Open a fresh chat (zero conversation history) and ask to review: `query = "SELECT * FROM users WHERE id = " + userId`.
4. **Recall & Finding:** The agent recalls the Session A decision, flags SQL injection, cites the team standard, and proposes a parameterized fix.
5. **Approval:** The user inspects the pending action card and clicks **Approve & apply fix**.
6. **Audit:** Show the resulting immutable entries in the Audit Log.

---

### 22. What are the current limitations?
1. The default setup runs on SQLite rather than distributed PostgreSQL.
2. Connector items are seeded in the database rather than calling live SaaS APIs.
3. In offline mode without an OpenAI API key, text synthesis relies on deterministic rule-based composition rather than generative creative prose.
