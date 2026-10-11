"""Explicit work dependencies and local, unsent follow-up drafts."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import ApiError
from ..impact_service import impact_report, prepare_draft
from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["decision impact"])
Context = Annotated[AppContext, Depends(get_ctx)]


class SourceDocument(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    uri: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=30_000)
    synthetic: bool = False


class WorkItemBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    id: str = Field(pattern=r"^work_[a-zA-Z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=200)
    status: Literal["open", "completed", "cancelled"] = "open"
    owner_id: str = Field(min_length=1, max_length=150)
    baseline_fact_id: str = Field(min_length=1, max_length=150)
    rationale: str = Field(min_length=1, max_length=2000)


class WorkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: SourceDocument
    items: list[WorkItemBody] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("work item ids must be unique within a manifest")
        return self

    def graph_payload(self) -> dict[str, Any]:
        data = self.model_dump()
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]
        data["document"]["id"] = f"doc_{fingerprint}"
        return data


class DraftBody(BaseModel):
    current_fact_id: str = Field(min_length=1, max_length=150)


@router.post("/work-items/import")
def import_work_items(tenant: str, body: WorkManifest, ctx: Context) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    payload = body.graph_payload()
    try:
        imported = ctx.hive.import_work_manifest(tenant, payload)
    except ValueError as exc:
        raise ApiError(422, "invalid_work_manifest", str(exc)) from exc
    return {"imported": imported, "document_id": payload["document"]["id"]}


@router.get("/impact")
def get_impact(tenant: str, ctx: Context) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    return impact_report(ctx.hive, tenant)


@router.get("/impact/drafts")
def get_drafts(tenant: str, ctx: Context) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return ctx.hive.list_impact_drafts(tenant)


@router.post("/impact/{work_item_id}/draft")
def create_draft(tenant: str, work_item_id: str, body: DraftBody, ctx: Context) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    return prepare_draft(ctx.hive, tenant, work_item_id, body.current_fact_id)
