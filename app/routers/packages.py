from __future__ import annotations

from fastapi import APIRouter

from app.package_authoring.models import (
    ArtifactManifestRequest,
    AuthorityPreflightRequest,
    AuthorityPreflightResponse,
    PackageCreateRequest,
    PackageReplaceRequest,
    VoiceArtifactManifestImportRequest,
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
    return service().write_manifest(package_id, request.manifest)


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
