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

    bad = deepcopy(bundle)
    bad["memorial_subjects"][0]["public_bio"] = "Paperclip issue 3230430e-9ed0-4be8-a1ca-c98b6672a9bf leaked"
    assert_status(client.post("/packages", json={"bundle": bad}), 400)

    print("package authoring scaffold smoke: ok")


if __name__ == "__main__":
    main()
