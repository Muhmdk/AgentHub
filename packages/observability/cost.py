"""Thread-safe model cost ledger across operational ownership dimensions."""

from collections import defaultdict, deque
from datetime import UTC, datetime
from threading import Lock

from packages.contracts.observability import CostAttributionReport, CostAttributionRow


class CostLedger:
    """Keep bounded usage entries and aggregate exact five-dimensional ownership."""

    def __init__(self, capacity: int = 50_000) -> None:
        if capacity < 1:
            raise ValueError("Cost ledger capacity must be positive")
        self._entries: deque[tuple[datetime, CostAttributionRow]] = deque(maxlen=capacity)
        self._lock = Lock()

    def record(
        self,
        *,
        agent_name: str,
        agent_version: str,
        model: str,
        environment: str,
        team: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        occurred_at: datetime | None = None,
    ) -> None:
        row = CostAttributionRow(
            agent_name=agent_name,
            agent_version=agent_version,
            model=model,
            environment=environment,
            team=team,
            invocation_count=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        with self._lock:
            self._entries.append((occurred_at or datetime.now(UTC), row))

    def report(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        team: str | None = None,
        environment: str | None = None,
    ) -> CostAttributionReport:
        if window_end < window_start:
            raise ValueError("Cost report window end must not precede its start")
        with self._lock:
            entries = list(self._entries)
        selected = [
            row
            for occurred_at, row in entries
            if window_start <= occurred_at <= window_end
            and (team is None or row.team == team)
            and (environment is None or row.environment == environment)
        ]
        groups: dict[tuple[str, str, str, str, str], list[CostAttributionRow]] = defaultdict(list)
        for row in selected:
            groups[
                (row.agent_name, row.agent_version, row.model, row.environment, row.team)
            ].append(row)
        rows = [
            CostAttributionRow(
                agent_name=key[0],
                agent_version=key[1],
                model=key[2],
                environment=key[3],
                team=key[4],
                invocation_count=len(values),
                input_tokens=sum(value.input_tokens for value in values),
                output_tokens=sum(value.output_tokens for value in values),
                cost_usd=sum(value.cost_usd for value in values),
            )
            for key, values in sorted(groups.items())
        ]
        return CostAttributionReport(
            window_start=window_start,
            window_end=window_end,
            generated_at=datetime.now(UTC),
            rows=rows,
            invocation_count=sum(row.invocation_count for row in rows),
            input_tokens=sum(row.input_tokens for row in rows),
            output_tokens=sum(row.output_tokens for row in rows),
            cost_usd=sum(row.cost_usd for row in rows),
        )
