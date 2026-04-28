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

    bad = deepcopy(bundle)
    bad["memorial_subjects"][0]["public_bio"] = "Paperclip issue 3230430e-9ed0-4be8-a1ca-c98b6672a9bf leaked"
    assert_status(client.post("/packages", json={"bundle": bad}), 400)

    print("package authoring scaffold smoke: ok")


if __name__ == "__main__":
    main()
