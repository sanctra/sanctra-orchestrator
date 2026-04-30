from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from .validation import ID_PATTERN, validate_bundle, validate_ids_and_leakage


LANE_A_PROTOCOL_VERSION = "sanctra.lane_a_prompt_protocol.v0"
SUPPORTED_LANE_A_MODALITIES = {"text", "audio", "video"}
SUPPORTED_ARCHIVE_MEDIA_TYPES = {"text", "document", "image", "audio", "video", "transcript"}
UNSAFE_STORAGE_PREFIXES = ("/host/repos/", "./", "../")
UNSAFE_STORAGE_MARKERS = (".git/", "node_modules/", "__pycache__/", ".env")
VOICE_FAMILIES = {"voice", "audio", "voice_message", "private_audio", "public_audio"}
VIDEO_FAMILIES = {"video", "talking_head", "talking_head_clip", "private_video", "public_video"}


def create_lane_a_prompt_session(bundle: dict[str, Any], package_id: str, session: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(session, dict):
        raise_validation("session must be a JSON object")
    package = _package(bundle, package_id)
    consent = session.get("consent_snapshot") or {}
    if not isinstance(consent, dict) or consent.get("subject_consent") is not True:
        raise HTTPException(status_code=403, detail="Lane A prompt sessions require explicit subject consent")
    if consent.get("revocable") is not True or not consent.get("revocation_contact"):
        raise_validation("Lane A consent must be revocable and include revocation_contact")

    protocol_version = session.get("prompt_protocol_version") or LANE_A_PROTOCOL_VERSION
    if protocol_version != LANE_A_PROTOCOL_VERSION:
        raise_validation(f"unsupported prompt protocol version {protocol_version}")
    modalities = list(session.get("intended_modalities") or ["text"])
    unsupported = sorted(set(modalities) - SUPPORTED_LANE_A_MODALITIES)
    if unsupported:
        raise_validation(f"unsupported Lane A modalities: {unsupported}")

    subject_ref = session.get("subject_ref") or package.get("subject_ref")
    if subject_ref != package.get("subject_ref"):
        raise HTTPException(status_code=409, detail="Lane A subject_ref must match package subject_ref")
    session_id = session.get("session_id") or _next_id(bundle.get("lane_a_prompt_sessions", []), "prompt_session", "lane_a")
    _require_stable_id(session_id, "session_id")
    _ensure_not_existing(bundle.get("lane_a_prompt_sessions", []), "session_id", session_id, "prompt session")

    prompts = session.get("prompts") or default_lane_a_prompts()
    if not isinstance(prompts, list) or not prompts:
        raise_validation("Lane A prompt sessions require at least one prompt")
    prompt_ids: set[str] = set()
    normalized_prompts: list[dict[str, Any]] = []
    for prompt in prompts:
        if not isinstance(prompt, dict):
            raise_validation("Lane A prompts must be JSON objects")
        prompt_id = prompt.get("prompt_id")
        _require_stable_id(prompt_id, "prompt_id")
        if prompt_id in prompt_ids:
            raise_validation(f"duplicate prompt_id {prompt_id}")
        text = prompt.get("text")
        if not isinstance(text, str) or not text.strip():
            raise_validation("Lane A prompts require non-empty text")
        prohibited = ("look sad", "look tender", "sound sad", "perform emotion")
        if any(marker in text.lower() for marker in prohibited):
            raise_validation("Lane A prompts must elicit reflection, not performed emotion")
        prompt_ids.add(prompt_id)
        normalized_prompts.append(
            {
                "prompt_id": prompt_id,
                "section": prompt.get("section") or "life_review",
                "text": text.strip(),
                "capture_guidance": prompt.get("capture_guidance") or "Subject may answer in text, audio, or video and may approve, redact, re-record, mark private-only, or revoke.",
            }
        )

    record = {
        "session_id": session_id,
        "package_ref": package_id,
        "subject_ref": subject_ref,
        "prompt_protocol_version": protocol_version,
        "intended_modalities": modalities,
        "consent_snapshot": consent,
        "operator_context": session.get("operator_context") or {},
        "prompts": normalized_prompts,
        "review_queue_status": "awaiting_subject_responses",
        "created_at": _now(),
    }
    validate_ids_and_leakage(record, "lane_a_prompt_session")
    updated = _append_record(bundle, "lane_a_prompt_sessions", record)
    response = {
        "prompt_session_id": session_id,
        "ordered_prompts": normalized_prompts,
        "capture_instructions": {
            "modalities": modalities,
            "raw_media_policy": "Store raw media outside source repos and submit external storage refs only.",
            "review_loop": "Subject can approve, redact, re-record, mark private-only, or revoke each response.",
        },
        "required_consent_acknowledgements": ["subject_consent", "revocable", "source_lineage_retained"],
        "review_queue_status": record["review_queue_status"],
    }
    return validate_bundle(updated), response


def submit_lane_a_prompt_response(bundle: dict[str, Any], package_id: str, session_id: str, response: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(response, dict):
        raise_validation("response must be a JSON object")
    session = _find_record(bundle.get("lane_a_prompt_sessions", []), "session_id", session_id, "prompt session")
    if session.get("package_ref") != package_id:
        raise HTTPException(status_code=409, detail="prompt session does not belong to package")
    prompt_id = response.get("prompt_id")
    if prompt_id not in {p.get("prompt_id") for p in session.get("prompts", [])}:
        raise_validation("response.prompt_id must reference a prompt from the session")
    modality = response.get("modality")
    if modality not in SUPPORTED_LANE_A_MODALITIES:
        raise_validation("response.modality must be text, audio, or video")
    if response.get("subject_review_status") != "approved":
        raise HTTPException(status_code=403, detail="Lane A responses require subject approval before normalization")
    capture_context = response.get("capture_context") or {}
    if not isinstance(capture_context, dict) or not capture_context.get("captured_at") or not capture_context.get("capture_method"):
        raise_validation("Lane A responses require capture_context.captured_at and capture_context.capture_method")
    if modality in {"audio", "video"}:
        if response.get("raw_media") or response.get("inline_media_base64"):
            raise_validation("raw media must not be committed inline; provide external_media_ref")
        media_ref = response.get("external_media_ref")
        _validate_storage_ref(media_ref, "external_media_ref")
    else:
        transcript = response.get("transcript") or response.get("text")
        if not isinstance(transcript, str) or not transcript.strip():
            raise_validation("text Lane A responses require transcript/text")

    response_id = response.get("response_id") or _next_id(bundle.get("lane_a_prompt_responses", []), "prompt_response", "lane_a")
    _require_stable_id(response_id, "response_id")
    _ensure_not_existing(bundle.get("lane_a_prompt_responses", []), "response_id", response_id, "prompt response")
    source_id = response.get("source_id") or f"source:{response_id.replace(':', '_')}"
    _require_stable_id(source_id, "source_id")

    item = {
        "source_id": source_id,
        "kind": "transcript" if modality == "text" else modality,
        "storage_uri_or_path": response.get("external_media_ref") or f"sanctra-ingestion://lane-a/{response_id}",
        "submitted_by": response.get("submitted_by") or session.get("subject_ref"),
        "provenance_notes": f"Lane A prompted response {response_id} to {prompt_id}; subject reviewed and approved.",
        "subject_coverage": response.get("subject_coverage") or "Living-subject life-review prompt response.",
        "rights_notes": "First-party subject consent captured at prompt-session time; revocable by subject.",
        "sensitivity_level": response.get("sensitivity_level") or "moderate",
        "quality_notes": response.get("quality_notes") or "Pending reviewer normalization.",
        "usable_for": _usable_for_modality(modality),
        "exclude_from": ["public_training"],
        "retention_policy": response.get("retention_policy") or "Retain source reference while consent remains active; remove or quarantine on revocation.",
        "lineage": {"lane": "lane_a", "prompt_session_ref": session_id, "prompt_ref": prompt_id, "response_ref": response_id},
    }
    record = {
        "response_id": response_id,
        "session_ref": session_id,
        "package_ref": package_id,
        "prompt_ref": prompt_id,
        "modality": modality,
        "capture_context": capture_context,
        "subject_review_status": "approved",
        "source_ref": source_id,
        "review_queue_status": "normalized_source_pending_reviewer",
        "candidate_memory_coverage_refs": response.get("candidate_memory_coverage_refs") or [],
        "candidate_expression_sample_refs": response.get("candidate_expression_sample_refs") or ([] if modality == "text" else [f"expression:{response_id.replace(':', '_')}" ]),
        "created_at": _now(),
    }
    validate_ids_and_leakage(record, "lane_a_prompt_response")
    updated = _append_record(bundle, "lane_a_prompt_responses", record)
    updated = _append_source_item(updated, package_id, item)
    return validate_bundle(updated), {
        "response_id": response_id,
        "source_inventory_fragment": item,
        "candidate_memory_coverage_refs": record["candidate_memory_coverage_refs"],
        "candidate_expression_sample_refs": record["candidate_expression_sample_refs"],
        "review_queue_status": record["review_queue_status"],
    }


def create_lane_b_archive_intake(bundle: dict[str, Any], package_id: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise_validation("archive manifest must be a JSON object")
    _package(bundle, package_id)
    uploader_ref = manifest.get("uploader_stakeholder_ref")
    if not _has_stakeholder(bundle, uploader_ref):
        raise_validation("archive manifest requires uploader_stakeholder_ref from package stakeholders")
    authority_attestation = manifest.get("authority_attestation") or {}
    if not isinstance(authority_attestation, dict) or authority_attestation.get("can_submit_archives") is not True:
        raise HTTPException(status_code=403, detail="Lane B archive intake requires uploader authority attestation")

    intake_id = manifest.get("intake_id") or _next_id(bundle.get("lane_b_archive_intakes", []), "archive_intake", "lane_b")
    _require_stable_id(intake_id, "intake_id")
    _ensure_not_existing(bundle.get("lane_b_archive_intakes", []), "intake_id", intake_id, "archive intake")
    items = manifest.get("items") or []
    if not isinstance(items, list) or not items:
        raise_validation("archive manifest requires at least one item")

    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    readiness_gaps: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise_validation("archive items must be JSON objects")
        source_id = item.get("source_id")
        _require_stable_id(source_id, "items.source_id")
        media_type = item.get("media_type") or item.get("kind")
        if media_type not in SUPPORTED_ARCHIVE_MEDIA_TYPES:
            raise_validation(f"unsupported archive media_type {media_type}")
        storage_ref = item.get("storage_ref") or item.get("storage_uri_or_path")
        _validate_storage_ref(storage_ref, "items.storage_ref")
        provenance = item.get("provenance_notes") or item.get("claimed_origin")
        if not isinstance(provenance, str) or not provenance.strip():
            raise_validation(f"archive item {source_id} requires provenance_notes or claimed_origin")

        uncertainty_reasons = _archive_uncertainty_reasons(item)
        fragment = {
            "source_id": source_id,
            "kind": media_type,
            "storage_uri_or_path": storage_ref,
            "submitted_by": uploader_ref,
            "provenance_notes": provenance,
            "subject_coverage": item.get("subject_coverage") or "Posthumous archive submission pending curation.",
            "rights_notes": item.get("rights_notes") or _rights_notes(authority_attestation),
            "sensitivity_level": item.get("sensitivity_level") or "moderate",
            "quality_notes": item.get("quality_notes") or ("Quarantined for review." if uncertainty_reasons else "Accepted for reviewer normalization."),
            "usable_for": [] if uncertainty_reasons else _usable_for_archive_media(media_type),
            "exclude_from": ["artifact_generation", "public_training"] if uncertainty_reasons else ["public_training"],
            "retention_policy": item.get("retention_policy") or "Retain source reference only; raw archive remains outside source repos.",
            "lineage": {"lane": "lane_b", "archive_intake_ref": intake_id},
        }
        if uncertainty_reasons:
            quarantined.append({"source_id": source_id, "reasons": uncertainty_reasons, "review_queue_status": "quarantined_pending_review"})
            for reason in uncertainty_reasons:
                readiness_gaps.append({"source_ref": source_id, "gap_type": reason, "next_action": _gap_action(reason)})
        else:
            accepted.append(fragment)

    record = {
        "intake_id": intake_id,
        "package_ref": package_id,
        "uploader_stakeholder_ref": uploader_ref,
        "authority_attestation": authority_attestation,
        "accepted_source_refs": [item["source_id"] for item in accepted],
        "quarantined_items": quarantined,
        "readiness_gaps": readiness_gaps,
        "review_queue_status": "quarantine_review_required" if quarantined else "accepted_sources_pending_reviewer",
        "created_at": _now(),
    }
    validate_ids_and_leakage(record, "lane_b_archive_intake")
    updated = _append_record(bundle, "lane_b_archive_intakes", record)
    for fragment in accepted:
        updated = _append_source_item(updated, package_id, fragment)
    return validate_bundle(updated), {
        "intake_id": intake_id,
        "accepted_source_fragments": accepted,
        "quarantined_items": quarantined,
        "readiness_gaps": readiness_gaps,
        "review_queue_status": record["review_queue_status"],
    }


def ingestion_readiness(bundle: dict[str, Any], package_id: str, lane_refs: list[str], requested_artifact_families: list[str]) -> dict[str, Any]:
    package = _package(bundle, package_id)
    items = _inventory_items(bundle, package_id)
    source_kinds = {item.get("kind") for item in items}
    unresolved_quarantine = [item for intake in bundle.get("lane_b_archive_intakes", []) for item in intake.get("quarantined_items", [])]
    accepted_authority = [
        authority.get("authority_id")
        for authority in bundle.get("authority_records", [])
        if authority.get("status") in {"accepted", "limited"} and authority.get("subject_ref") == package.get("subject_ref")
    ]
    families = requested_artifact_families or ["memorial_text", "voice", "video"]
    per_modality: dict[str, Any] = {}
    blockers: list[str] = []
    gaps: list[dict[str, str]] = []
    for family in families:
        required_kind = _required_kind_for_family(family)
        family_blockers: list[str] = []
        if not accepted_authority:
            family_blockers.append("no accepted authority record")
        if required_kind and required_kind not in source_kinds and not (required_kind == "text" and "transcript" in source_kinds):
            family_blockers.append(f"insufficient {required_kind} source material")
            gaps.append({"artifact_family": family, "gap_type": f"missing_{required_kind}_source", "next_action": f"collect or approve {required_kind} source material"})
        if unresolved_quarantine and (family in VOICE_FAMILIES or family in VIDEO_FAMILIES):
            family_blockers.append("unresolved quarantine blocks likeness generation")
        state = "ready_for_review" if not family_blockers else "blocked"
        per_modality[family] = {"state": state, "blockers": family_blockers, "accepted_authority_record_refs": accepted_authority}
        blockers.extend(family_blockers)
    return {
        "package_id": package_id,
        "lane_refs": lane_refs,
        "per_modality_readiness": per_modality,
        "blockers": sorted(set(blockers)),
        "gap_prompts": gaps + [gap for intake in bundle.get("lane_b_archive_intakes", []) for gap in intake.get("readiness_gaps", [])],
        "allowed_next_artifact_requests": [family for family, state in per_modality.items() if state["state"] == "ready_for_review"],
        "review_requirements": ["consent_authority_review", "source_provenance_review", "human_approval_before_likeness_delivery"],
        "quarantine_refs": [item.get("source_id") for item in unresolved_quarantine],
    }


def default_lane_a_prompts() -> list[dict[str, str]]:
    return [
        {"prompt_id": "prompt:identity_voice", "section": "identity", "text": "What names, sayings, values, and everyday details would help loved ones recognize your voice?"},
        {"prompt_id": "prompt:turning_points", "section": "timeline", "text": "Tell a story about a turning point that shaped what mattered to you."},
        {"prompt_id": "prompt:care_message", "section": "relationships", "text": "What would you want someone you love to remember when they feel alone?"},
        {"prompt_id": "prompt:boundaries", "section": "boundaries", "text": "What topics, people, memories, or likeness uses should remain private, limited, or off limits?"},
    ]


def _append_record(bundle: dict[str, Any], collection: str, record: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(bundle)
    records = list(updated.get(collection, []))
    records.append(record)
    updated[collection] = records
    return updated


def _append_source_item(bundle: dict[str, Any], package_id: str, item: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(bundle)
    package = _package(updated, package_id)
    inventory_ref = package.get("source_inventory_ref")
    for inventory in updated.get("source_inventories", []):
        if inventory.get("inventory_id") == inventory_ref:
            if any(existing.get("source_id") == item["source_id"] for existing in inventory.get("items", [])):
                raise_validation(f"duplicate source_id {item['source_id']}")
            inventory.setdefault("items", []).append(item)
            return updated
    raise_validation(f"unknown package source_inventory_ref {inventory_ref}")


def _package(bundle: dict[str, Any], package_id: str) -> dict[str, Any]:
    for package in bundle.get("memorial_packages", []):
        if package.get("package_id") == package_id:
            return package
    raise HTTPException(status_code=404, detail=f"unknown package {package_id}")


def _inventory_items(bundle: dict[str, Any], package_id: str) -> list[dict[str, Any]]:
    package = _package(bundle, package_id)
    inventory_ref = package.get("source_inventory_ref")
    for inventory in bundle.get("source_inventories", []):
        if inventory.get("inventory_id") == inventory_ref:
            return list(inventory.get("items", []))
    return []


def _has_stakeholder(bundle: dict[str, Any], stakeholder_ref: Any) -> bool:
    return isinstance(stakeholder_ref, str) and any(stakeholder.get("stakeholder_id") == stakeholder_ref for stakeholder in bundle.get("stakeholders", []))


def _find_record(records: list[dict[str, Any]], key: str, value: str, label: str) -> dict[str, Any]:
    for record in records:
        if record.get(key) == value:
            return record
    raise HTTPException(status_code=404, detail=f"unknown {label} {value}")


def _ensure_not_existing(records: list[dict[str, Any]], key: str, value: str, label: str) -> None:
    if any(record.get(key) == value for record in records):
        raise HTTPException(status_code=409, detail=f"{label} {value} already exists")


def _next_id(records: list[dict[str, Any]], prefix: str, slug: str) -> str:
    return f"{prefix}:{slug}_{len(records) + 1:03d}"


def _require_stable_id(value: Any, path: str) -> None:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise_validation(f"{path} must be a stable Sanctra id")


def _validate_storage_ref(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise_validation(f"{path} is required")
    lowered = value.lower()
    if lowered.startswith(UNSAFE_STORAGE_PREFIXES) or any(marker in lowered for marker in UNSAFE_STORAGE_MARKERS):
        raise_validation(f"unsafe storage ref at {path}")


def _archive_uncertainty_reasons(item: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if item.get("permission_status") not in {"allowed", "limited"}:
        reasons.append("permission_uncertain")
    if item.get("subject_identity_confidence") not in {"confirmed", "high"}:
        reasons.append("identity_uncertain")
    if item.get("quality_status") in {"poor", "unknown", None}:
        reasons.append("quality_uncertain")
    if item.get("known_disputes"):
        reasons.append("known_dispute")
    return reasons


def _gap_action(reason: str) -> str:
    return {
        "permission_uncertain": "obtain accepted authority or limit use before normalization",
        "identity_uncertain": "confirm subject/speaker/face identity before generation use",
        "quality_uncertain": "review quality or request a higher-quality replacement",
        "known_dispute": "resolve dispute before source can feed artifact generation",
    }.get(reason, "review source before artifact generation")


def _rights_notes(authority_attestation: dict[str, Any]) -> str:
    scope = authority_attestation.get("likeness_use_scope") or "unknown"
    return f"Uploader attests archive submission authority; likeness use scope: {scope}."


def _usable_for_modality(modality: str) -> list[str]:
    if modality == "text":
        return ["memorial_text", "memory_page", "story"]
    if modality == "audio":
        return ["voice_context", "expression_sample", "private_audio"]
    return ["video_context", "expression_sample", "private_video"]


def _usable_for_archive_media(media_type: str) -> list[str]:
    return {
        "text": ["memorial_text", "memory_page", "story"],
        "transcript": ["memorial_text", "memory_page", "story"],
        "document": ["memorial_text", "memory_page", "authority_review"],
        "image": ["visual_context", "memory_page"],
        "audio": ["voice_context", "expression_sample"],
        "video": ["video_context", "expression_sample"],
    }[media_type]


def _required_kind_for_family(family: str) -> str | None:
    if family in VOICE_FAMILIES:
        return "audio"
    if family in VIDEO_FAMILIES:
        return "video"
    if family in {"memorial_text", "memory_page", "letter", "story"}:
        return "text"
    return None


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def raise_validation(message: str) -> None:
    raise HTTPException(status_code=400, detail=message)
