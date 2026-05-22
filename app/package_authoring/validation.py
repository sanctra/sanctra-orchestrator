from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from jsonschema import Draft202012Validator, FormatChecker

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
IMAGE_ARTIFACTS = {"portrait_image"}
HIGH_PRESENCE_ARTIFACTS = VOICE_ARTIFACTS | VIDEO_ARTIFACTS
LIKNESS_USES = {"private_audio", "public_audio", "private_video", "public_video"}
TEXT_USES = {"memorial_text", "memory_page"}
PACKAGE_STATUSES = {
    "draft",
    "intake_pending",
    "authority_review",
    "source_review",
    "artifact_production",
    "family_review",
    "approved",
    "delivered",
    "paused",
    "revoked",
    "takedown_requested",
}
TERMINAL_PACKAGE_STATUSES = {"revoked", "takedown_requested"}
PACKAGE_STATUS_TRANSITIONS = {
    "draft": {"intake_pending", "authority_review", "paused", "revoked"},
    "intake_pending": {"authority_review", "source_review", "paused", "revoked"},
    "authority_review": {"source_review", "paused", "revoked", "takedown_requested"},
    "source_review": {"artifact_production", "paused", "revoked", "takedown_requested"},
    "artifact_production": {"family_review", "paused", "revoked", "takedown_requested"},
    "family_review": {"approved", "artifact_production", "paused", "revoked", "takedown_requested"},
    "approved": {"delivered", "family_review", "paused", "revoked", "takedown_requested"},
    "delivered": {"takedown_requested", "revoked"},
    "paused": {"intake_pending", "authority_review", "source_review", "artifact_production", "family_review", "revoked"},
    "revoked": set(),
    "takedown_requested": {"revoked"},
}
ARTIFACT_FAMILY_BY_TYPE = {
    "memorial_profile": "text",
    "memory_page": "text",
    "email_response": "text",
    "letter": "text",
    "story": "text",
    "voice_message": "audio",
    "portrait_image": "image",
    "talking_head_clip": "video",
    "consultant_closeout_packet": "text",
}
ARTIFACT_OUTPUT_CONTRACTS = {
    "text": {"formats": ["text/markdown; charset=utf-8", "text/plain; charset=utf-8", "application/pdf"], "metadata_required": True},
    "audio": {"formats": ["audio/wav", "audio/mpeg"], "hash_required": True, "manifest_hash_required": True},
    "image": {"formats": ["image/png", "image/jpeg", "image/webp"], "model_dataset_refs_required": True},
    "video": {"formats": ["video/mp4"], "codec": "H.264", "baseline": "1080p", "placeholder": True},
}
TIER_ENTITLEMENTS = {
    "async_starter": {
        "allowed_artifact_families": ["text"],
        "consultant_white_glove": False,
        "review_required": False,
    },
    "guided_consultant": {
        "allowed_artifact_families": ["text", "audio", "image", "video"],
        "consultant_white_glove": True,
        "review_required": True,
    },
}
REVIEW_STATES = {"not_required", "required_pending", "approved", "changes_requested", "rejected"}
REVIEW_REQUIRED_TIERS = {"guided_consultant", "consultant", "high_trust", "consultant_high_trust"}
PILOT_ADMIN_ROLES = {"pilot_admin"}
PILOT_REVIEWER_ROLES = {"pilot_reviewer"}
PILOT_READONLY_ROLES = {"pilot_operator_readonly"}
PILOT_ALLOWED_ROLES = PILOT_ADMIN_ROLES | PILOT_REVIEWER_ROLES | PILOT_READONLY_ROLES
BLOCKED_PILOT_STATUSES = {"approved", "delivered", "published", "released", "training", "trained"}
BLOCKED_PROVIDER_KEYS = {
    "provider_ref",
    "provider_id",
    "provider_job_ref",
    "provider_job_id",
    "model_ref",
    "model_id",
    "training_job_ref",
    "training_job_id",
    "publish_target_ref",
    "publish_target_id",
    "release_ref",
    "release_id",
}
SCHEMA_PATH = Path(__file__).parent / "schema" / "async-memorial-package.schema.json"
SUBJECT_DATASET_SCHEMA_VERSION = "sanctra.subject_dataset_package.v0.3"
SUBJECT_DATASET_SCHEMA_PATH = Path(__file__).parent / "schema" / "subject-dataset-package.schema.json"


