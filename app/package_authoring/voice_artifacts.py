from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import HTTPException

from .validation import ID_PATTERN, authority_preflight, raise_validation, validate_ids_and_leakage

VOICE_CONTRACT_VERSION = "1.0.0"
MASTERING_REPORT_VERSION = "1.0.0"
REPO_LOCAL_PREFIXES = (
    "/host/repos/",
    "file:///host/repos/",
    "/home/node/.openclaw/workspace/",
    "file:///home/node/.openclaw/workspace/",
)
TEMP_ROOT_PREFIXES = ("/tmp/", "/var/tmp/", "file:///tmp/", "file:///var/tmp/")
APPROVED_EXTERNAL_ROOT_PREFIXES = (
    "gcs://",
    "s3://",
    "az://",
    "sanctra-storage://",
    "voice-artifact-storage://",
    "file:///srv/voice-data/",
    "storage-policy:",
)
MEDIA_OR_MODEL_KEYS = {
    "audio",
    "audio_base64",
    "audio_bytes",
    "model",
    "model_bytes",
    "model_path",
    "wav",
    "mp3",
}
LOCAL_PATH_PATTERN = re.compile(r"(^|\s)(?:\.\.?/|/host/|/tmp/|/var/tmp/|[A-Za-z]:\\)")


@dataclass(frozen=True)
class VoiceArtifactSubmission:
    voice_job_ref: str
    status: str
    request_hash: str
    submitted_at: str


class VoiceArtifactJobClient(Protocol):
    def submit(self, request: dict[str, Any]) -> VoiceArtifactSubmission: ...
    def inspect(self, job_ref: str) -> dict[str, Any]: ...
    def manifest(self, job_ref: str) -> dict[str, Any]: ...
    def revoke(self, job_ref: str, reason: str, revocation_ref: str) -> dict[str, Any]: ...


class FakeVoiceArtifactJobClient:
    """Dependency-free test adapter; imports no OpenVoice/RVC runtime."""

    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def submit(self, request: dict[str, Any]) -> VoiceArtifactSubmission:
        validate_voice_job_request(request)
        self.submitted.append(deepcopy(request))
        request_hash = _stable_hash(request)
        request_id = request["caller"]["request_id"].replace(":", "_")
        return VoiceArtifactSubmission(
            voice_job_ref=f"voice_job_fake_{request_id}",
            status="submitted",
            request_hash=request_hash,
            submitted_at=_now(),
        )

    def inspect(self, job_ref: str) -> dict[str, Any]:
        _require_id(job_ref, "job_ref")
        return {"voice_job_ref": job_ref, "status": "submitted", "adapter": "fake"}

    def manifest(self, job_ref: str) -> dict[str, Any]:
        _require_id(job_ref, "job_ref")
        return {"voice_job_ref": job_ref, "status": "manifest_pending", "adapter": "fake"}

    def revoke(self, job_ref: str, reason: str, revocation_ref: str) -> dict[str, Any]:
        _require_id(job_ref, "job_ref")
        _require_id(revocation_ref, "revocation_ref")
        if not reason:
            raise_validation("revocation reason is required")
        return {"voice_job_ref": job_ref, "status": "revoked", "reason": reason, "revocation_ref": revocation_ref}


