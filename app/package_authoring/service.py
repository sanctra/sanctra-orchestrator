from __future__ import annotations

from fastapi import HTTPException

from .store import PackageStore
from .validation import (
    authority_preflight,
    package_id_from_bundle,
    upsert_manifest,
    validate_bundle,
    validate_manifest_write,
)
from .ingestion import (
    create_lane_a_prompt_session,
    create_lane_b_archive_intake,
    ingestion_readiness,
    submit_lane_a_prompt_response,
)
from .voice_artifacts import (
    FakeVoiceArtifactJobClient,
    build_mastering_report,
    build_voice_job_request,
    find_voice_request,
    mark_manifest_received,
    package_voice_request_record,
    store_mastering_report,
    upsert_voice_request,
    validate_voice_manifest_import,
)


class PackageAuthoringService:
    def __init__(self, store: PackageStore | None = None) -> None:
        self.store = store or PackageStore()

    def create(self, bundle: dict) -> dict:
        validated = validate_bundle(bundle)
        package_id = package_id_from_bundle(validated)
        if self.store.exists(package_id):
            raise HTTPException(status_code=409, detail=f"package {package_id} already exists")
        self.store.write(package_id, validated)
        return self.response(package_id, validated)

    def get(self, package_id: str) -> dict:
        if not self.store.exists(package_id):
            raise HTTPException(status_code=404, detail=f"unknown package {package_id}")
        return self.response(package_id, self.store.read(package_id))

    def replace(self, package_id: str, bundle: dict) -> dict:
        if not self.store.exists(package_id):
            raise HTTPException(status_code=404, detail=f"unknown package {package_id}")
        validated = validate_bundle(bundle)
        bundle_package_id = package_id_from_bundle(validated)
        if bundle_package_id != package_id:
            raise HTTPException(status_code=409, detail="package_id mismatch")
        self.store.write(package_id, validated)
        return self.response(package_id, validated)

    def preflight(self, package_id: str, artifact_type: str, requested_use: str, subject_ref: str | None) -> dict:
        bundle = self.get(package_id)["bundle"]
        return authority_preflight(bundle, artifact_type, requested_use, subject_ref)

    def write_manifest(self, package_id: str, manifest: dict) -> dict:
        bundle = self.get(package_id)["bundle"]
        validated_manifest = validate_manifest_write(bundle, manifest)
        updated = upsert_manifest(bundle, validated_manifest)
        self.store.write(package_id, updated)
        return {
            "manifest_id": validated_manifest["manifest_id"],
            "artifact_status": validated_manifest.get("artifact_status", "planned"),
        }

    def submit_voice_artifact_request(
        self, package_id: str, request_id: str, request: dict, preflight: dict | None = None
    ) -> dict:
        bundle = self.get(package_id)["bundle"]
        request = dict(request)
        request.setdefault("package_id", package_id)
        request.setdefault("request_id", request_id)
        if request["package_id"] != package_id or request["request_id"] != request_id:
            raise HTTPException(status_code=409, detail="voice artifact request path/body mismatch")
        job_request = build_voice_job_request(bundle, request, preflight)
        submission = FakeVoiceArtifactJobClient().submit(job_request)
        record = package_voice_request_record(request, job_request, submission)
        updated = upsert_voice_request(bundle, record)
        self.store.write(package_id, updated)
        return {"request": record, "job_request": job_request}

    def get_voice_artifact_request(self, package_id: str, request_id: str) -> dict:
        bundle = self.get(package_id)["bundle"]
        return find_voice_request(bundle, request_id)

    def import_voice_artifact_manifest(self, package_id: str, request_id: str, manifest: dict) -> dict:
        bundle = self.get(package_id)["bundle"]
        validated_voice_manifest = validate_voice_manifest_import(bundle, request_id, manifest)
        validated_manifest = validate_manifest_write(bundle, validated_voice_manifest)
        updated = upsert_manifest(bundle, validated_manifest)
        updated = mark_manifest_received(updated, request_id, validated_manifest["manifest_id"])
        self.store.write(package_id, updated)
        return {
            "request_id": request_id,
            "manifest_id": validated_manifest["manifest_id"],
            "status": "manifest_received",
        }

    def write_voice_artifact_mastering_report(self, package_id: str, request_id: str, report: dict) -> dict:
        bundle = self.get(package_id)["bundle"]
        mastering_report = build_mastering_report(bundle, request_id, report)
        updated = store_mastering_report(bundle, request_id, mastering_report)
        self.store.write(package_id, updated)
        return {
            "request_id": request_id,
            "report_id": mastering_report["report_id"],
            "manifest_id": mastering_report["manifest_id"],
            "final_outcome": mastering_report["final_outcome"],
            "mastering_report_uri": mastering_report["report_uri"],
        }

    def create_lane_a_prompt_session(self, package_id: str, session: dict) -> dict:
        bundle = self.get(package_id)["bundle"]
        updated, response = create_lane_a_prompt_session(bundle, package_id, session)
        self.store.write(package_id, updated)
        return response

    def submit_lane_a_prompt_response(self, package_id: str, session_id: str, response: dict) -> dict:
        bundle = self.get(package_id)["bundle"]
        updated, normalized = submit_lane_a_prompt_response(bundle, package_id, session_id, response)
        self.store.write(package_id, updated)
        return normalized

    def create_lane_b_archive_intake(self, package_id: str, manifest: dict) -> dict:
        bundle = self.get(package_id)["bundle"]
        updated, response = create_lane_b_archive_intake(bundle, package_id, manifest)
        self.store.write(package_id, updated)
        return response

    def ingestion_readiness(self, package_id: str, lane_refs: list[str], requested_artifact_families: list[str]) -> dict:
        bundle = self.get(package_id)["bundle"]
        return ingestion_readiness(bundle, package_id, lane_refs, requested_artifact_families)

    @staticmethod
    def response(package_id: str, bundle: dict) -> dict:
        package = (bundle.get("memorial_packages") or [{}])[0]
        return {"package_id": package_id, "status": package.get("status", "draft"), "bundle": bundle}
