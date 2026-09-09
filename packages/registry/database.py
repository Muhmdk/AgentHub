"""PostgreSQL engine and transaction boundaries for the agent registry."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class RegistryBase(DeclarativeBase):
    """Declarative metadata root imported by Alembic."""


class Database:
    """Own the SQLAlchemy engine and explicit transaction-scoped sessions."""

    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            with session.begin():
                yield session
        finally:
            session.close()

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1")).scalar_one() == 1)

    def dispose(self) -> None:
        self.engine.dispose()
