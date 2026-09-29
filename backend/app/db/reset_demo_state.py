"""Reset demo state for a clean Hindsight Engineering Agent demonstration.

Usage:
    cd backend
    python -m app.db.reset_demo_state

Cleans up demo-specific memories and actions without touching the underlying
enterprise database records (employees, projects, documents, connectors).
"""
from __future__ import annotations

import logging
from sqlalchemy import or_

from .models import AIAction, ConnectorItem, EnterpriseMemory
from .session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("novatech.reset_demo")


def reset_demo_state() -> None:
    log.info("Resetting demo memories and pending actions to clean judge baseline...")
    with SessionLocal() as db:
        # 1. Clean demo memories that might interfere with demo evaluation
        deleted_mems = db.query(EnterpriseMemory).filter(
            or_(
                EnterpriseMemory.content.contains("parameterized"),
                EnterpriseMemory.content.contains("SQL string interpolation"),
                EnterpriseMemory.content.contains("API key rotation"),
                EnterpriseMemory.content.contains("OAuth token leakage"),
                EnterpriseMemory.content.contains("Platform Security team"),
            )
        ).delete(synchronize_session=False)

        # 2. Clean temporary demo connector items generated during Jira demo tests
        deleted_items = db.query(ConnectorItem).filter(
            or_(
                ConnectorItem.content.contains("API key rotation"),
                ConnectorItem.content.contains("OAuth token leakage"),
            )
        ).delete(synchronize_session=False)

        # 3. Clean pending demo actions
        deleted_actions = db.query(AIAction).filter(
            AIAction.tool.in_(["propose_code_fix", "create_jira_issue"])
        ).delete(synchronize_session=False)

        db.commit()

    print("\n" + "=" * 70)
    print("[OK] NexusGuard Demo State Reset Complete")
    print(f"  - Cleared {deleted_mems} dynamic demo memories")
    print(f"  - Cleared {deleted_items} dynamic demo connector items")
    print(f"  - Cleared {deleted_actions} pending demo actions")
    print("=" * 70)
    print("Ready to execute the Hindsight Engineering Code Review Agent Demo:\n")
    print("1. Sign in as Rahul Sharma (rahul.sharma@novatech.demo)")
    print("2. Session A: Teach team standard:")
    print("   'Remember team decision: Our team requires parameterized SQL queries and does not allow raw SQL string interpolation.'")
    print("3. Session B: Open new chat and submit vulnerable code:")
    print("   'Review this code: query = \"SELECT * FROM users WHERE id = \" + userId'")
    print("4. Verify Engineering Code Review Agent flags SQL injection citing team standard.")
    print("5. Approve the proposed fix card and inspect audit logs.\n")


if __name__ == "__main__":
    reset_demo_state()
