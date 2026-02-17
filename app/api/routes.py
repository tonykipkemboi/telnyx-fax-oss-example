from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_session, get_settings
from app.models import DocumentUpload, FaxJob
from app.schemas import (
    CreateFaxJobRequest,
    CreateFaxJobResponse,
    FaxJobStatusResponse,
    UploadResponse,
    WebhookAck,
)
from app.services.fax_provider import FaxProviderError
from app.services.orchestrator import apply_telnyx_status, dispatch_fax_job
from app.services.phone import PhoneValidationError, normalize_us_fax_number
from app.services.retention import run_retention_cleanup
from app.services.status_view import build_fax_job_status_response
from app.services.storage import UploadValidationError, store_upload
from app.services.webhooks import register_webhook_event

router = APIRouter(prefix="/v1", tags=["api"])

CANCELABLE_JOB_STATUSES = {"queued_for_send", "retry_queued", "sending"}
TERMINAL_JOB_STATUSES = {"delivered", "failed", "canceled", "cancelled"}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _assert_country_supported(country_code: str, settings: Settings) -> None:
    country = country_code.upper()
    allowed = {c.strip().upper() for c in settings.supported_country_codes.split(",")}
    if country not in allowed:
        raise HTTPException(status_code=400, detail=f"Destination country {country} is not supported")