def load_schema_contract() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_json_schema_contract(instance: dict[str, Any], schema_path: Path, *, label: str) -> None:
    """Run Draft 2020-12 JSON Schema validation for runtime package contracts."""
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise_validation(f"{label} schema validation failed at {location}: {first.message}")


def validate_subject_dataset_package(package: dict[str, Any]) -> dict[str, Any]:
    """Validate the governed Subject Dataset Package v0.3 contract.

    This is intentionally side-effect-free: it validates a submitted package
    object but does not enqueue jobs, mutate storage, or call model providers.
    """
    if not isinstance(package, dict):
        raise_validation("subject dataset package must be a JSON object")
    if package.get("schema_version") != SUBJECT_DATASET_SCHEMA_VERSION:
        raise_validation(f"schema_version must be {SUBJECT_DATASET_SCHEMA_VERSION}")
    validate_json_schema_contract(package, SUBJECT_DATASET_SCHEMA_PATH, label="subject_dataset_package")
    validate_ids_and_leakage(package)
    return package


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
    validate_json_schema_contract(normalized, SCHEMA_PATH, label="async_memorial_package")
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
        family = artifact_family(manifest)
        entitlement = package_entitlement(bundle, manifest.get("package_ref"))
        if family not in entitlement["allowed_artifact_families"]:
            raise HTTPException(status_code=403, detail=f"{family} artifact is not entitled for package tier")
        validate_artifact_output_contract(manifest, family)


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


def package_entitlement(bundle: dict[str, Any], package_id: Any) -> dict[str, Any]:
    package = next((item for item in bundle.get("memorial_packages", []) if item.get("package_id") == package_id), {})
    tier = package.get("tier") or "async_starter"
    base = deepcopy(TIER_ENTITLEMENTS.get(tier, TIER_ENTITLEMENTS["async_starter"]))
    base["tier"] = tier
    base["status"] = package.get("status", "draft")
    base["blocked"] = package.get("status") in TERMINAL_PACKAGE_STATUSES
    return base


def artifact_family(manifest: dict[str, Any]) -> str:
    return ARTIFACT_FAMILY_BY_TYPE.get(manifest.get("artifact_type"), "text")


def validate_artifact_output_contract(manifest: dict[str, Any], family: str) -> None:
    contract = ARTIFACT_OUTPUT_CONTRACTS[family]
    outputs = manifest.get("outputs") or []
    if family in {"text", "audio"} and not outputs:
        raise_validation(f"{family} manifests require output references")
    for output in outputs:
        if output.get("format") not in contract["formats"]:
            raise_validation(f"{family} output format must be one of {contract['formats']}")
        if contract.get("hash_required") and not str(output.get("content_hash", "")).startswith("sha256:"):
            raise_validation(f"{family} output content_hash must be a sha256 manifest hash reference")
    if family == "audio" and not manifest.get("generation_refs"):
        raise_validation("audio manifests require generation refs for manual/provider job traceability")
    if family == "image":
        kinds = {ref.get("kind") for ref in manifest.get("generation_refs", []) if isinstance(ref, dict)}
        if not {"model_manifest", "dataset_manifest"}.issubset(kinds):
            raise_validation("image manifests require model_manifest and dataset_manifest generation refs")
    if family == "video":
        for output in outputs:
            media_contract = output.get("media_contract") or {}
            if output.get("format") != "video/mp4":
                raise_validation("video placeholder outputs must use video/mp4")
            if media_contract.get("codec") != "H.264" or media_contract.get("baseline") != "1080p":
                raise_validation("video placeholders must declare H.264 1080p baseline media_contract")


