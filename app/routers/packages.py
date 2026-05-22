from __future__ import annotations

from fastapi import APIRouter

from app.package_authoring.models import (
    ArtifactManifestRequest,
    AuthorityPreflightRequest,
    AuthorityPreflightResponse,
    IngestionReadinessRequest,
    LaneAPromptResponseRequest,
    LaneAPromptSessionRequest,
    LaneBArchiveIntakeRequest,
    PackageCreateRequest,
    PackageReplaceRequest,
    VoiceArtifactManifestImportRequest,
    VoiceArtifactMasteringReportRequest,
    VoiceArtifactSubmitRequest,
)
from app.package_authoring.service import PackageAuthoringService

router = APIRouter()


def service() -> PackageAuthoringService:
    return PackageAuthoringService()


@router.post("/packages")
def create_package(request: PackageCreateRequest) -> dict:
    return service().create(request.bundle)


@router.get("/packages/{package_id}")
def get_package(package_id: str) -> dict:
    return service().get(package_id)


@router.put("/packages/{package_id}")
def replace_package(package_id: str, request: PackageReplaceRequest) -> dict:
    return service().replace(package_id, request.bundle)


@router.post("/packages/{package_id}/authority-preflight", response_model=AuthorityPreflightResponse)
def package_authority_preflight(package_id: str, request: AuthorityPreflightRequest) -> dict:
    return service().preflight(
        package_id,
        artifact_type=request.artifact_type,
        requested_use=request.requested_use,
        subject_ref=request.subject_ref,
    )


@router.post("/packages/{package_id}/artifact-manifests")
def write_artifact_manifest(package_id: str, request: ArtifactManifestRequest) -> dict:
    return service().write_manifest(package_id, request.manifest, request.actor)


@router.post("/packages/{package_id}/voice-artifact-requests/{request_id}/submit")
def submit_voice_artifact_request(
    package_id: str, request_id: str, request: VoiceArtifactSubmitRequest
) -> dict:
    return service().submit_voice_artifact_request(
        package_id, request_id, request.request, request.preflight
    )


@router.get("/packages/{package_id}/voice-artifact-requests/{request_id}")
def get_voice_artifact_request(package_id: str, request_id: str) -> dict:
    return service().get_voice_artifact_request(package_id, request_id)


@router.post("/packages/{package_id}/voice-artifact-requests/{request_id}/manifest")
def import_voice_artifact_manifest(
    package_id: str, request_id: str, request: VoiceArtifactManifestImportRequest
) -> dict:
    return service().import_voice_artifact_manifest(package_id, request_id, request.manifest)


@router.post("/packages/{package_id}/voice-artifact-requests/{request_id}/mastering-report")
def write_voice_artifact_mastering_report(
    package_id: str, request_id: str, request: VoiceArtifactMasteringReportRequest
) -> dict:
    return service().write_voice_artifact_mastering_report(package_id, request_id, request.report)


@router.post("/packages/{package_id}/lane-a/prompt-sessions")
def create_lane_a_prompt_session(package_id: str, request: LaneAPromptSessionRequest) -> dict:
    return service().create_lane_a_prompt_session(package_id, request.session)


@router.post("/packages/{package_id}/lane-a/prompt-sessions/{session_id}/responses")
def submit_lane_a_prompt_response(
    package_id: str, session_id: str, request: LaneAPromptResponseRequest
) -> dict:
    return service().submit_lane_a_prompt_response(package_id, session_id, request.response)


@router.post("/packages/{package_id}/lane-b/archive-intakes")
def create_lane_b_archive_intake(package_id: str, request: LaneBArchiveIntakeRequest) -> dict:
    return service().create_lane_b_archive_intake(package_id, request.manifest)


@router.post("/packages/{package_id}/ingestion-readiness")
def package_ingestion_readiness(package_id: str, request: IngestionReadinessRequest) -> dict:
    return service().ingestion_readiness(
        package_id,
        lane_refs=request.lane_refs,
        requested_artifact_families=request.requested_artifact_families,
    )