def build_voice_job_request(bundle: dict[str, Any], request: dict[str, Any], preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise_validation("voice artifact request must be a JSON object")
    validate_ids_and_leakage(request, "voice_artifact_request")
    reject_local_or_embedded_artifacts(request, "voice_artifact_request")

    package_id = _require_id(request.get("package_id"), "package_id")
    request_id = _require_id(request.get("request_id"), "request_id")
    persona_id = _require_id(request.get("persona_id"), "persona_id")
    person_id = _require_id(request.get("person_id"), "person_id")
    subject_ref = _require_id(request.get("subject_ref"), "subject_ref")
    requester_ref = _require_id(
        request.get("requester_ref") or (request.get("relationship_context") or {}).get("requester_role_ref"),
        "requester_ref",
    )
    _require_package(bundle, package_id)

    consent = request.get("consent") or {}
    consent_ref = _require_id(consent.get("consent_ref"), "consent.consent_ref")
    authority_record_refs = consent.get("authority_record_refs") or []
    if not authority_record_refs or not all(isinstance(ref, str) and ID_PATTERN.match(ref) for ref in authority_record_refs):
        raise_validation("consent.authority_record_refs must include stable Sanctra ids")
    disclosure_label = consent.get("disclosure_label")
    if consent.get("disclosure_required") is not True or not isinstance(disclosure_label, str) or not disclosure_label.strip():
        raise HTTPException(status_code=403, detail="voice artifact requests require disclosure and a non-empty disclosure label")

    output = request.get("output") or {}
    use_case = normalize_use_case(output.get("use_case") or request.get("use_case"))
    visibility = normalize_visibility(output.get("visibility") or request.get("visibility"), use_case)
    target_root_ref = output.get("target_root_ref")
    validate_external_target_root(target_root_ref)
    final_formats = output.get("final_formats") or ["wav", "mp3"]
    if not final_formats or any(fmt not in {"wav", "mp3"} for fmt in final_formats):
        raise_validation("output.final_formats must contain wav and/or mp3")

    require_public_review = visibility in {"limited", "public"} or use_case == "memorial_public_audio"
    quality_policy = request.get("quality_policy") or {}
    if require_public_review and quality_policy.get("require_human_review") is False:
        raise HTTPException(status_code=403, detail="public/limited-public voice artifacts require human review policy")

    requested_use = "public_audio" if use_case == "memorial_public_audio" else "private_audio"
    preflight_result = preflight or authority_preflight(bundle, "voice_message", requested_use, subject_ref)
    if not preflight_result.get("allowed"):
        raise HTTPException(status_code=403, detail={"message": "voice authority preflight denied", "preflight": preflight_result})
    missing_authority = [ref for ref in authority_record_refs if ref not in set(preflight_result.get("authority_record_refs") or [])]
    if missing_authority:
        raise HTTPException(status_code=403, detail=f"voice authority preflight did not approve refs: {missing_authority}")

    script = request.get("script") or {}
    mode = script.get("mode") or "inline_text"
    if mode not in {"inline_text", "script_ref"}:
        raise_validation("script.mode must be inline_text or script_ref")
    text = script.get("text")
    script_ref = script.get("script_ref")
    if mode == "inline_text" and not (isinstance(text, str) and text.strip()):
        raise_validation("script.text is required for inline_text voice requests")
    if mode == "script_ref":
        script_ref = _require_id(script_ref, "script.script_ref")
    language = script.get("language") or "en-US"
    text_hash = script.get("text_hash") or (f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}" if isinstance(text, str) else None)

    callback_ref = (request.get("callback") or {}).get("callback_ref") or f"sanctra://packages/{package_id}/voice-artifact-requests/{request_id}"
    if not isinstance(callback_ref, str) or not callback_ref.startswith(f"sanctra://packages/{package_id}/voice-artifact-requests/{request_id}"):
        raise_validation("callback.callback_ref must be a Sanctra package voice-artifact callback ref")

    return {
        "contract_version": VOICE_CONTRACT_VERSION,
        "job_type": "offline_voice_artifact",
        "caller": {"system": "sanctra", "request_id": request_id, "user_or_agent_ref": requester_ref},
        "persona_id": persona_id,
        "input": {"mode": mode, "text": text if mode == "inline_text" else None, "script_ref": script_ref, "language": language, "text_hash": text_hash},
        "output": {
            "use_case": use_case,
            "visibility": visibility,
            "target_root_ref": target_root_ref,
            "final_formats": final_formats,
            "keep_intermediates": bool(output.get("keep_intermediates", True)),
        },
        "style_controls": _style_controls(request.get("style_controls") or {}),
        "quality_policy": {
            "policy_id": quality_policy.get("policy_id") or "memorial_review_required",
            "require_human_review": bool(quality_policy.get("require_human_review", True)),
            "fail_on_openvoice_warnings": bool(quality_policy.get("fail_on_openvoice_warnings", False)),
            "fail_on_rvc_warnings": bool(quality_policy.get("fail_on_rvc_warnings", False)),
        },
        "caller_metadata": {
            "consent_ref": consent_ref,
            "disclosure_required": True,
            "disclosure_label": disclosure_label,
            "sanctra_person_id": person_id,
            "sanctra_package_id": package_id,
            "narratron_project_id": None,
            "callback_ref": callback_ref,
        },
        "retention": {
            "class": output.get("retention_class") or "package_artifact",
            "delete_intermediates_after": output.get("delete_intermediates_after"),
            "revocation_behavior": output.get("revocation_behavior") or "manual_review_required",
        },
    }


def package_voice_request_record(request: dict[str, Any], job_request: dict[str, Any], submission: VoiceArtifactSubmission) -> dict[str, Any]:
    callback_ref = job_request["caller_metadata"]["callback_ref"]
    manifest_slot = (request.get("callback") or {}).get("expected_manifest_slot")
    if manifest_slot is not None:
        _require_id(manifest_slot, "callback.expected_manifest_slot")
    return {
        "request_id": job_request["caller"]["request_id"],
        "package_id": job_request["caller_metadata"]["sanctra_package_id"],
        "person_id": job_request["caller_metadata"]["sanctra_person_id"],
        "persona_id": job_request["persona_id"],
        "consent_ref": job_request["caller_metadata"]["consent_ref"],
        "authority_record_refs": list((request.get("consent") or {}).get("authority_record_refs") or []),
        "callback_ref": callback_ref,
        "expected_manifest_slot": manifest_slot,
        "status": "submitted",
        "voice_job_ref": submission.voice_job_ref,
        "artifact_manifest_ref": None,
        "request_hash": submission.request_hash,
        "submitted_at": submission.submitted_at,
        "updated_at": submission.submitted_at,
    }


def upsert_voice_request(bundle: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    updated = dict(bundle)
    requests = list(updated.get("voice_artifact_requests", []))
    for idx, existing in enumerate(requests):
        if existing.get("request_id") == record["request_id"]:
            requests[idx] = record
            break
    else:
        requests.append(record)
    updated["voice_artifact_requests"] = requests
    validate_ids_and_leakage(updated, "bundle")
    reject_local_or_embedded_artifacts(updated.get("voice_artifact_requests", []), "bundle.voice_artifact_requests")
    return updated


def find_voice_request(bundle: dict[str, Any], request_id: str) -> dict[str, Any]:
    _require_id(request_id, "request_id")
    for request in bundle.get("voice_artifact_requests", []):
        if request.get("request_id") == request_id:
            return request
    raise HTTPException(status_code=404, detail=f"unknown voice artifact request {request_id}")


def validate_voice_manifest_import(bundle: dict[str, Any], request_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    request = find_voice_request(bundle, request_id)
    if not isinstance(manifest, dict):
        raise_validation("manifest must be a JSON object")
    validate_ids_and_leakage(manifest, "voice_manifest")
    reject_local_or_embedded_artifacts(manifest, "voice_manifest")
    caller_metadata = manifest.get("caller_metadata") or {}
    if caller_metadata:
        if caller_metadata.get("sanctra_package_id") not in {None, request["package_id"]}:
            raise_validation("voice manifest package metadata mismatch")
        if caller_metadata.get("consent_ref") not in {None, request["consent_ref"]}:
            raise_validation("voice manifest consent metadata mismatch")
    if manifest.get("artifact_type") not in {None, "voice_message"}:
        raise_validation("voice manifest import only accepts voice_message artifacts")
    return manifest


def mark_manifest_received(bundle: dict[str, Any], request_id: str, manifest_id: str) -> dict[str, Any]:
    updated = dict(bundle)
    requests = []
    for request in updated.get("voice_artifact_requests", []):
        if request.get("request_id") == request_id:
            request = dict(request)
            request["artifact_manifest_ref"] = manifest_id
            request["status"] = "manifest_received"
            request["updated_at"] = _now()
        requests.append(request)
    updated["voice_artifact_requests"] = requests
    return updated


def build_mastering_report(bundle: dict[str, Any], request_id: str, report: dict[str, Any]) -> dict[str, Any]:
    request = find_voice_request(bundle, request_id)
    if not isinstance(report, dict):
        raise_validation("mastering report must be a JSON object")
    validate_ids_and_leakage(report, "mastering_report")
    reject_local_or_embedded_artifacts(report, "mastering_report")

    report_id = _require_id(report.get("report_id"), "report_id")
    manifest_id = _require_id(report.get("manifest_id") or request.get("artifact_manifest_ref") or request.get("expected_manifest_slot"), "manifest_id")
    voice_job_ref = _require_id(report.get("voice_job_ref") or request.get("voice_job_ref"), "voice_job_ref")
    if voice_job_ref != request.get("voice_job_ref"):
        raise_validation("mastering report voice_job_ref does not match request")

    chunk_outcomes = _validate_chunk_outcomes(report.get("chunk_outcomes"))
    audio_targets = _validate_audio_targets(report.get("audio_targets") or {})
    final_artifact_uris = _validate_final_artifact_uris(report.get("final_artifact_uris"))
    final_outcome = _derive_mastering_outcome(chunk_outcomes, audio_targets)
    if report.get("final_outcome") and report["final_outcome"] != final_outcome:
        raise_validation("mastering report final_outcome does not match chunk/audio checks")

    report_uri = report.get("report_uri") or _default_mastering_report_uri(request, final_artifact_uris)
    validate_external_target_root(report_uri)

    return {
        "contract_version": MASTERING_REPORT_VERSION,
        "report_id": report_id,
        "report_uri": report_uri,
        "request_id": request_id,
        "package_id": request["package_id"],
        "manifest_id": manifest_id,
        "voice_job_ref": voice_job_ref,
        "chunk_outcomes": chunk_outcomes,
        "final_outcome": final_outcome,
        "loudness_target": audio_targets["loudness_target"],
        "peak_ceiling": audio_targets["peak_ceiling"],
        "silence_trim": audio_targets["silence_trim"],
        "seam_artifact_checks": audio_targets["seam_artifact_checks"],
        "sample_rate_channel_conformity": audio_targets["sample_rate_channel_conformity"],
        "clipping": audio_targets["clipping"],
        "final_artifact_uris": final_artifact_uris,
        "disclosure_required": True,
        "disclosure_label": request.get("consent_ref") and (report.get("disclosure_label") or "Generated voice memorial artifact; disclosure required."),
        "review_required": bool(report.get("review_required", True)),
        "created_at": report.get("created_at") or _now(),
    }


def store_mastering_report(bundle: dict[str, Any], request_id: str, report: dict[str, Any]) -> dict[str, Any]:
    updated = dict(bundle)
    reports = list(updated.get("mastering_reports", []))
    for idx, existing in enumerate(reports):
        if existing.get("report_id") == report["report_id"]:
            reports[idx] = report
            break
    else:
        reports.append(report)
    updated["mastering_reports"] = reports

    manifests = []
    manifest_found = False
    for manifest in updated.get("artifact_manifests", []):
        if manifest.get("manifest_id") == report["manifest_id"]:
            manifest = dict(manifest)
            manifest["mastering_report_uri"] = report["report_uri"]
            review = dict(manifest.get("human_review") or {})
            mastering_refs = list(review.get("mastering_report_refs") or [])
            if report["report_id"] not in mastering_refs:
                mastering_refs.append(report["report_id"])
            if review:
                review["mastering_report_refs"] = mastering_refs
                manifest["human_review"] = review
            manifest_found = True
        manifests.append(manifest)
    if not manifest_found:
        raise_validation("mastering report manifest_id does not match an artifact manifest")
    updated["artifact_manifests"] = manifests

    requests = []
    request_found = False
    for request in updated.get("voice_artifact_requests", []):
        if request.get("request_id") == request_id:
            request = dict(request)
            request["mastering_report_ref"] = report["report_id"]
            request["mastering_report_uri"] = report["report_uri"]
            request["status"] = f"mastering_{report['final_outcome']}"
            request["updated_at"] = _now()
            request_found = True
        requests.append(request)
    if not request_found:
        raise_validation("unknown voice artifact request for mastering report")
    updated["voice_artifact_requests"] = requests
    validate_ids_and_leakage(updated, "bundle")
    reject_local_or_embedded_artifacts(updated.get("mastering_reports", []), "bundle.mastering_reports")
    return updated


def normalize_use_case(value: Any) -> str:
    mapping = {
        "private_voice_message": "memorial_private_audio",
        "private_audio": "memorial_private_audio",
        "public_story_audio": "memorial_public_audio",
        "public_audio": "memorial_public_audio",
    }
    use_case = mapping.get(value, value)
    if use_case not in {"memorial_private_audio", "memorial_public_audio"}:
        raise_validation("voice artifact output.use_case must map to memorial_private_audio or memorial_public_audio")
    return use_case


def normalize_visibility(value: Any, use_case: str) -> str:
    visibility = value or ("public" if use_case == "memorial_public_audio" else "private")
    if visibility not in {"private", "limited", "public"}:
        raise_validation("voice artifact output.visibility must be private, limited, or public")
    if use_case == "memorial_public_audio" and visibility == "private":
        raise_validation("memorial_public_audio cannot use private visibility")
    return visibility


def validate_external_target_root(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise_validation("output.target_root_ref is required")
    lowered = value.lower()
    if any(lowered.startswith(prefix) for prefix in REPO_LOCAL_PREFIXES) or any(lowered.startswith(prefix) for prefix in TEMP_ROOT_PREFIXES):
        raise_validation("output.target_root_ref must not be repo-local or temp-only")
    if LOCAL_PATH_PATTERN.search(value):
        raise_validation("output.target_root_ref must be an external artifact root ref")
    if not any(value.startswith(prefix) for prefix in APPROVED_EXTERNAL_ROOT_PREFIXES):
        raise_validation("output.target_root_ref must use an approved external artifact storage root")


def reject_local_or_embedded_artifacts(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered_key = key.lower()
            if lowered_key in MEDIA_OR_MODEL_KEYS and isinstance(child, (bytes, bytearray)):
                raise_validation(f"generated media/model blobs are not allowed at {path}.{key}")
            if lowered_key in MEDIA_OR_MODEL_KEYS and isinstance(child, str) and len(child) > 256:
                raise_validation(f"embedded generated media/model payload rejected at {path}.{key}")
            reject_local_or_embedded_artifacts(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_local_or_embedded_artifacts(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(lowered.startswith(prefix) for prefix in REPO_LOCAL_PREFIXES) or any(lowered.startswith(prefix) for prefix in TEMP_ROOT_PREFIXES):
            raise_validation(f"repo-local/temp artifact path rejected at {path}")


def validate_voice_job_request(request: dict[str, Any]) -> None:
    if request.get("contract_version") != VOICE_CONTRACT_VERSION or request.get("job_type") != "offline_voice_artifact":
        raise_validation("invalid voice job contract header")
    validate_external_target_root((request.get("output") or {}).get("target_root_ref"))
    metadata = request.get("caller_metadata") or {}
    if not metadata.get("consent_ref") or metadata.get("disclosure_required") is not True or not metadata.get("disclosure_label"):
        raise_validation("voice job request requires consent and disclosure metadata")
    reject_local_or_embedded_artifacts(request, "voice_job_request")
    validate_ids_and_leakage(request, "voice_job_request")


def _validate_chunk_outcomes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise_validation("mastering report chunk_outcomes must be a non-empty array")
    chunks: list[dict[str, Any]] = []
    for idx, chunk in enumerate(value):
        if not isinstance(chunk, dict):
            raise_validation("mastering report chunk_outcomes entries must be objects")
        chunk_id = _require_id(chunk.get("chunk_id"), f"chunk_outcomes[{idx}].chunk_id")
        outcome = chunk.get("outcome")
        if outcome not in {"pass", "warn", "fail"}:
            raise_validation("chunk outcome must be pass, warn, or fail")
        chunks.append({"chunk_id": chunk_id, "outcome": outcome, "warnings": list(chunk.get("warnings") or []), "artifact_uri": chunk.get("artifact_uri")})
    return chunks


def _validate_audio_targets(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "loudness_target_lufs",
        "integrated_loudness_lufs",
        "true_peak_ceiling_dbtp",
        "measured_true_peak_dbtp",
        "expected_sample_rate_hz",
        "sample_rate_hz",
        "expected_channels",
        "channels",
    }
    missing = sorted(key for key in required if key not in value)
    if missing:
        raise_validation(f"mastering report audio_targets missing {missing}")
    tolerance = float(value.get("loudness_tolerance_lufs", 1.0))
    loudness_delta = abs(float(value["integrated_loudness_lufs"]) - float(value["loudness_target_lufs"]))
    peak_violation = float(value["measured_true_peak_dbtp"]) > float(value["true_peak_ceiling_dbtp"])
    clipping_detected = bool(value.get("clipping_detected"))
    sample_rate_matches = int(value["sample_rate_hz"]) == int(value["expected_sample_rate_hz"])
    channels_match = int(value["channels"]) == int(value["expected_channels"])
    unexpected_silences = list(value.get("unexpected_long_silences") or [])
    seam_checks = _validate_seam_checks(value.get("seam_artifact_checks") or [])

    return {
        "loudness_target": {
            "target_lufs": float(value["loudness_target_lufs"]),
            "integrated_loudness_lufs": float(value["integrated_loudness_lufs"]),
            "tolerance_lufs": tolerance,
            "outcome": "pass" if loudness_delta <= tolerance else "fail",
        },
        "peak_ceiling": {
            "ceiling_dbtp": float(value["true_peak_ceiling_dbtp"]),
            "measured_true_peak_dbtp": float(value["measured_true_peak_dbtp"]),
            "outcome": "fail" if peak_violation else "pass",
        },
        "silence_trim": value.get("silence_trim") or {"applied": False},
        "unexpected_long_silences": unexpected_silences,
        "seam_artifact_checks": seam_checks,
        "sample_rate_channel_conformity": {
            "expected_sample_rate_hz": int(value["expected_sample_rate_hz"]),
            "sample_rate_hz": int(value["sample_rate_hz"]),
            "expected_channels": int(value["expected_channels"]),
            "channels": int(value["channels"]),
            "outcome": "pass" if sample_rate_matches and channels_match else "fail",
        },
        "clipping": {"detected": clipping_detected, "outcome": "fail" if clipping_detected else "pass"},
    }


def _validate_seam_checks(value: list[Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for idx, check in enumerate(value):
        if not isinstance(check, dict):
            raise_validation("seam_artifact_checks entries must be objects")
        seam_id = _require_id(check.get("seam_id"), f"seam_artifact_checks[{idx}].seam_id")
        outcome = check.get("outcome")
        if outcome not in {"pass", "warn", "fail"}:
            raise_validation("seam artifact outcome must be pass, warn, or fail")
        checks.append({"seam_id": seam_id, "outcome": outcome, "notes": check.get("notes") or ""})
    return checks


def _derive_mastering_outcome(chunks: list[dict[str, Any]], audio_targets: dict[str, Any]) -> str:
    outcomes = [chunk["outcome"] for chunk in chunks]
    outcomes.extend(audio_targets["loudness_target"]["outcome"] for _ in [0])
    outcomes.append(audio_targets["peak_ceiling"]["outcome"])
    outcomes.append(audio_targets["sample_rate_channel_conformity"]["outcome"])
    outcomes.append(audio_targets["clipping"]["outcome"])
    outcomes.extend(check["outcome"] for check in audio_targets["seam_artifact_checks"])
    if audio_targets["unexpected_long_silences"]:
        outcomes.append("warn")
    if "fail" in outcomes:
        return "fail"
    if "warn" in outcomes:
        return "warn"
    return "pass"


def _validate_final_artifact_uris(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise_validation("mastering report final_artifact_uris must be a non-empty array")
    for uri in value:
        validate_external_target_root(uri)
    return list(value)


def _default_mastering_report_uri(request: dict[str, Any], final_artifact_uris: list[str]) -> str:
    root = str((final_artifact_uris[0]).rsplit("/", 1)[0])
    if root.endswith("/final"):
        root = root.rsplit("/", 1)[0]
    return f"{root}/reports/final/mastering_report.json"


def _style_controls(value: dict[str, Any]) -> dict[str, Any]:
    chunking = value.get("chunking") or {}
    return {
        "openvoice_style_preset": value.get("openvoice_style_preset") or "warm_memorial_reading",
        "emotion": value.get("emotion") or "gentle",
        "pace": value.get("pace") or "measured",
        "pronunciation_notes": value.get("pronunciation_notes"),
        "chunking": {"max_chars": int(chunking.get("max_chars") or 900), "split_on": chunking.get("split_on") or ["paragraph", "sentence"]},
    }


def _require_package(bundle: dict[str, Any], package_id: str) -> None:
    if package_id not in {pkg.get("package_id") for pkg in bundle.get("memorial_packages", [])}:
        raise_validation(f"unknown package_id {package_id}")


def _require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise_validation(f"{field} must be a stable Sanctra id")
    return value


def _stable_hash(value: dict[str, Any]) -> str:
    import json

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
