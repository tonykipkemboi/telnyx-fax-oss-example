from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UploadResponse(BaseModel):
    document_upload_id: str
    mime_type: str
    page_count: int
    checksum: str
    file_size_bytes: int


class CreateFaxJobRequest(BaseModel):
    document_upload_id: str
    destination_fax: str = Field(min_length=5, max_length=40)
    destination_country: str = Field(default="US", min_length=2, max_length=2)
    notification_email: EmailStr | None = None


class CreateFaxJobResponse(BaseModel):
    fax_job_id: str
    status: str


class FaxTimelineEvent(BaseModel):
    at: datetime | None = None
    stage: str
    label: str
    source: str
    detail: str | None = None


class FaxJobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    provider_status: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    destination_fax: str
    page_count: int
    progress_percent: int = Field(default=0, ge=0, le=100)
    progress_label: str | None = None
    progress_stage: str | None = None
    timeline: list[FaxTimelineEvent] = Field(default_factory=list)


class WebhookAck(BaseModel):
    ok: bool
    duplicate: bool = False
    ignored: bool = False
    message: str | None = None
