import json

from sqlalchemy.orm import Session

from app.models import AnalyticsEvent


def track_event(
    session: Session,
    event_name: str,
    *,
    entity_id: str | None = None,
    session_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    payload = json.dumps(metadata or {}, separators=(",", ":"))
    event = AnalyticsEvent(
        event_name=event_name,
        entity_id=entity_id,
        session_id=session_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=payload,
    )
    session.add(event)