def package_lifecycle_summary(bundle: dict[str, Any], package_id: str) -> dict[str, Any]:
    package = next((item for item in bundle.get("memorial_packages", []) if item.get("package_id") == package_id), None)
    if not package:
        raise HTTPException(status_code=404, detail=f"unknown package {package_id}")
    manifest_refs = set(package.get("artifact_manifest_refs", []))
    manifests = [
        manifest for manifest in bundle.get("artifact_manifests", []) if manifest.get("manifest_id") in manifest_refs
    ]
    entitlement = package_entitlement(bundle, package_id)
    entitlement["families_present"] = sorted({artifact_family(manifest) for manifest in manifests})
    return {
        "package_id": package_id,
        "status": package.get("status"),
        "subject_ref": package.get("subject_ref"),
        "consultant_white_glove": entitlement["consultant_white_glove"],
        "entitlement": entitlement,
        "artifact_refs": [
            {
                "manifest_id": manifest.get("manifest_id"),
                "artifact_type": manifest.get("artifact_type"),
                "artifact_family": artifact_family(manifest),
                "artifact_status": manifest.get("artifact_status"),
                "output_refs": [
                    {
                        "artifact_id": output.get("artifact_id"),
                        "format": output.get("format"),
                        "storage_uri": output.get("storage_uri"),
                        "content_hash": output.get("content_hash"),
                    }
                    for output in manifest.get("outputs", [])
                ],
                "generation_refs": manifest.get("generation_refs", []),
                "revocation_ref": manifest.get("revocation_ref"),
                "retention_policy": manifest.get("retention_policy"),
            }
            for manifest in manifests
        ],
        "lifecycle_events": package.get("lifecycle_events", []),
    }


def transition_package_lifecycle(
    bundle: dict[str, Any],
    package_id: str,
    status: str,
    actor: dict[str, Any],
    *,
    reason: str = "",
    revocation_ref: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if status not in PACKAGE_STATUSES:
        raise_validation(f"unsupported package status {status}")
    updated = deepcopy(bundle)
    package = next((item for item in updated.get("memorial_packages", []) if item.get("package_id") == package_id), None)
    if not package:
        raise HTTPException(status_code=404, detail=f"unknown package {package_id}")
    prior = package.get("status", "draft")
    if status != prior and status not in PACKAGE_STATUS_TRANSITIONS.get(prior, set()):
        raise HTTPException(status_code=409, detail=f"invalid lifecycle transition {prior} -> {status}")
    actor_id = actor.get("actor_id") or "system:package_lifecycle"
    role = actor.get("role") or "pilot_admin"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    event = {
        "event_id": f"lifecycle:{package_id.replace(':', '_')}:{status}:{len(package.get('lifecycle_events', [])) + 1}",
        "from_status": prior,
        "to_status": status,
        "actor_id": actor_id,
        "actor_role": role,
        "reason": reason or f"package lifecycle moved to {status}",
        "created_at": now,
    }
    if revocation_ref:
        event["revocation_ref"] = revocation_ref
    package["status"] = status
    package["updated_at"] = now
    package["entitlement"] = package_entitlement(updated, package_id)
    package.setdefault("lifecycle_events", []).append(event)

    if status in TERMINAL_PACKAGE_STATUSES:
        target_artifact_status = "revoked" if status == "revoked" else "removed"
        refs = set(package.get("artifact_manifest_refs", []))
        for manifest in updated.get("artifact_manifests", []):
            if manifest.get("manifest_id") not in refs:
                continue
            if manifest.get("artifact_status") not in {"revoked", "removed"}:
                manifest["artifact_status"] = target_artifact_status
                manifest["revocation_ref"] = revocation_ref or event["event_id"]
                manifest["revoked_at"] = now
                manifest["retention_policy"] = (
                    "Retain only audit metadata and manifest hashes; remove generated media refs after revocation review."
                )
    validate_bundle(updated)
    return updated, event


def validate_manifest_write(bundle: dict[str, Any], manifest: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise_validation("manifest must be a JSON object")
    manifest = dict(manifest)
    manifest.pop("caller_metadata", None)
    manifest_id = manifest.get("manifest_id")
    if not isinstance(manifest_id, str) or not ID_PATTERN.match(manifest_id):
        raise_validation("manifest_id must be a stable Sanctra id")
    actor = actor or {}
    role = _actor_role(actor)
    artifact_type = manifest.get("artifact_type")
    if artifact_type in HIGH_PRESENCE_ARTIFACTS:
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

    _enforce_pilot_role_guard(manifest, role)
    _enforce_pilot_lockouts(manifest)

    review = normalize_manifest_review_metadata(bundle, manifest, role)
    if review:
        manifest["human_review"] = review
    manifest["audit_metadata"] = _build_audit_metadata(manifest, actor, role)

    if artifact_type in VOICE_ARTIFACTS and manifest.get("artifact_status") in {"approved", "delivered"} and not manifest.get("mastering_report_uri"):
        raise HTTPException(status_code=403, detail="voice artifacts require mastering_report_uri before approval or delivery")
    validate_ids_and_leakage(manifest, "manifest")
    return manifest


def normalize_manifest_review_metadata(bundle: dict[str, Any], manifest: dict[str, Any], role: str | None) -> dict[str, Any] | None:
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
    if review_required and role not in PILOT_ADMIN_ROLES | PILOT_REVIEWER_ROLES:
        raise HTTPException(status_code=403, detail="pilot reviewer or pilot admin role required for review mutations")

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
        if role not in PILOT_ADMIN_ROLES | PILOT_REVIEWER_ROLES:
            raise HTTPException(status_code=403, detail="pilot reviewer or pilot admin role required for terminal review decisions")
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
    if manifest.get("artifact_status") in {"approved", "delivered"} and manifest.get("artifact_type") in HIGH_PRESENCE_ARTIFACTS and role not in PILOT_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="pilot admin confirmation is required before high-presence artifacts can be approved or delivered")
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


def _actor_role(actor: dict[str, Any]) -> str | None:
    role = actor.get("role")
    return role if isinstance(role, str) and role else None


def _enforce_pilot_role_guard(manifest: dict[str, Any], role: str | None) -> None:
    if role not in PILOT_ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="pilot lane access is restricted to pilot_admin, pilot_reviewer, or pilot_operator_readonly")
    if role in PILOT_READONLY_ROLES:
        raise HTTPException(status_code=403, detail="pilot_operator_readonly cannot mutate pilot manifests")


