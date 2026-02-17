from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import Base


class Database:
    def __init__(self, settings: Settings):
        database_url = settings.database_url
        if database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            self.engine = create_engine(
                database_url,
                connect_args=connect_args,
                pool_pre_ping=True,
            )
        else:
            self.engine = create_engine(
                database_url,
                pool_pre_ping=True,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout_seconds,
                pool_recycle=settings.db_pool_recycle_seconds,
            )

        self.session_factory = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def init_db(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def session(self):
        session: Session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
