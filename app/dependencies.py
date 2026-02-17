from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.database.session() as session:
        yield session
