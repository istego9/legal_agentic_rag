from __future__ import annotations

from typing import Any, Dict, Mapping

from fastapi import APIRouter, HTTPException

from legal_rag_api import runtime_pg
from legal_rag_api.contracts import ScoringPolicy
from legal_rag_api.state import store
from services.eval.engine import (
    POLICY_FAMILY_NAMES,
    POLICY_REGISTRY_VERSION,
    build_policy_registry,
    collect_scoring_policy_versions,
)

router = APIRouter(prefix="/v1/config", tags=["Config"])


def _policy_registry_override() -> Dict[str, Any]:
    if runtime_pg.enabled():
        payload = runtime_pg.get_config_version(POLICY_REGISTRY_VERSION) or {}
        return payload if isinstance(payload, dict) else {}
    payload = store.config_versions.get(POLICY_REGISTRY_VERSION, {})
    return payload if isinstance(payload, dict) else {}


def _merge_policy_registry_override(
    base: Mapping[str, Any],
    patch: Mapping[str, Any],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    base_policies_raw = base.get("policies")
    patch_policies_raw = patch.get("policies")
    base_policies = dict(base_policies_raw) if isinstance(base_policies_raw, Mapping) else {}
    patch_policies = dict(patch_policies_raw) if isinstance(patch_policies_raw, Mapping) else {}

    for family, family_patch in patch_policies.items():
        if not isinstance(family_patch, Mapping):
            base_policies[family] = family_patch
            continue
        family_base_raw = base_policies.get(family)
        family_base = dict(family_base_raw) if isinstance(family_base_raw, Mapping) else {}
        family_base.update(dict(family_patch))
        base_policies[family] = family_base

    for key, value in patch.items():
        if key == "policies":
            continue
        merged[key] = value
    merged["policies"] = base_policies
    return merged


def _normalize_policy_registry_patch(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if "policies" in payload:
        policies_payload = payload.get("policies")
        policies = dict(policies_payload) if isinstance(policies_payload, Mapping) else {}
        out = {
            key: value
            for key, value in payload.items()
            if key not in POLICY_FAMILY_NAMES
        }
        out["policies"] = policies
        return out

    shorthand_policies = {
        key: payload.get(key)
        for key in POLICY_FAMILY_NAMES
        if key in payload
    }
    out = {
        key: value
        for key, value in payload.items()
        if key not in POLICY_FAMILY_NAMES
    }
    out["policies"] = shorthand_policies
    return out


def _scoring_policy_versions() -> list[str]:
    if runtime_pg.enabled():
        items = runtime_pg.list_scoring_policies()
    else:
        items = list(store.scoring_policies.values())
    return collect_scoring_policy_versions(items)


def _policy_registry_snapshot(*, override: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    base_override = dict(_policy_registry_override())
    if override:
        base_override = _merge_policy_registry_override(base_override, override)
    return build_policy_registry(
        scoring_policy_versions=_scoring_policy_versions(),
        override=base_override,
    )


@router.get("/scoring-policies")
def list_policies() -> dict:
    if runtime_pg.enabled():
        return {"items": [p.model_dump(mode="json") for p in runtime_pg.list_scoring_policies()]}
    return {"items": [p.model_dump(mode="json") for p in store.scoring_policies.values()]}


@router.post("/scoring-policies")
def upsert_policy(payload: ScoringPolicy) -> dict:
    if runtime_pg.enabled():
        runtime_pg.upsert_scoring_policy(payload)
    else:
        store.scoring_policies[payload.policy_version] = payload
    return {"status": "ok"}


@router.get("/policy-registry")
def get_policy_registry() -> dict:
    return _policy_registry_snapshot()


@router.post("/policy-registry")
def upsert_policy_registry(payload: Dict[str, Any]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be an object")
    override = _normalize_policy_registry_patch(payload)

    normalized = _policy_registry_snapshot(override=override)
    stored_payload = {
        "registry_version": normalized.get("registry_version", POLICY_REGISTRY_VERSION),
        "policies": normalized.get("policies", {}),
    }
    if runtime_pg.enabled():
        runtime_pg.upsert_config_version(POLICY_REGISTRY_VERSION, stored_payload)
    else:
        store.config_versions[POLICY_REGISTRY_VERSION] = stored_payload
    return {"status": "ok", "registry": normalized}
