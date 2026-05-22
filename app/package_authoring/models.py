from __future__ import annotations

from pydantic import BaseModel, Field


class PackageCreateRequest(BaseModel):
    bundle: dict = Field(default_factory=dict)


class PackageReplaceRequest(BaseModel):
    bundle: dict


class AuthorityPreflightRequest(BaseModel):
    artifact_type: str
    requested_use: str
    input_refs: list[str] = Field(default_factory=list)
    subject_ref: str | None = None


class AuthorityPreflightResponse(BaseModel):
    allowed: bool
    authority_record_refs: list[str]
    decision: str
    reasons: list[str]


class ArtifactManifestRequest(BaseModel):
    manifest: dict
    actor: dict = Field(default_factory=dict)


class VoiceArtifactSubmitRequest(BaseModel):
    request: dict = Field(default_factory=dict)
    preflight: dict | None = None


class VoiceArtifactManifestImportRequest(BaseModel):
    manifest: dict


class VoiceArtifactMasteringReportRequest(BaseModel):
    report: dict = Field(default_factory=dict)


class LaneAPromptSessionRequest(BaseModel):
    session: dict = Field(default_factory=dict)


class LaneAPromptResponseRequest(BaseModel):
    response: dict = Field(default_factory=dict)


class LaneBArchiveIntakeRequest(BaseModel):
    manifest: dict = Field(default_factory=dict)


class IngestionReadinessRequest(BaseModel):
    lane_refs: list[str] = Field(default_factory=list)
    requested_artifact_families: list[str] = Field(default_factory=list)
