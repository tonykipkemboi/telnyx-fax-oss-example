import hashlib
import hmac
import json
import time
from base64 import b64encode
from datetime import UTC, datetime
from io import BytesIO

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from PIL import Image
from pypdf import PdfWriter

from app.models import DocumentUpload, FaxJob


def make_pdf_bytes(page_count: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)

    buff = BytesIO()
    writer.write(buff)
    return buff.getvalue()


def make_jpeg_bytes() -> bytes:
    image = Image.new("RGB", (200, 120), color=(255, 255, 255))
    buff = BytesIO()
    image.save(buff, format="JPEG")
    return buff.getvalue()


def create_upload(client, page_count: int = 1):
    res = client.post(
        "/v1/uploads",
        files={"file": ("doc.pdf", make_pdf_bytes(page_count), "application/pdf")},
    )
    assert res.status_code == 200
    return res.json()


def create_job(client, upload_id: str):
    res = client.post(
        "/v1/fax/jobs",
        json={
            "document_upload_id": upload_id,
            "destination_fax": "+14155550123",
            "destination_country": "US",
            "notification_email": "user@example.com",
        },
    )
    assert res.status_code == 201
    return res.json()


def test_happy_path_upload_to_delivery(client):
    upload = create_upload(client, page_count=3)
    job = create_job(client, upload["document_upload_id"])

    status_res = client.get(f"/v1/fax/jobs/{job['fax_job_id']}")
    assert status_res.status_code == 200
    data = status_res.json()
    assert data["status"] == "delivered"
    assert data["submitted_at"] is not None
    assert data["completed_at"] is not None


def test_upload_accepts_mislabeled_image_payload(client):
    res = client.post(
        "/v1/uploads",
        files={"file": ("scan.pdf", make_jpeg_bytes(), "application/pdf")},
    )
    assert res.status_code == 200
    assert res.json()["page_count"] == 1


def test_upload_validation_rejects_unsupported_file(client):
    res = client.post(
        "/v1/uploads",
        files={"file": ("doc.txt", b"not a fax", "text/plain")},
    )
    assert res.status_code == 400


def test_cancel_sending_job(client):
    upload = create_upload(client)
    job = create_job(client, upload["document_upload_id"])

    with client.app.state.database.session() as session:
        fax_job = session.get(FaxJob, job["fax_job_id"])
        fax_job.status = "sending"
        fax_job.provider_job_id = "mock_fax_cancel_123"
        fax_job.provider_status = "queued"

    cancel_res = client.post(f"/v1/fax/jobs/{job['fax_job_id']}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "canceled"


def test_cancel_terminal_job_rejected(client):
    upload = create_upload(client)
    job = create_job(client, upload["document_upload_id"])

    with client.app.state.database.session() as session:
        fax_job = session.get(FaxJob, job["fax_job_id"])
        fax_job.status = "delivered"

    cancel_res = client.post(f"/v1/fax/jobs/{job['fax_job_id']}/cancel")
    assert cancel_res.status_code == 409


def test_telnyx_webhook_requires_signature_when_public_key_configured(client):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    client.app.state.settings.telnyx_webhook_public_key = b64encode(public_key).decode("utf-8")

    payload = {
        "data": {
            "id": "evt_telnyx_sig_required",
            "event_type": "fax.delivered",
            "payload": {"fax_id": "fax_sig_required", "status": "delivered"},
        }
    }

    response = client.post("/v1/webhooks/telnyx", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing Telnyx signature headers"


def test_telnyx_webhook_accepts_valid_signature(client):
    upload = create_upload(client)
    job = create_job(client, upload["document_upload_id"])

    with client.app.state.database.session() as session:
        fax_job = session.get(FaxJob, job["fax_job_id"])
        fax_job.status = "sending"
        fax_job.provider_job_id = "telnyx_live_job_123"

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    client.app.state.settings.telnyx_webhook_public_key = b64encode(public_key).decode("utf-8")

    payload = {
        "data": {
            "id": "evt_telnyx_valid",
            "event_type": "fax.delivered",
            "payload": {"fax_id": "telnyx_live_job_123", "status": "delivered"},
        }
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    timestamp = str(int(time.time()))
    message = f"{timestamp}|".encode() + payload_bytes
    signature = b64encode(private_key.sign(message)).decode("utf-8")

    response = client.post(
        "/v1/webhooks/telnyx",
        content=payload_bytes,
        headers={
            "content-type": "application/json",
            "telnyx-timestamp": timestamp,
            "telnyx-signature-ed25519": signature,
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    status_res = client.get(f"/v1/fax/jobs/{job['fax_job_id']}")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "delivered"


def test_telnyx_webhook_is_idempotent(client):
    upload = create_upload(client)
    job = create_job(client, upload["document_upload_id"])

    with client.app.state.database.session() as session:
        fax_job = session.get(FaxJob, job["fax_job_id"])
        fax_job.status = "sending"
        fax_job.provider_job_id = "telnyx_dup_job_123"

    payload = {
        "data": {
            "id": "evt_telnyx_duplicate_1",
            "event_type": "fax.queued",
            "payload": {"fax_id": "telnyx_dup_job_123", "status": "queued"},
        }
    }

    first = client.post("/v1/webhooks/telnyx", json=payload)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    second = client.post("/v1/webhooks/telnyx", json=payload)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True


def test_local_upload_url_requires_signature_in_production(client):
    upload = create_upload(client)

    with client.app.state.database.session() as session:
        document_upload = session.get(DocumentUpload, upload["document_upload_id"])
        storage_key = document_upload.storage_key

    settings = client.app.state.settings
    settings.environment = "production"
    settings.app_secret_key = "prod-secret-test"

    no_sig = client.get(f"/v1/uploads/public/{storage_key}")
    assert no_sig.status_code == 403

    exp = int(time.time()) + 300
    signature = hmac.new(
        settings.app_secret_key.encode("utf-8"),
        f"{storage_key}|{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()

    signed = client.get(f"/v1/uploads/public/{storage_key}?exp={exp}&sig={signature}")
    assert signed.status_code == 200


def test_fax_job_status_includes_event_chain_and_progress(client):
    upload = create_upload(client)
    job = create_job(client, upload["document_upload_id"])

    with client.app.state.database.session() as session:
        fax_job = session.get(FaxJob, job["fax_job_id"])
        fax_job.status = "sending"
        fax_job.submitted_at = datetime.now(UTC)
        fax_job.provider_job_id = "progress_job_123"
        fax_job.provider_status = "queued"

    webhook_payload = {
        "data": {
            "id": "evt_telnyx_progress_queued",
            "event_type": "fax.queued",
            "payload": {"fax_id": "progress_job_123", "status": "queued"},
        }
    }
    webhook_res = client.post("/v1/webhooks/telnyx", json=webhook_payload)
    assert webhook_res.status_code == 200

    status_res = client.get(f"/v1/fax/jobs/{job['fax_job_id']}")
    assert status_res.status_code == 200
    data = status_res.json()

    assert data["status"] == "sending"
    assert data["progress_percent"] >= 45
    assert data["progress_label"]
    assert isinstance(data["timeline"], list)
    assert any(event["source"] == "telnyx" for event in data["timeline"])
    assert any(event["stage"] == "fax_queued" for event in data["timeline"])
