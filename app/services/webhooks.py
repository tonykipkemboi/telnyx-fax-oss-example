import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import WebhookEvent


def register_webhook_event(
    session: Session,
    *,
    provider: str,
    external_event_id: str,
    event_type: str,
    payload: dict,
) -> bool:
    event = WebhookEvent(
        provider=provider,
        external_event_id=external_event_id,
        event_type=event_type,
        payload_json=json.dumps(payload, separators=(",", ":")),
    )
    session.add(event)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return False

    return True
