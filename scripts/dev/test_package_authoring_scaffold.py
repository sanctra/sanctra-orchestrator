from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["SANCTRA_PACKAGE_STORE_DIR"] = tempfile.mkdtemp(prefix="sanctra-package-store-test-")

from app.main import app  # noqa: E402
EXAMPLE = ROOT.parent / "async-memorial-package-scaffold" / "examples" / "tier1-text-plus-approved-likeness.example.json"


def assert_status(response, expected: int) -> dict:
    assert response.status_code == expected, response.text
    if response.content:
        return response.json()
    return {}


def main() -> None:
    bundle = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    package_id = bundle["memorial_packages"][0]["package_id"]
    client = TestClient(app)

    created = assert_status(client.post("/packages", json={"bundle": bundle}), 200)
    assert created["package_id"] == package_id

    fetched = assert_status(client.get(f"/packages/{package_id}"), 200)
    assert fetched["bundle"]["schema_version"] == "sanctra.async_memorial_package.v0"

    denied = assert_status(
        client.post(
            f"/packages/{package_id}/authority-preflight",
            json={"artifact_type": "voice_message", "requested_use": "public_audio", "subject_ref": "subject:maria_ellis"},
        ),
        200,
    )
    assert denied["allowed"] is False

    allowed = assert_status(
        client.post(
            f"/packages/{package_id}/authority-preflight",
            json={"artifact_type": "voice_message", "requested_use": "private_audio", "subject_ref": "subject:maria_ellis"},
        ),
        200,
    )
    assert allowed["allowed"] is True
    assert allowed["authority_record_refs"] == ["authority:family_audio_video_001"]

    updated = deepcopy(bundle)
    updated["memorial_packages"][0]["status"] = "artifact_production"
    replaced = assert_status(client.put(f"/packages/{package_id}", json={"bundle": updated}), 200)
    assert replaced["status"] == "artifact_production"

    manifest = deepcopy(bundle["artifact_manifests"][1])
    manifest["manifest_id"] = "manifest:runtime_private_voice_001"
    manifest["outputs"][0]["artifact_id"] = "artifact:runtime_private_voice_mp3_001"
    written = assert_status(client.post(f"/packages/{package_id}/artifact-manifests", json={"manifest": manifest}), 200)
    assert written == {"manifest_id": "manifest:runtime_private_voice_001", "artifact_status": "planned"}

    voice_request_id = "sanctra_voice_req_private_001"
    voice_request = {
        "request_id": voice_request_id,
        "package_id": package_id,
        "person_id": "person:maria_ellis",
        "persona_id": "voice_persona:maria_ellis_private_v0",
        "subject_ref": "subject:maria_ellis",
        "relationship_context": {
            "requester_role_ref": "stakeholder:requester_dana",
            "intended_audience": "private_family",
        },
        "script": {
            "mode": "inline_text",
            "text": "Dana, I am always with you in the garden and around the Sunday table.",
            "language": "en-US",
        },
        "consent": {
            "consent_ref": "authority:family_audio_video_001",
            "authority_record_refs": ["authority:family_audio_video_001"],
            "disclosure_required": True,
            "disclosure_label": "Private generated voice memorial created from family-authorized audio samples.",
        },
        "output": {
            "use_case": "private_voice_message",
            "visibility": "private",
            "target_root_ref": "gcs://sanctra-voice-artifacts/packages/package-maria-ellis-async-001",
            "final_formats": ["wav", "mp3"],
            "retention_class": "package_artifact",
        },
        "callback": {"expected_manifest_slot": "manifest:runtime_private_voice_001"},
    }
    submitted = assert_status(
        client.post(f"/packages/{package_id}/voice-artifact-requests/{voice_request_id}/submit", json={"request": voice_request}),
        200,
    )
    assert submitted["job_request"]["contract_version"] == "1.0.0"
    assert submitted["job_request"]["job_type"] == "offline_voice_artifact"
    assert submitted["job_request"]["output"]["use_case"] == "memorial_private_audio"
    assert submitted["request"]["voice_job_ref"].startswith("voice_job_fake_sanctra_voice_req_private_001")

    missing_consent = deepcopy(voice_request)
    missing_consent["request_id"] = "sanctra_voice_req_missing_consent"
    missing_consent["consent"].pop("consent_ref")
    assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/sanctra_voice_req_missing_consent/submit",
            json={"request": missing_consent},
        ),
        400,
    )

    denied_public = deepcopy(voice_request)
    denied_public["request_id"] = "sanctra_voice_req_public_denied"
    denied_public["output"]["use_case"] = "public_story_audio"
    denied_public["output"]["visibility"] = "public"
    assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/sanctra_voice_req_public_denied/submit",
            json={"request": denied_public},
        ),
        403,
    )

    repo_local = deepcopy(voice_request)
    repo_local["request_id"] = "sanctra_voice_req_repo_local"
    repo_local["output"]["target_root_ref"] = "/host/repos/Sanctra/generated/private.wav"
    assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/sanctra_voice_req_repo_local/submit",
            json={"request": repo_local},
        ),
        400,
    )

    voice_manifest = deepcopy(manifest)
    voice_manifest["manifest_id"] = "manifest:runtime_private_voice_imported_001"
    voice_manifest["outputs"][0]["artifact_id"] = "artifact:runtime_private_voice_imported_mp3_001"
    voice_manifest["outputs"][0]["storage_uri"] = "gcs://sanctra-voice-artifacts/packages/package-maria-ellis-async-001/private-message-v1.mp3"
    voice_manifest["generation_refs"] = [{"kind": "voice_job", "ref": submitted["request"]["voice_job_ref"]}]
    voice_manifest["caller_metadata"] = {
        "sanctra_package_id": package_id,
        "consent_ref": "authority:family_audio_video_001",
    }
    imported = assert_status(
        client.post(f"/packages/{package_id}/voice-artifact-requests/{voice_request_id}/manifest", json={"manifest": voice_manifest}),
        200,
    )
    assert imported == {
        "request_id": voice_request_id,
        "manifest_id": "manifest:runtime_private_voice_imported_001",
        "status": "manifest_received",
    }

    base_mastering_report = {
        "report_id": "mastering:private_message_pass_001",
        "manifest_id": "manifest:runtime_private_voice_imported_001",
        "voice_job_ref": submitted["request"]["voice_job_ref"],
        "chunk_outcomes": [
            {"chunk_id": "chunk:private_message_001", "outcome": "pass"},
            {"chunk_id": "chunk:private_message_002", "outcome": "pass"},
        ],
        "audio_targets": {
            "loudness_target_lufs": -16.0,
            "integrated_loudness_lufs": -16.2,
            "loudness_tolerance_lufs": 1.0,
            "true_peak_ceiling_dbtp": -1.0,
            "measured_true_peak_dbtp": -1.4,
            "expected_sample_rate_hz": 48000,
            "sample_rate_hz": 48000,
            "expected_channels": 1,
            "channels": 1,
            "clipping_detected": False,
            "silence_trim": {"leading_ms": 80, "trailing_ms": 120, "max_internal_silence_ms": 900},
            "unexpected_long_silences": [],
            "seam_artifact_checks": [{"seam_id": "seam:private_message_001_002", "outcome": "pass"}],
        },
        "final_artifact_uris": [
            "gcs://sanctra-voice-artifacts/packages/package-maria-ellis-async-001/private-message-v1.wav",
            "gcs://sanctra-voice-artifacts/packages/package-maria-ellis-async-001/private-message-v1.mp3",
        ],
        "final_outcome": "pass",
        "review_required": True,
    }
    mastering_pass = assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/{voice_request_id}/mastering-report",
            json={"report": base_mastering_report},
        ),
        200,
    )
    assert mastering_pass == {
        "request_id": voice_request_id,
        "report_id": "mastering:private_message_pass_001",
        "manifest_id": "manifest:runtime_private_voice_imported_001",
        "final_outcome": "pass",
        "mastering_report_uri": "gcs://sanctra-voice-artifacts/packages/package-maria-ellis-async-001/reports/final/mastering_report.json",
    }
    fetched_after_mastering = assert_status(client.get(f"/packages/{package_id}"), 200)
    mastered_manifest = {
        item["manifest_id"]: item for item in fetched_after_mastering["bundle"]["artifact_manifests"]
    }["manifest:runtime_private_voice_imported_001"]
    assert mastered_manifest["mastering_report_uri"] == mastering_pass["mastering_report_uri"]
    assert fetched_after_mastering["bundle"]["mastering_reports"][0]["final_outcome"] == "pass"

    warn_report = deepcopy(base_mastering_report)
    warn_report["report_id"] = "mastering:private_message_warn_001"
    warn_report["chunk_outcomes"][1]["outcome"] = "warn"
    warn_report["chunk_outcomes"][1]["warnings"] = ["minor breath noise retained"]
    warn_report["final_outcome"] = "warn"
    assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/{voice_request_id}/mastering-report",
            json={"report": warn_report},
        ),
        200,
    )["final_outcome"] == "warn"

    fail_report = deepcopy(base_mastering_report)
    fail_report["report_id"] = "mastering:private_message_fail_001"
    fail_report["chunk_outcomes"][0]["outcome"] = "fail"
    fail_report["final_outcome"] = "fail"
    assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/{voice_request_id}/mastering-report",
            json={"report": fail_report},
        ),
        200,
    )["final_outcome"] == "fail"

    clipping_violation = deepcopy(base_mastering_report)
    clipping_violation["report_id"] = "mastering:private_message_bad_peak_001"
    clipping_violation["audio_targets"]["measured_true_peak_dbtp"] = -0.2
    clipping_violation["audio_targets"]["clipping_detected"] = True
    clipping_violation["final_outcome"] = "pass"
    assert_status(
        client.post(
            f"/packages/{package_id}/voice-artifact-requests/{voice_request_id}/mastering-report",
            json={"report": clipping_violation},
        ),
        400,
    )

    delivery_without_mastering = deepcopy(voice_manifest)
    delivery_without_mastering["manifest_id"] = "manifest:runtime_delivery_without_mastering_001"
    delivery_without_mastering["artifact_status"] = "delivered"
    delivery_without_mastering["outputs"][0]["artifact_id"] = "artifact:runtime_delivery_without_mastering_mp3_001"
    delivery_without_mastering["human_review"] = {
        "review_required": True,
        "state": "approved",
        "reviewer_ref": "stakeholder:consultant_01",
        "reviewer_identity_ref": "staff_contact:consultant_01",
        "decided_at": "2026-04-29T13:00:00Z",
        "notes": "Review passed, but mastering link was not attached.",
        "quality_gate_refs": ["gate:voice_clone_private_001"],
        "qa_report_refs": ["voice-qa:private-message-pass-001"],
        "mastering_report_refs": ["mastering:private-message-pass-001"],
        "review_decision_refs": [],
    }
    assert_status(client.post(f"/packages/{package_id}/artifact-manifests", json={"manifest": delivery_without_mastering}), 403)

    pending_delivery = deepcopy(voice_manifest)
    pending_delivery["manifest_id"] = "manifest:runtime_pending_delivery_001"
    pending_delivery["artifact_status"] = "delivered"
    pending_delivery["outputs"][0]["artifact_id"] = "artifact:runtime_pending_delivery_mp3_001"
    pending_delivery["human_review"] = {
        "review_required": True,
        "state": "required_pending",
        "quality_gate_refs": ["gate:voice_clone_private_001"],
        "qa_report_refs": ["voice-qa:private-message-pass-001"],
        "mastering_report_refs": ["mastering:private-message-pass-001"],
        "review_decision_refs": [],
    }
    assert_status(client.post(f"/packages/{package_id}/artifact-manifests", json={"manifest": pending_delivery}), 403)

    approved_delivery = deepcopy(pending_delivery)
    approved_delivery["manifest_id"] = "manifest:runtime_approved_delivery_001"
    approved_delivery["outputs"][0]["artifact_id"] = "artifact:runtime_approved_delivery_mp3_001"
    approved_delivery["human_review"].update(
        {
            "state": "approved",
            "reviewer_ref": "stakeholder:consultant_01",
            "reviewer_identity_ref": "staff_contact:consultant_01",
            "decided_at": "2026-04-29T13:00:00Z",
            "notes": "QA and mastering reports reviewed; approved for private family delivery.",
        }
    )
    approved_delivery["mastering_report_uri"] = mastering_pass["mastering_report_uri"]
    approved = assert_status(client.post(f"/packages/{package_id}/artifact-manifests", json={"manifest": approved_delivery}), 200)
    assert approved == {"manifest_id": "manifest:runtime_approved_delivery_001", "artifact_status": "delivered"}

    changes_requested = deepcopy(approved_delivery)
    changes_requested["manifest_id"] = "manifest:runtime_changes_requested_001"
    changes_requested["artifact_status"] = "generated"
    changes_requested["outputs"][0]["artifact_id"] = "artifact:runtime_changes_requested_mp3_001"
    changes_requested["human_review"].update(
        {
            "state": "changes_requested",
            "notes": "Mastering report found mouth-click artifacts; regenerate before delivery.",
            "qa_report_refs": ["voice-qa:private-message-clicks-001"],
            "mastering_report_refs": ["mastering:private-message-clicks-001"],
        }
    )
    assert_status(client.post(f"/packages/{package_id}/artifact-manifests", json={"manifest": changes_requested}), 200)

    rejected_delivery = deepcopy(changes_requested)
    rejected_delivery["manifest_id"] = "manifest:runtime_rejected_delivery_001"
    rejected_delivery["artifact_status"] = "delivered"
    rejected_delivery["outputs"][0]["artifact_id"] = "artifact:runtime_rejected_delivery_mp3_001"
    rejected_delivery["human_review"].update(
        {
            "state": "rejected",
            "notes": "QA report confirms unusable clone; keep reports linked for audit.",
            "qa_report_refs": ["voice-qa:private-message-rejected-001"],
        }
    )
    assert_status(client.post(f"/packages/{package_id}/artifact-manifests", json={"manifest": rejected_delivery}), 403)

    fetched_after_review = assert_status(client.get(f"/packages/{package_id}"), 200)
    reviewed_manifests = {item["manifest_id"]: item for item in fetched_after_review["bundle"]["artifact_manifests"]}
    retained_review = reviewed_manifests["manifest:runtime_changes_requested_001"]["human_review"]
    assert retained_review["state"] == "changes_requested"
    assert retained_review["qa_report_refs"] == ["voice-qa:private-message-clicks-001"]
    assert retained_review["mastering_report_refs"] == ["mastering:private-message-clicks-001"]

    bad = deepcopy(bundle)
    bad["memorial_subjects"][0]["public_bio"] = "Paperclip issue 3230430e-9ed0-4be8-a1ca-c98b6672a9bf leaked"
    assert_status(client.post("/packages", json={"bundle": bad}), 400)

    print("package authoring scaffold smoke: ok")


if __name__ == "__main__":
    main()
