"""PostgreSQL engine and transaction boundaries for the agent registry."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class RegistryBase(DeclarativeBase):
    """Declarative metadata root imported by Alembic."""


class AccessTokenSource(Protocol):
    """Minimal credential boundary used for short-lived PostgreSQL passwords."""

    def get_token(self, scope: str) -> str: ...


class Database:
    """Own the SQLAlchemy engine and explicit transaction-scoped sessions."""

    def __init__(
        self,
        url: str,
        *,
        token_provider: AccessTokenSource | None = None,
        token_scope: str = "https://ossrdbms-aad.database.windows.net/.default",
    ) -> None:
        self._token_provider = token_provider
        self._token_scope = token_scope
        self.engine: Engine = create_engine(url, pool_pre_ping=True)
        if token_provider is not None:
            event.listen(self.engine, "do_connect", self._inject_access_token)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _inject_access_token(
        self,
        _dialect: Any,
        _connection_record: Any,
        _connection_args: list[Any],
        connection_parameters: dict[str, Any],
    ) -> None:
        if self._token_provider is None:  # pragma: no cover - listener is conditional
            return
        connection_parameters["password"] = self._token_provider.get_token(self._token_scope)

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
