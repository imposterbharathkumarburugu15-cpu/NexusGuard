"""Hindsight Persistent Memory Router.

Endpoints for managing enterprise memory, inspecting Hindsight status,
retaining decisions/preferences/corrections, and recalling authorized memories.
"""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.rbac import allowed_levels, is_guest
from ..core.security import Principal, get_principal
from ..db.session import get_db
from ..services.memory import memory_service

log = logging.getLogger("novatech.memory")
router = APIRouter(prefix="/memory", tags=["memory"])


class RetainMemoryPayload(BaseModel):
    content: str = Field(..., min_length=5, description="Text content to retain in memory")
    category: str = Field(default="engineering_decision", description="Category: engineering_decision, user_preference, organizational_policy, workflow_decision, correction")
    clearance: str = Field(default="INTERNAL", description="Classification level: PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED")
    department: str = Field(default="*", description="Department scope or '*' for organization-wide")
    tags: list[str] = Field(default_factory=list, description="Optional search/filter tags")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom metadata attributes")


class RecallMemoryPayload(BaseModel):
    query: str = Field(..., min_length=2, description="Semantic or keyword query to recall memories for")
    category: str | None = Field(default=None, description="Optional category filter")
    limit: int = Field(default=5, ge=1, le=20, description="Max memories to return")


@router.get("/status")
def get_memory_status(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Returns the operational status of Hindsight Persistent Memory."""
    return memory_service.get_status(db=db, company_id=principal.company_id)


@router.get("")
def list_memories(
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """List retained memories accessible to the current user."""
    memories = memory_service.list_for_principal(
        db=db,
        principal=principal,
        category=category,
        limit=limit,
    )
    return {
        "memories": [m.to_dict() for m in memories],
        "count": len(memories),
        "bank_id": memory_service.bank_for_tenant(principal.company_id),
    }


@router.post("/retain", status_code=status.HTTP_201_CREATED)
def retain_memory_endpoint(
    payload: RetainMemoryPayload,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Manually retain an organizational decision or user preference into Hindsight."""
    try:
        res = memory_service.retain(
            db=db,
            principal=principal,
            content=payload.content,
            category=payload.category,
            clearance=payload.clearance,
            department=payload.department,
            tags=payload.tags,
            metadata=payload.metadata,
        )
        return {
            "status": "success",
            "message": "Memory retained successfully in Hindsight persistent bank.",
            "memory": res,
        }
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as exc:
        log.exception("Failed to retain memory: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retain memory: {exc}")


@router.post("/recall")
def recall_memory_endpoint(
    payload: RecallMemoryPayload,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Recall memories matching a query subject to user's RBAC and tenant boundaries."""
    memories = memory_service.recall(
        db=db,
        principal=principal,
        query=payload.query,
        category=payload.category,
        limit=payload.limit,
    )
    return {
        "query": payload.query,
        "count": len(memories),
        "memories": [m.to_dict() for m in memories],
        "bank_id": memory_service.bank_for_tenant(principal.company_id),
    }


@router.delete("/{memory_id}")
def delete_memory_endpoint(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    """Delete a memory from Hindsight and local enterprise store."""
    try:
        ok = memory_service.delete_memory(
            db=db,
            principal=principal,
            memory_id=memory_id,
        )
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
        return {"status": "success", "message": f"Memory {memory_id} deleted."}
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as exc:
        log.exception("Failed to delete memory: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