def _enforce_pilot_lockouts(manifest: dict[str, Any]) -> None:
    if manifest.get("artifact_status") in BLOCKED_PILOT_STATUSES:
        # approved/delivered are conditionally allowed later after role/review checks
        if manifest.get("artifact_status") in {"approved", "delivered"}:
            pass
        else:
            raise HTTPException(status_code=403, detail="provider, training, publish, and release actions are hard-disabled in the guided-curation pilot lane")
    for key in BLOCKED_PROVIDER_KEYS:
        if manifest.get(key):
            raise HTTPException(status_code=403, detail=f"{key} is hard-disabled in the guided-curation pilot lane")


def _build_audit_metadata(manifest: dict[str, Any], actor: dict[str, Any], role: str | None) -> dict[str, Any]:
    review = manifest.get("human_review") or {}
    return {
        "actor_id": actor.get("actor_id") or actor.get("id") or "unknown_actor",
        "actor_role": role or "unknown_role",
        "lane": actor.get("lane") or "guided_curation_pilot",
        "item_id": manifest.get("manifest_id"),
        "source_id": manifest.get("package_ref"),
        "authority_basis": actor.get("authority_basis") or "documented_authority_required",
        "consent_scope": actor.get("consent_scope") or "private_review",
        "audience_scope": actor.get("audience_scope") or "private_review",
        "prior_state": actor.get("prior_state") or "unknown",
        "new_state": manifest.get("artifact_status") or "planned",
        "decision_reason": review.get("notes") or actor.get("decision_reason") or "pilot mutation",
        "admin_confirmation_required": manifest.get("artifact_type") in HIGH_PRESENCE_ARTIFACTS,
        "admin_confirmation_performed": role in PILOT_ADMIN_ROLES and manifest.get("artifact_status") in {"approved", "delivered"},
    }


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
