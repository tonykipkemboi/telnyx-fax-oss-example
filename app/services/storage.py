from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.services.storage_backend import StorageBackend


class UploadValidationError(ValueError):
    pass


SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}

FILENAME_EXTENSION_TO_TYPE = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass
class StoredUpload:
    storage_key: str
    mime_type: str
    page_count: int
    checksum: str
    file_size_bytes: int


def _pdf_page_count(content: bytes) -> int:
    reader = PdfReader(BytesIO(content))
    return len(reader.pages)


def _image_to_pdf_bytes(content: bytes) -> bytes:
    try:
        image = Image.open(BytesIO(content))
    except UnidentifiedImageError as exc:
        raise UploadValidationError("Unable to parse image upload") from exc

    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="PDF", resolution=200)
    return output.getvalue()


def _normalize_declared_content_type(content_type: str) -> str:
    return content_type.split(";", maxsplit=1)[0].strip().lower()


def _detect_content_type_from_magic(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _guess_content_type_from_filename(filename: str) -> str | None:
    extension = Path(filename).suffix.lower()
    return FILENAME_EXTENSION_TO_TYPE.get(extension)


def store_upload(
    *,
    content: bytes,
    content_type: str,
    original_filename: str,
    storage_backend: StorageBackend,
    max_pages_per_job: int,
) -> StoredUpload:
    if not content:
        raise UploadValidationError("Upload is empty")

    declared_content_type = _normalize_declared_content_type(content_type)
    detected_content_type = _detect_content_type_from_magic(content)
    guessed_content_type = _guess_content_type_from_filename(original_filename)

    mime_type = (
        detected_content_type
        or (declared_content_type if declared_content_type in SUPPORTED_CONTENT_TYPES else None)
        or guessed_content_type
    )

    if mime_type not in SUPPORTED_CONTENT_TYPES:
        raise UploadValidationError("Unsupported upload type. Use PDF, JPG, PNG, or WEBP")

    normalized_content = content

    if mime_type.startswith("image/"):
        normalized_content = _image_to_pdf_bytes(content)
        mime_type = "application/pdf"

    try:
        page_count = _pdf_page_count(normalized_content)
    except Exception:
        # Fallback: some clients label image data as PDF. Retry by parsing as image.
        try:
            normalized_content = _image_to_pdf_bytes(content)
            mime_type = "application/pdf"
            page_count = _pdf_page_count(normalized_content)
        except Exception as fallback_exc:
            raise UploadValidationError(
                "Upload is not a valid PDF document. Try exporting as PDF or upload JPG/PNG."
            ) from fallback_exc

    if page_count < 1:
        raise UploadValidationError("Upload must contain at least one page")

    if page_count > max_pages_per_job:
        raise UploadValidationError(f"Maximum {max_pages_per_job} pages per fax")

    checksum = hashlib.sha256(normalized_content).hexdigest()
    storage_key = f"{uuid4()}.pdf"
    storage_backend.save_pdf(storage_key=storage_key, content=normalized_content)

    return StoredUpload(
        storage_key=storage_key,
        mime_type=mime_type,
        page_count=page_count,
        checksum=checksum,
        file_size_bytes=len(normalized_content),
    )
