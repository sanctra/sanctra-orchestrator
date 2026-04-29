from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

SCHEMA_VERSION = "sanctra.async_memorial_package.v0"
REQUIRED_COLLECTIONS = (
    "memorial_subjects",
    "stakeholders",
    "authority_records",
    "source_inventories",
    "quality_gates",
    "review_decisions",
    "artifact_manifests",
    "closeout_instructions",
    "memorial_packages",
)
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_:-]{2,127}$")
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
ORCHESTRATION_MARKERS = ("paperclip", "openclaw", "issue:", "run:", "agent:", "PAPERCLIP_")
VOICE_ARTIFACTS = {"voice_message"}
VIDEO_ARTIFACTS = {"talking_head_clip"}
LIKNESS_USES = {"private_audio", "public_audio", "private_video", "public_video"}
TEXT_USES = {"memorial_text", "memory_page"}
REVIEW_STATES = {"not_required", "required_pending", "approved", "changes_requested", "rejected"}
REVIEW_REQUIRED_TIERS = {"guided_consultant", "consultant", "high_trust", "consultant_high_trust"}
SCHEMA_PATH = Path(__file__).parent / "schema" / "async-memorial-package.schema.json"


def load_schema_contract() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def normalize_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise_validation("bundle must be a JSON object")
    normalized = dict(bundle)
    if normalized.get("schema_version") != SCHEMA_VERSION:
        raise_validation(f"schema_version must be {SCHEMA_VERSION}")
    for key in REQUIRED_COLLECTIONS:
        normalized.setdefault(key, [])
        if not isinstance(normalized[key], list):
            raise_validation(f"{key} must be an array")
    return normalized


def validate_bundle(bundle: dict[str, Any], *, require_package: bool = True) -> dict[str, Any]:
    normalized = normalize_bundle(bundle)
    load_schema_contract()  # Parse gate for vendored runtime contract.
    if require_package and not normalized["memorial_packages"]:
        raise_validation("memorial_packages must include at least one package record")
    validate_ids_and_leakage(normalized)
    validate_refs(normalized)
    return normalized


def package_id_from_bundle(bundle: dict[str, Any]) -> str:
    packages = bundle.get("memorial_packages") or []
    if not packages:
        raise_validation("bundle.memorial_packages[0].package_id is required")
    package_id = packages[0].get("package_id")
    if not isinstance(package_id, str) or not ID_PATTERN.match(package_id):
        raise_validation("package_id must be a stable Sanctra id")
    return package_id


