"""Concurrency-safe per-agent/model runtime budget accounting."""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from uuid import UUID, uuid4


class RateLimitExceeded(RuntimeError):
    """The bounded request window has no remaining capacity."""


class BudgetExceeded(RuntimeError):
    """A token or cost reservation would exceed its configured window."""


@dataclass(frozen=True)
class BudgetKey:
    """Stable attribution dimensions for one model budget."""

    agent_name: str
    agent_version: str
    provider: str
    model: str


@dataclass(frozen=True)
class BudgetLimits:
    """Rate, token, and cost ceilings for rolling windows."""

    requests_per_minute: int = 120
    tokens_per_minute: int = 100_000
    cost_per_hour_usd: float = 10.0

    def __post_init__(self) -> None:
        if self.requests_per_minute < 1 or self.tokens_per_minute < 1 or self.cost_per_hour_usd < 0:
            raise ValueError("Model budget limits must be positive")


@dataclass(frozen=True)
class BudgetLease:
    """Opaque reservation completed or released after provider execution."""

    lease_id: UUID
    key: BudgetKey


@dataclass(frozen=True)
class _Reservation:
    occurred_at: float
    tokens: int
    cost_usd: float


class BudgetManager:
    """Reserve rolling-window capacity atomically across concurrent requests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._requests: dict[BudgetKey, deque[float]] = defaultdict(deque)
        self._tokens: dict[BudgetKey, deque[tuple[float, int]]] = defaultdict(deque)
        self._costs: dict[BudgetKey, deque[tuple[float, float]]] = defaultdict(deque)
        self._reservations: dict[UUID, tuple[BudgetKey, _Reservation]] = {}

    def reserve(
        self,
        key: BudgetKey,
        limits: BudgetLimits,
        *,
        tokens: int,
        cost_usd: float,
    ) -> BudgetLease:
        """Atomically reserve worst-case capacity before a provider call."""
        if tokens < 0 or cost_usd < 0:
            raise ValueError("Budget reservations cannot be negative")
        now = self._clock()
        with self._lock:
            self._prune(key, now)
            requests = self._requests[key]
            if len(requests) >= limits.requests_per_minute:
                raise RateLimitExceeded("Model rate limit exceeded")
            reserved = [
                reservation
                for reserved_key, reservation in self._reservations.values()
                if reserved_key == key
            ]
            token_total = sum(value for _, value in self._tokens[key]) + sum(
                reservation.tokens for reservation in reserved if reservation.occurred_at > now - 60
            )
            if token_total + tokens > limits.tokens_per_minute:
                raise BudgetExceeded("Model token budget exceeded")
            cost_total = sum(value for _, value in self._costs[key]) + sum(
                reservation.cost_usd
                for reservation in reserved
                if reservation.occurred_at > now - 3600
            )
            if cost_total + cost_usd > limits.cost_per_hour_usd:
                raise BudgetExceeded("Model cost budget exceeded")
            lease = BudgetLease(lease_id=uuid4(), key=key)
            requests.append(now)
            self._reservations[lease.lease_id] = (
                key,
                _Reservation(now, tokens, cost_usd),
            )
            return lease

    def complete(self, lease: BudgetLease, *, tokens: int, cost_usd: float) -> None:
        """Replace a reservation with provider-reported actual usage."""
        if tokens < 0 or cost_usd < 0:
            raise ValueError("Completed budget usage cannot be negative")
        now = self._clock()
        with self._lock:
            reserved = self._reservations.pop(lease.lease_id, None)
            if reserved is None or reserved[0] != lease.key:
                return
            self._tokens[lease.key].append((now, tokens))
            self._costs[lease.key].append((now, cost_usd))
            self._prune(lease.key, now)

    def release(self, lease: BudgetLease) -> None:
        """Release token/cost capacity after an unsuccessful provider call."""
        with self._lock:
            reserved = self._reservations.get(lease.lease_id)
            if reserved is not None and reserved[0] == lease.key:
                del self._reservations[lease.lease_id]

    def _prune(self, key: BudgetKey, now: float) -> None:
        requests = self._requests[key]
        while requests and requests[0] <= now - 60:
            requests.popleft()
        tokens = self._tokens[key]
        while tokens and tokens[0][0] <= now - 60:
            tokens.popleft()
        costs = self._costs[key]
        while costs and costs[0][0] <= now - 3600:
            costs.popleft()