def _verify_local_upload_signature(*, storage_key: str, exp: str | None, sig: str | None, secret: str) -> bool:
    if not exp or not sig:
        return False

    try:
        expires_at = int(exp)
    except ValueError:
        return False

    now = int(time.time())
    if now > expires_at:
        return False

    payload = f"{storage_key}|{expires_at}".encode()
    expected_sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_sig, sig)


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.post("/uploads", response_model=UploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    ip_address = _client_ip(request)

    limiter = request.app.state.rate_limiter
    if not limiter.allow(f"upload:{ip_address}", settings.rate_limit_ip_per_hour, 3600):
        raise HTTPException(status_code=429, detail="Upload rate limit exceeded")

    try:
        content = await file.read()
        if len(content) > settings.max_upload_size_bytes:
            raise UploadValidationError(
                f"Upload exceeds {settings.max_upload_size_mb} MB limit. Compress and try again."
            )
        stored = store_upload(
            content=content,
            content_type=file.content_type or "application/octet-stream",
            original_filename=file.filename or "upload",
            storage_backend=request.app.state.storage_backend,
            max_pages_per_job=settings.max_pages_per_job,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload = DocumentUpload(
        storage_key=stored.storage_key,
        mime_type=stored.mime_type,
        original_filename=file.filename or "upload",
        page_count=stored.page_count,
        checksum=stored.checksum,
        file_size_bytes=stored.file_size_bytes,
    )
    session.add(upload)
    session.flush()

    return UploadResponse(
        document_upload_id=upload.id,
        mime_type=upload.mime_type,
        page_count=upload.page_count,
        checksum=upload.checksum,
        file_size_bytes=upload.file_size_bytes,
    )


@router.get("/uploads/public/{storage_key}")
def get_public_upload(
    request: Request,
    storage_key: str,
    exp: str | None = None,
    sig: str | None = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    storage_backend = request.app.state.storage_backend

    upload = session.execute(
        select(DocumentUpload).where(DocumentUpload.storage_key == storage_key)
    ).scalar_one_or_none()
    if not upload or upload.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Upload not found")

    path = storage_backend.local_path(storage_key=storage_key)
    if path is not None:
        should_verify = settings.is_production or bool(exp or sig)
        if should_verify and not _verify_local_upload_signature(
            storage_key=storage_key,
            exp=exp,
            sig=sig,
            secret=settings.app_secret_key,
        ):
            raise HTTPException(status_code=403, detail="Invalid or expired upload URL")

        if not path.exists():
            raise HTTPException(status_code=404, detail="Upload not found")
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    if not storage_backend.exists(storage_key=storage_key):
        raise HTTPException(status_code=404, detail="Upload not found")

    return RedirectResponse(
        url=storage_backend.public_url(
            storage_key=storage_key,
            ttl_seconds=settings.storage_presign_ttl_seconds,
        )
    )


def _dispatch_fax_job(*, request: Request, session: Session, fax_job: FaxJob) -> None:
    if fax_job.status in TERMINAL_JOB_STATUSES:
        return

    upload = session.get(DocumentUpload, fax_job.document_upload_id)
    if not upload:
        fax_job.status = "failed"
        fax_job.failure_reason = "Document upload missing"
        return

    storage_backend = request.app.state.storage_backend
    if not storage_backend.exists(storage_key=upload.storage_key):
        fax_job.status = "failed"
        fax_job.failure_reason = "Document file missing"
        return

    media_url = storage_backend.public_url(
        storage_key=upload.storage_key,
        ttl_seconds=request.app.state.settings.storage_presign_ttl_seconds,
    )

    dispatch_fax_job(
        session=session,
        settings=request.app.state.settings,
        fax_provider=request.app.state.fax_provider,
        fax_job=fax_job,
        media_url=media_url,
    )


@router.post("/fax/jobs", response_model=CreateFaxJobResponse, status_code=status.HTTP_201_CREATED)
def create_fax_job(
    payload: CreateFaxJobRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CreateFaxJobResponse:
    _assert_country_supported(payload.destination_country, settings)

    try:
        normalized_fax = normalize_us_fax_number(payload.destination_fax)
    except PhoneValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ip_address = _client_ip(request)
    limiter = request.app.state.rate_limiter
    if not limiter.allow(f"faxjob:ip:{ip_address}", settings.rate_limit_ip_per_hour, 3600):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this IP")

    upload = session.get(DocumentUpload, payload.document_upload_id)
    if not upload or upload.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document upload not found")

    fax_job = FaxJob(
        document_upload_id=upload.id,
        destination_country=payload.destination_country.upper(),
        destination_fax=normalized_fax,
        notification_email=payload.notification_email.lower() if payload.notification_email else None,
        status="queued_for_send",
        ip_address=ip_address,
    )

    session.add(fax_job)
    session.flush()

    _dispatch_fax_job(request=request, session=session, fax_job=fax_job)

    return CreateFaxJobResponse(fax_job_id=fax_job.id, status=fax_job.status)


def _decode_telnyx_public_key(value: str) -> bytes:
    candidate = value.strip()

    try:
        decoded = base64.b64decode(candidate, validate=True)
        if len(decoded) == 32:
            return decoded
    except (ValueError, binascii.Error):
        pass

    hex_candidate = candidate.lower().removeprefix("0x")
    try:
        decoded_hex = bytes.fromhex(hex_candidate)
    except ValueError as exc:
        raise ValueError("Unsupported Telnyx public key format") from exc

    if len(decoded_hex) != 32:
        raise ValueError("Invalid Telnyx public key length")

    return decoded_hex


def _verify_telnyx_webhook_signature(
    *,
    raw_body: bytes,
    provided_signature: str,
    provided_timestamp: str,
    public_key: str,
    tolerance_seconds: int,
) -> bool:
    try:
        timestamp_int = int(provided_timestamp)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - timestamp_int) > tolerance_seconds:
        return False

    try:
        signature_bytes = base64.b64decode(provided_signature, validate=True)
        public_key_bytes = _decode_telnyx_public_key(public_key)
    except (ValueError, binascii.Error):
        return False

    message = f"{provided_timestamp}|".encode() + raw_body

    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature_bytes, message)
    except InvalidSignature:
        return False

    return True


@router.post("/webhooks/telnyx", response_model=WebhookAck)
async def telnyx_webhook(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    telnyx_signature_ed25519: str | None = Header(default=None),
    telnyx_timestamp: str | None = Header(default=None),
) -> WebhookAck:
    raw_body = await request.body()

    if settings.telnyx_webhook_public_key:
        if not telnyx_signature_ed25519 or not telnyx_timestamp:
            raise HTTPException(status_code=400, detail="Missing Telnyx signature headers")
        if not _verify_telnyx_webhook_signature(
            raw_body=raw_body,
            provided_signature=telnyx_signature_ed25519,
            provided_timestamp=telnyx_timestamp,
            public_key=settings.telnyx_webhook_public_key,
            tolerance_seconds=settings.webhook_timestamp_tolerance_seconds,
        ):
            raise HTTPException(status_code=400, detail="Invalid Telnyx webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Telnyx webhook payload: {exc}") from exc

    data = payload.get("data", {})
    event_id = str(data.get("id") or payload.get("id") or "")
    event_type = str(data.get("event_type") or payload.get("event_type") or "unknown")

    if not event_id:
        raise HTTPException(status_code=400, detail="Missing Telnyx event id")

    first_seen = register_webhook_event(
        session,
        provider="telnyx",
        external_event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    if not first_seen:
        return WebhookAck(ok=True, duplicate=True, message="Duplicate Telnyx event ignored")

    telnyx_payload = data.get("payload", payload.get("payload", {}))
    provider_job_id = str(
        telnyx_payload.get("fax_id")
        or telnyx_payload.get("id")
        or telnyx_payload.get("fax", {}).get("id")
        or ""
    )

    provider_status = str(telnyx_payload.get("status") or event_type).lower()
    if provider_status.startswith("fax."):
        provider_status = provider_status.split(".", 1)[1]

    if not provider_job_id:
        return WebhookAck(ok=True, ignored=True, message="No fax id in Telnyx webhook")

    fax_job = session.execute(select(FaxJob).where(FaxJob.provider_job_id == provider_job_id)).scalar_one_or_none()
    if not fax_job:
        return WebhookAck(ok=True, ignored=True, message="Fax job not found for provider id")

    apply_telnyx_status(
        fax_job,
        provider_status=provider_status,
        failure_reason=telnyx_payload.get("failure_reason"),
    )

    return WebhookAck(ok=True)


@router.get("/fax/jobs/{fax_job_id}", response_model=FaxJobStatusResponse)
def get_fax_job_status(
    fax_job_id: str,
    session: Session = Depends(get_session),
) -> FaxJobStatusResponse:
    fax_job = session.get(FaxJob, fax_job_id)
    if not fax_job:
        raise HTTPException(status_code=404, detail="Fax job not found")

    return build_fax_job_status_response(session, fax_job)


@router.post("/fax/jobs/{fax_job_id}/cancel", response_model=FaxJobStatusResponse)
def cancel_fax_job(
    fax_job_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> FaxJobStatusResponse:
    fax_job = session.get(FaxJob, fax_job_id)
    if not fax_job:
        raise HTTPException(status_code=404, detail="Fax job not found")

    if fax_job.status in TERMINAL_JOB_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot cancel in status '{fax_job.status}'")

    if fax_job.status not in CANCELABLE_JOB_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cancel is not allowed in status '{fax_job.status}'")

    if fax_job.status == "sending" and fax_job.provider_job_id:
        fax_provider = request.app.state.fax_provider
        try:
            provider_cancel_status = fax_provider.cancel_fax(provider_job_id=fax_job.provider_job_id)
        except FaxProviderError as exc:
            raise HTTPException(status_code=502, detail=f"Unable to cancel with provider: {exc}") from exc
        fax_job.provider_status = provider_cancel_status
    else:
        fax_job.provider_status = fax_job.provider_status or "canceled"

    fax_job.status = "canceled"
    fax_job.completed_at = datetime.now(UTC)
    fax_job.failure_reason = "Canceled by user"

    return build_fax_job_status_response(session, fax_job)


@router.post("/internal/tasks/retention-run")
def run_retention(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    x_internal_token: str | None = Header(default=None),
) -> dict[str, int]:
    if settings.internal_admin_token and x_internal_token != settings.internal_admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return run_retention_cleanup(
        session=session,
        settings=settings,
        storage_backend=request.app.state.storage_backend,
    )