def validate_ids_and_leakage(value: Any, path: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            validate_ids_and_leakage(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            validate_ids_and_leakage(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if UUID_PATTERN.search(value) or any(marker.lower() in lowered for marker in ORCHESTRATION_MARKERS):
            raise_validation(f"orchestration id leakage rejected at {path}")


def validate_refs(bundle: dict[str, Any]) -> None:
    ids: set[str] = set()
    def add_id(record_id: str | None, path: str) -> None:
        if not isinstance(record_id, str) or not ID_PATTERN.match(record_id):
            raise_validation(f"{path} must be a stable Sanctra id")
        if record_id in ids:
            raise_validation(f"duplicate id {record_id}")
        ids.add(record_id)

    for collection, id_key in (
        ("memorial_subjects", "subject_id"),
        ("stakeholders", "stakeholder_id"),
        ("authority_records", "authority_id"),
        ("source_inventories", "inventory_id"),
        ("quality_gates", "gate_id"),
        ("review_decisions", "decision_id"),
        ("artifact_manifests", "manifest_id"),
        ("closeout_instructions", "closeout_id"),
        ("memorial_packages", "package_id"),
    ):
        for record in bundle.get(collection, []):
            add_id(record.get(id_key), f"{collection}.{id_key}")

    for inventory in bundle.get("source_inventories", []):
        for item in inventory.get("items", []):
            add_id(item.get("source_id"), "source_inventories.items.source_id")
    for gate in bundle.get("quality_gates", []):
        for check in gate.get("checks", []):
            add_id(check.get("check_id"), "quality_gates.checks.check_id")
    for manifest in bundle.get("artifact_manifests", []):
        for output in manifest.get("outputs", []):
            add_id(output.get("artifact_id"), "artifact_manifests.outputs.artifact_id")

    for package in bundle.get("memorial_packages", []):
        require_ref(ids, package.get("subject_ref"), "memorial_packages.subject_ref")
        require_ref(ids, package.get("source_inventory_ref"), "memorial_packages.source_inventory_ref")
        require_ref(ids, package.get("closeout_instruction_ref"), "memorial_packages.closeout_instruction_ref")
        for key in ("stakeholder_refs", "authority_record_refs", "quality_gate_refs", "artifact_manifest_refs"):
            for ref in package.get(key, []):
                require_ref(ids, ref, f"memorial_packages.{key}")

    for authority in bundle.get("authority_records", []):
        require_ref(ids, authority.get("subject_ref"), "authority_records.subject_ref")
        require_ref(ids, authority.get("stakeholder_ref"), "authority_records.stakeholder_ref")
        for ref in authority.get("source_refs", []):
            require_ref(ids, ref, "authority_records.source_refs")

    for manifest in bundle.get("artifact_manifests", []):
        if manifest.get("artifact_type") in VOICE_ARTIFACTS | VIDEO_ARTIFACTS and not manifest.get("authority_record_refs"):
            raise_validation("voice/video artifact manifests require authority_record_refs")
        for ref in manifest.get("authority_record_refs", []):
            require_ref(ids, ref, "artifact_manifests.authority_record_refs")


def authority_preflight(bundle: dict[str, Any], artifact_type: str, requested_use: str, subject_ref: str | None) -> dict[str, Any]:
    if requested_use in TEXT_USES:
        return {"allowed": True, "authority_record_refs": [], "decision": "approved", "reasons": []}
    if artifact_type in VOICE_ARTIFACTS and requested_use not in {"private_audio", "public_audio"}:
        return denied(f"{artifact_type} requires private_audio or public_audio use")
    if artifact_type in VIDEO_ARTIFACTS and requested_use not in {"private_video", "public_video"}:
        return denied(f"{artifact_type} requires private_video or public_video use")
    if requested_use not in LIKNESS_USES:
        return denied(f"Unsupported requested_use {requested_use}")

    matches: list[str] = []
    blocked: list[str] = []
    for authority in bundle.get("authority_records", []):
        if subject_ref and authority.get("subject_ref") != subject_ref:
            continue
        status = authority.get("status")
        authority_id = authority.get("authority_id")
        allowed_uses = set(authority.get("allowed_uses", []))
        prohibited_uses = set(authority.get("prohibited_uses", []))
        if status not in {"accepted", "limited"}:
            blocked.append(f"{authority_id} is {status}")
            continue
        if requested_use in prohibited_uses:
            blocked.append(f"{authority_id} prohibits {requested_use}")
            continue
        if requested_use in allowed_uses:
            matches.append(authority_id)
    if matches:
        return {"allowed": True, "authority_record_refs": matches, "decision": "approved", "reasons": []}
    subject_msg = f" for {subject_ref}" if subject_ref else ""
    reasons = [f"No accepted authority record allows {requested_use}{subject_msg}"]
    reasons.extend(blocked)
    return denied(*reasons)


def validate_manifest_write(bundle: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise_validation("manifest must be a JSON object")
    manifest_id = manifest.get("manifest_id")
    if not isinstance(manifest_id, str) or not ID_PATTERN.match(manifest_id):
        raise_validation("manifest_id must be a stable Sanctra id")
    artifact_type = manifest.get("artifact_type")
    if artifact_type in VOICE_ARTIFACTS | VIDEO_ARTIFACTS:
        authority_refs = manifest.get("authority_record_refs") or []
        if not authority_refs:
            raise_validation("voice/video manifests require authority_record_refs")
        allowed_refs = {
            authority.get("authority_id")
            for authority in bundle.get("authority_records", [])
            if authority.get("status") in {"accepted", "limited"}
        }
        missing = [ref for ref in authority_refs if ref not in allowed_refs]
        if missing:
            raise HTTPException(status_code=403, detail=f"authority gate denies manifest refs: {missing}")
    review = normalize_manifest_review_metadata(bundle, manifest)
    if review:
        manifest = dict(manifest)
        manifest["human_review"] = review
    validate_ids_and_leakage(manifest, "manifest")
    return manifest


def normalize_manifest_review_metadata(bundle: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Validate generic human-review metadata at the artifact manifest boundary.

    Sanctra package tiers decide when review is required. The shared voice lane only
    receives/stores generic review state and report refs; family/relationship UX is
    intentionally kept out of this metadata seam.
    """
    artifact_type = manifest.get("artifact_type")
    review = manifest.get("human_review") or {}
    if not isinstance(review, dict):
        raise_validation("human_review must be a JSON object")

    review_required = bool(review.get("review_required"))
    if artifact_type in VOICE_ARTIFACTS and _package_requires_review(bundle, manifest.get("package_ref")):
        review_required = True

    state = review.get("state") or ("required_pending" if review_required else "not_required")
    if state not in REVIEW_STATES:
        raise_validation("human_review.state must be not_required, required_pending, approved, changes_requested, or rejected")
    if state == "not_required" and review_required:
        raise HTTPException(status_code=403, detail="consultant/high-trust voice artifacts require human review")
    if state != "not_required" and not review_required:
        raise_validation("human_review.review_required must be true unless state is not_required")

    normalized = {
        "review_required": review_required,
        "state": state,
        "reviewer_ref": review.get("reviewer_ref"),
        "reviewer_identity_ref": review.get("reviewer_identity_ref"),
        "decided_at": review.get("decided_at"),
        "notes": review.get("notes") or "",
        "quality_gate_refs": list(review.get("quality_gate_refs") or manifest.get("quality_gate_refs") or []),
        "qa_report_refs": list(review.get("qa_report_refs") or []),
        "mastering_report_refs": list(review.get("mastering_report_refs") or []),
        "review_decision_refs": list(review.get("review_decision_refs") or manifest.get("review_decision_refs") or []),
    }
    for key in ("quality_gate_refs", "qa_report_refs", "mastering_report_refs", "review_decision_refs"):
        if not all(isinstance(ref, str) and ref for ref in normalized[key]):
            raise_validation(f"human_review.{key} must contain non-empty string refs")

    if state in {"approved", "changes_requested", "rejected"}:
        if not isinstance(normalized["reviewer_ref"], str) or not ID_PATTERN.match(normalized["reviewer_ref"]):
            raise_validation("human_review.reviewer_ref is required for terminal review decisions")
        if not isinstance(normalized["decided_at"], str) or not normalized["decided_at"].strip():
            raise_validation("human_review.decided_at is required for terminal review decisions")
        if state in {"changes_requested", "rejected"} and not (
            normalized["quality_gate_refs"] or normalized["qa_report_refs"] or normalized["mastering_report_refs"]
        ):
            raise_validation("changes_requested/rejected human reviews must retain QA or mastering report refs")

    if manifest.get("artifact_status") in {"approved", "delivered"} and review_required and state != "approved":
        raise HTTPException(status_code=403, detail="caller-facing delivery is blocked until human_review.state is approved")
    if state in {"changes_requested", "rejected"} and manifest.get("artifact_status") in {"approved", "delivered"}:
        raise HTTPException(status_code=403, detail="changes_requested/rejected artifacts cannot be approved or delivered")
    if review_required or review:
        return normalized
    return None


def _package_requires_review(bundle: dict[str, Any], package_ref: Any) -> bool:
    for package in bundle.get("memorial_packages", []):
        if package.get("package_id") != package_ref:
            continue
        tier_values = {package.get("tier"), package.get("trust_tier"), package.get("delivery_tier")}
        return any(isinstance(tier, str) and tier in REVIEW_REQUIRED_TIERS for tier in tier_values)
    return False


def upsert_manifest(bundle: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    manifests = list(bundle.get("artifact_manifests", []))
    for idx, existing in enumerate(manifests):
        if existing.get("manifest_id") == manifest["manifest_id"]:
            manifests[idx] = manifest
            break
    else:
        manifests.append(manifest)
    bundle = dict(bundle)
    bundle["artifact_manifests"] = manifests
    for package in bundle.get("memorial_packages", []):
        refs = list(package.get("artifact_manifest_refs", []))
        if manifest["manifest_id"] not in refs:
            refs.append(manifest["manifest_id"])
        package["artifact_manifest_refs"] = refs
    validate_bundle(bundle)
    return bundle


def require_ref(ids: set[str], ref: str | None, path: str) -> None:
    if not isinstance(ref, str) or ref not in ids:
        raise_validation(f"unknown reference at {path}: {ref}")


def denied(*reasons: str) -> dict[str, Any]:
    return {"allowed": False, "authority_record_refs": [], "decision": "blocked", "reasons": [r for r in reasons if r]}


def raise_validation(message: str) -> None:
    raise HTTPException(status_code=400, detail=message)
