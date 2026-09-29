"""NexusGuard Persistent Enterprise Memory Service powered by Hindsight (Vectorize).

Integrates official Hindsight Python SDK (hindsight-client) with NexusGuard's
multi-tenant RBAC, clearance tiers, department scopes, and audit logging.

Memory lifecycle:
  USER QUERY
      ↓
  Security Guardrails (Prompt injection / exfiltration scan)
      ↓
  Hindsight RECALL (tenant-scoped bank -> clearance & department pre-filter)
      ↓
  Agent / LLM reasoning (injected via <recalled_enterprise_memory>)
      ↓
  Tools / Actions executed
      ↓
  Hindsight RETAIN (policy-governed persistence of decisions/preferences/corrections)
      ↓
  Audit trail recorded
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session as DBSession

from ..config import get_settings
from ..core.rbac import LEVELS, allowed_levels, is_guest, norm_level
from ..core.security import Principal
from ..db.models import EnterpriseMemory, new_id
from . import audit
from .embeddings import tokenize
from .guard import redact, scan_injection

log = logging.getLogger("novatech.memory")
settings = get_settings()

try:
    from hindsight_client import Hindsight
    HINDSIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    Hindsight = None
    HINDSIGHT_AVAILABLE = False
    log.warning("hindsight-client package not found; memory will operate in local persistence mode.")


# Directives that trigger automatic memory retention
RETENTION_PATTERNS = [
    # Corrections / Process updates to the agent (Highest Priority)
    (r"\b(?:we changed our process|process change|new process|updated process|new standard|process update)\s*[:\-\.]?\s*(.+)", "correction"),
    (r"\b(?:correction|that's wrong|don't do that|actually(?:,\s*we)?|instead of .* use)\s*[:\-]?\s*(.+)", "correction"),
    # Team / Engineering decisions
    (r"\b(?:remember(?:\s+that)?|team decision|we decided|engineering decision|architecture decision|rule for (?:this|our))\s*[:\-]?\s*(.+)", "engineering_decision"),
    # Preferences / Conventions / Workflow rules
    (r"\b(?:for\s+(?:all\s+)?(?:[\w\-]+\s+)*(?:tickets?|issues?|requests?|reviews?|prs?|tasks?)|when creating\s+[\w\-\s]+|our team prefers?|always use|never use|for future (?:requests?|reviews?|prs?|tasks?))\s*[:\-,]?\s*(.+)", "user_preference"),
    (r"\b(?:(?:security|engineering|support|it|devops)[\w\-\s]*?(?:tickets?|issues?|requests?)\s+should\s+(?:now\s+|always\s+)?(?:go to|use|be assigned to|be)\s+.+)", "user_preference"),
    (r"\b(?:(?:prefer|set|use)\s+(?:high|low|medium|critical)\s+priority\s+for\s+.+)", "user_preference"),
    # Policy / Compliance decisions
    (r"\b(?:company policy requires?|compliance rule|standard for (?:all|our))\s*[:\-]?\s*(.+)", "organizational_policy"),
]


@dataclass
class MemoryItem:
    id: str
    text: str
    category: str  # engineering_decision | user_preference | organizational_policy | workflow_decision | correction
    clearance: str  # PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED
    department: str
    user_id: str
    creator_name: str
    tags: list[str] = field(default_factory=list)
    score: float = 1.0
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HindsightMemoryService:
    """Enterprise Memory Manager integrating Hindsight (Vectorize) SDK

    with deterministic RBAC, tenant isolation, and resilient fallback.
    """

    _client: Any = None
    _client_initialized: bool = False
    _status: str = "uninitialized"

    @classmethod
    def get_client(cls) -> Any:
        """Returns initialized Hindsight client instance or None."""
        if not cls._client_initialized:
            if HINDSIGHT_AVAILABLE and settings.hindsight_enabled:
                try:
                    cls._client = Hindsight(
                        base_url=settings.hindsight_base_url,
                        api_key=settings.hindsight_api_key,
                        timeout=settings.hindsight_timeout_seconds,
                    )
                    cls._status = "connected"
                    log.info("Initialized Hindsight SDK client pointing to %s", settings.hindsight_base_url)
                except Exception as exc:
                    cls._client = None
                    cls._status = f"degraded: {type(exc).__name__}"
                    log.warning("Failed to initialize Hindsight client: %s; using local persistent store", exc)
            else:
                cls._status = "local_persistent"
            cls._client_initialized = True
        return cls._client

    @classmethod
    def get_status(cls, db: DBSession | None = None, company_id: str | None = None) -> dict[str, Any]:
        """Provides health, mode, and storage statistics for administration and UI."""
        cls.get_client()
        total_memories = 0
        if db and company_id:
            try:
                total_memories = db.scalar(
                    select(func.count(EnterpriseMemory.id)).where(EnterpriseMemory.company_id == company_id)
                ) or 0
            except Exception:
                pass
        return {
            "hindsight_sdk_available": HINDSIGHT_AVAILABLE,
            "hindsight_enabled": settings.hindsight_enabled,
            "base_url": settings.hindsight_base_url,
            "status": cls._status,
            "total_memories": total_memories,
            "tenant_bank": f"nexus_{company_id}" if company_id else None,
        }

    @classmethod
    def bank_for_tenant(cls, company_id: str) -> str:
        """Ensures strict multi-tenant bank isolation in Hindsight."""
        clean_tenant = re.sub(r"[^a-zA-Z0-9_\-]", "_", company_id)
        return f"nexus_{clean_tenant}"

    @classmethod
    def should_retain_directive(cls, text: str) -> tuple[bool, str, str]:
        """Inspects user input for memorable directives, decisions, or corrections.

        Returns (should_retain, category, extracted_content).
        """
        cleaned = text.strip()
        # Secret protection: Never automatically retain messages containing raw credentials or secrets
        if re.search(r"\b(?:password|passwd|api[_\-\s]?key|secret[_\-\s]?key|bearer\s+[a-zA-Z0-9_\-\.]{15,}|ghp_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9_\-]{20,}|AKIA[0-9A-Z]{16})\b", cleaned, re.I):
            return False, "rejected_secret", ""

        for rx, category in RETENTION_PATTERNS:
            match = re.search(rx, cleaned, re.I)
            if match:
                extracted = match.group(1).strip() if match.groups() else match.group(0).strip()
                if len(extracted) >= 8:  # ignore trivial single words
                    # Return the full informative sentence if it provides complete context
                    full_content = cleaned if len(cleaned) <= 240 and not cleaned.lower().startswith("remember") else extracted
                    return True, category, full_content
        return False, "decision", ""

    @classmethod
    def retain(
        cls,
        db: DBSession,
        principal: Principal,
        content: str,
        *,
        category: str = "engineering_decision",
        clearance: str = "INTERNAL",
        department: str = "*",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        """Stores an organizational decision, user preference, or correction in Hindsight.

        Strictly enforces tenant isolation, secret scanning, injection checking, and DLP.
        """
        # 1. Tenant & Guest boundary
        if is_guest(principal) and clearance != "PUBLIC":
            raise PermissionError("Guests can only retain public feedback or non-sensitive notes.")

        # 2. Input Security: Never store prompt injection attacks
        inj = scan_injection(content)
        if inj.detected:
            audit.record(
                db,
                principal=principal,
                action="memory.poisoning_attempt_blocked",
                resource="Hindsight Memory Bank",
                query=content,
                permission_result="BLOCKED",
                result="BLOCKED",
                risk="HIGH",
                reason=f"Attempted to retain prompt injection into memory ({inj.summary()})",
                commit=True,
                request_id=request_id,
            )
            raise ValueError(f"Memory retention rejected: suspected prompt injection ({inj.summary()})")

        # 3. Secret Protection: Never store raw passwords, tokens, API keys, or private credentials
        if re.search(r"\b(?:password\s*[:=]\s*\S+|passwd\s*[:=]\s*\S+|api[_\-\s]?key\s*[:=]\s*\S+|secret[_\-\s]?key\s*[:=]\s*\S+|bearer\s+[a-zA-Z0-9_\-\.]{15,}|ghp_[a-zA-Z0-9]{20,}|sk-[a-zA-Z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY)\b", content, re.I):
            audit.record(
                db,
                principal=principal,
                action="memory.secret_retention_blocked",
                resource="Hindsight Memory Bank",
                query="[REDACTED_SECRET]",
                permission_result="BLOCKED",
                result="BLOCKED",
                risk="HIGH",
                reason="Attempted to store credentials, passwords, or tokens in enterprise memory",
                commit=True,
                request_id=request_id,
            )
            raise ValueError("Memory retention rejected: credentials, tokens, or passwords cannot be stored in memory.")

        redacted_content = redact(content).text

        # 4. Normalize metadata and tags
        req_cls = norm_level(clearance)
        tag_list = list(tags or [])
        tag_list.extend([
            f"tenant:{principal.company_id}",
            f"user:{principal.user_id}",
            f"category:{category}",
            f"clearance:{req_cls}",
            f"dept:{department or principal.department}",
        ])
        tag_list = list(dict.fromkeys(tag_list))

        meta = dict(metadata or {})
        meta.update({
            "creator_id": principal.user_id,
            "creator_name": principal.full_name,
            "creator_role": principal.role_name,
            "creator_department": principal.department,
            "creator_clearance": principal.clearance,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "category": category,
        })

        bank_id = cls.bank_for_tenant(principal.company_id)
        hindsight_id = None

        # 5. Call official Hindsight Client
        client = cls.get_client()
        if client and settings.hindsight_enabled:
            try:
                # Convert string metadata to strings for Hindsight API compatibility
                string_metadata = {k: str(v) for k, v in meta.items()}
                res = client.retain(
                    bank_id=bank_id,
                    content=redacted_content,
                    tags=tag_list,
                    metadata=string_metadata,
                )
                hindsight_id = getattr(res, "operation_id", None) or (res.operation_ids[0] if getattr(res, "operation_ids", None) else None)
                cls._status = "connected"
                log.info("Successfully retained memory to Hindsight bank %s (op_id=%s)", bank_id, hindsight_id)
            except Exception as exc:
                cls._status = f"degraded: {type(exc).__name__}"
                log.warning("Hindsight remote retain failed (%s); using local persistent memory store", exc)

        # 6. Always persist in NexusGuard enterprise database for persistence & auditability
        mem_record = EnterpriseMemory(
            id=new_id("mem_"),
            company_id=principal.company_id,
            user_id=principal.user_id,
            bank_id=bank_id,
            content=redacted_content,
            category=category,
            clearance=req_cls,
            department=department or principal.department,
            tags=tag_list,
            metadata_json=meta,
            hindsight_id=hindsight_id or new_id("hs_"),
        )
        db.add(mem_record)
        db.commit()

        # 7. Audit log the memory creation
        audit.record(
            db,
            principal=principal,
            action="memory.retain",
            resource=f"Memory ({category})",
            resource_id=mem_record.id,
            classification=req_cls,
            permission_result="ALLOWED",
            result="SUCCESS",
            reason=f"Retained {category.replace('_', ' ')} in Hindsight bank {bank_id}",
            risk="LOW" if req_cls in ("PUBLIC", "INTERNAL") else "MEDIUM",
            details={
                "memory_id": mem_record.id,
                "category": category,
                "hindsight_id": mem_record.hindsight_id,
                "tags": tag_list,
            },
            commit=True,
            request_id=request_id,
        )

        return {
            "id": mem_record.id,
            "bank_id": bank_id,
            "content": mem_record.content,
            "category": mem_record.category,
            "clearance": mem_record.clearance,
            "department": mem_record.department,
            "tags": mem_record.tags,
            "hindsight_id": mem_record.hindsight_id,
            "created_at": mem_record.created_at.isoformat(),
        }

    @classmethod
    def recall(
        cls,
        db: DBSession,
        principal: Principal,
        query: str,
        *,
        limit: int = 4,
        category: str | None = None,
        min_score: float = 0.20,
        request_id: str = "",
    ) -> list[MemoryItem]:
        """Recalls relevant memories from Hindsight.

        Applies strict NexusGuard pre-retrieval RBAC:
        - Tenant Isolation: Query restricted to principal.company_id
        - Clearance: Only levels within allowed_levels(principal)
        - Department: User's department or wildcard '*'
        - User Scoping: Private preferences restricted to owning user_id
        """
        bank_id = cls.bank_for_tenant(principal.company_id)
        user_allowed_levels = set(allowed_levels(principal))
        recalled_items: list[MemoryItem] = []

        # 1. Attempt Recall via official Hindsight Client
        client = cls.get_client()
        remote_success = False
        if client and settings.hindsight_enabled:
            try:
                tags_filter = None
                if category:
                    tags_filter = [f"category:{category}"]
                res = client.recall(
                    bank_id=bank_id,
                    query=query,
                    tags=tags_filter,
                    max_tokens=2048,
                )
                if hasattr(res, "results") and res.results:
                    for r in res.results:
                        meta = getattr(r, "metadata", {}) or {}
                        mem_clearance = norm_level(meta.get("creator_clearance", meta.get("clearance", "INTERNAL")))
                        mem_dept = meta.get("creator_department", meta.get("dept", "*"))
                        mem_user_id = meta.get("creator_id", "")
                        mem_category = meta.get("category", getattr(r, "type", "decision"))

                        # Security check on recalled memory
                        if mem_clearance not in user_allowed_levels:
                            continue
                        if mem_dept != "*" and principal.department != "*" and mem_dept.lower() not in (principal.department.lower(), "*"):
                            continue
                        if mem_category == "user_preference" and mem_user_id and mem_user_id != principal.user_id:
                            continue

                        recalled_items.append(
                            MemoryItem(
                                id=getattr(r, "id", new_id("hs_")),
                                text=getattr(r, "text", ""),
                                category=mem_category,
                                clearance=mem_clearance,
                                department=mem_dept,
                                user_id=mem_user_id,
                                creator_name=meta.get("creator_name", "Team Member"),
                                tags=getattr(r, "tags", []) or [],
                                score=0.95,
                                created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                                metadata=meta,
                            )
                        )
                    remote_success = True
                    cls._status = "connected"
            except Exception as exc:
                cls._status = f"degraded: {type(exc).__name__}"
                log.warning("Hindsight remote recall failed (%s); querying local persistent memory bank", exc)

        # 2. Local Persistent Store Fallback / Primary (ensures cross-session persistence in all environments)
        if not remote_success or len(recalled_items) == 0:
            query_tokens = set(tokenize(query.lower()))
            stmt = select(EnterpriseMemory).where(
                EnterpriseMemory.company_id == principal.company_id,
                EnterpriseMemory.clearance.in_(user_allowed_levels),
            )
            if category:
                stmt = stmt.where(EnterpriseMemory.category == category)

            records = db.scalars(stmt.order_by(EnterpriseMemory.created_at.desc())).all()
            for rec in records:
                # Department check
                rec_dept = str(rec.department or "*").lower()
                p_dept = str(principal.department or "*").lower()
                if rec_dept != "*" and p_dept != "*" and rec_dept not in (p_dept, "*"):
                    continue
                # Personal preference isolation
                if rec.category == "user_preference" and rec.user_id != principal.user_id:
                    continue

                # Hybrid match score: token overlap + recency bonus + correction priority
                content_tokens = set(tokenize(rec.content.lower()))
                if not query_tokens:
                    score = 0.5
                else:
                    overlap = len(query_tokens & content_tokens)
                    score = overlap / max(1, len(query_tokens))
                    # Phrase boost
                    if any(t in rec.content.lower() for t in query.lower().split() if len(t) >= 4):
                        score += 0.25
                    # Correction boost: Process changes and corrections take precedence over older preferences
                    # only when the memory has some topical relevance to the query
                    has_topic_match = overlap > 0 or any(t in rec.content.lower() for t in query.lower().split() if len(t) >= 4)
                    if has_topic_match and (rec.category == "correction" or "changed" in rec.content.lower()):
                        score += 0.30

                if score >= min_score or not query.strip():
                    recalled_items.append(
                        MemoryItem(
                            id=rec.id,
                            text=rec.content,
                            category=rec.category,
                            clearance=rec.clearance,
                            department=rec.department,
                            user_id=rec.user_id,
                            creator_name=rec.metadata_json.get("creator_name", "Team Member"),
                            tags=rec.tags or [],
                            score=round(min(1.0, score), 3),
                            created_at=rec.created_at.isoformat() if rec.created_at else "",
                            metadata=rec.metadata_json or {},
                        )
                    )

        # Sort by score descending and truncate to limit
        recalled_items.sort(key=lambda m: m.score, reverse=True)
        final_recalled = recalled_items[:limit]

        # Audit recall if memories were provided to the model
        if final_recalled:
            audit.record(
                db,
                principal=principal,
                action="memory.recall",
                resource="Hindsight Memory Bank",
                query=query,
                permission_result="ALLOWED",
                result="SUCCESS",
                reason=f"Recalled {len(final_recalled)} memories from Hindsight bank {bank_id}",
                risk="LOW",
                details={
                    "count": len(final_recalled),
                    "memory_ids": [m.id for m in final_recalled],
                    "categories": [m.category for m in final_recalled],
                },
                commit=False,
                request_id=request_id,
            )

        return final_recalled

    @classmethod
    def list_memories(
        cls,
        db: DBSession,
        principal: Principal,
        *,
        limit: int = 50,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lists authorized memories for admin observability and UI."""
        user_allowed_levels = set(allowed_levels(principal))
        stmt = select(EnterpriseMemory).where(
            EnterpriseMemory.company_id == principal.company_id,
            EnterpriseMemory.clearance.in_(user_allowed_levels),
        )
        if category:
            stmt = stmt.where(EnterpriseMemory.category == category)
        recs = db.scalars(stmt.order_by(EnterpriseMemory.created_at.desc()).limit(limit)).all()

        results = []
        for r in recs:
            if r.category == "user_preference" and r.user_id != principal.user_id:
                continue
            results.append({
                "id": r.id,
                "content": r.content,
                "category": r.category,
                "clearance": r.clearance,
                "department": r.department,
                "tags": r.tags,
                "creator_name": r.metadata_json.get("creator_name", "Unknown"),
                "creator_id": r.user_id,
                "hindsight_id": r.hindsight_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return results

    @classmethod
    def delete_memory(cls, db: DBSession, principal: Principal, memory_id: str) -> bool:
        """Deletes a memory record with permission checks."""
        mem = db.get(EnterpriseMemory, memory_id)
        if not mem or mem.company_id != principal.company_id:
            return False

        # Only creator, Security Admin, or Executive can delete
        if mem.user_id != principal.user_id and principal.role_name not in ("Security Administrator", "Administrator", "Executive"):
            raise PermissionError("You can only delete your own memories or require Administrator privileges.")

        db.delete(mem)
        db.commit()

        audit.record(
            db,
            principal=principal,
            action="memory.delete",
            resource=f"Memory ({mem.category})",
            resource_id=mem.id,
            permission_result="ALLOWED",
            result="SUCCESS",
            reason=f"Deleted {mem.category} from Hindsight memory bank",
            risk="LOW",
            commit=True,
        )
        return True

    @classmethod
    def format_memories_for_prompt(cls, memories: list[MemoryItem]) -> str:
        """Formats recalled memories into an authoritative XML context block for the agent."""
        if not memories:
            return ""

        lines = [
            "<recalled_enterprise_memory>",
            "The following organizational decisions, architecture standards, and user preferences were RECALLED from Hindsight persistent memory.",
            "Prioritize these team standards and preferences when answering questions, reviewing code, or proposing actions:",
        ]
        for idx, m in enumerate(memories, start=1):
            cat_label = m.category.replace("_", " ").title()
            lines.append(
                f'{idx}. [{cat_label}] (by {m.creator_name}, {m.department} dept, clearance {m.clearance}):\n   "{m.text}"'
            )
        lines.append("</recalled_enterprise_memory>")
        return "\n".join(lines)


# Singleton alias
memory_service = HindsightMemoryService
