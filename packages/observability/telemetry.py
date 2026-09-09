"""Failure-isolated tracing, metrics, context propagation, and local observations."""

import logging
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import time

from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Meter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue

from packages.observability.conventions import Attribute
from packages.observability.privacy import AttributeMapping, metric_attributes, span_attributes

logger = logging.getLogger("agenthub.observability")


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    service_name: str
    service_version: str
    environment: str
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:4318"
    export_interval_ms: int = 5000
    max_queue_size: int = 256


@dataclass(frozen=True, slots=True)
class Observation:
    occurred_at: float
    signal: str
    value: float
    attributes: Mapping[str, AttributeValue]


class ObservationStore:
    """Bounded process-local observations used by SLO previews and tests."""

    def __init__(self, capacity: int = 5000) -> None:
        self._events: deque[Observation] = deque(maxlen=capacity)
        self._lock = Lock()

    def record(self, signal: str, value: float, attributes: Mapping[str, AttributeValue]) -> None:
        observation = Observation(time(), signal, value, dict(attributes))
        with self._lock:
            self._events.append(observation)

    def snapshot(self, *, since: float = 0, agent_name: str | None = None) -> list[Observation]:
        with self._lock:
            events = list(self._events)
        return [
            event
            for event in events
            if event.occurred_at >= since
            and (
                agent_name is None or event.attributes.get(Attribute.AGENT_NAME.value) == agent_name
            )
        ]


class Telemetry:
    """One explicitly owned provider with bounded exporters and safe attributes."""

    def __init__(
        self,
        config: TelemetryConfig,
        *,
        span_exporter: SpanExporter | None = None,
        metric_reader: MetricReader | None = None,
        observations: ObservationStore | None = None,
    ) -> None:
        self.config = config
        self.observations = observations or ObservationStore()
        self._trace_lock = Lock()
        self._last_trace_ids: dict[str, str] = {}
        resource = Resource.create(
            {
                Attribute.SERVICE_NAME.value: config.service_name,
                Attribute.SERVICE_VERSION.value: config.service_version,
                Attribute.DEPLOYMENT_ENVIRONMENT.value: config.environment,
            }
        )
        self._tracer_provider: TracerProvider | None = None
        self._meter_provider: MeterProvider | None = None
        if config.enabled or span_exporter is not None or metric_reader is not None:
            tracer_provider = TracerProvider(resource=resource)
            exporter = span_exporter or OTLPSpanExporter(
                endpoint=f"{config.endpoint.rstrip('/')}/v1/traces",
                timeout=0.5,
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    max_queue_size=config.max_queue_size,
                    max_export_batch_size=min(64, config.max_queue_size),
                    schedule_delay_millis=200,
                    export_timeout_millis=500,
                )
            )
            reader = metric_reader or PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=f"{config.endpoint.rstrip('/')}/v1/metrics",
                    timeout=0.5,
                ),
                export_interval_millis=config.export_interval_ms,
                export_timeout_millis=500,
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
            self._tracer_provider = tracer_provider
            self._meter_provider = meter_provider
            self.tracer = tracer_provider.get_tracer("agenthub", config.service_version)
            self.meter = meter_provider.get_meter("agenthub", config.service_version)
        else:
            self.tracer = trace.NoOpTracerProvider().get_tracer("agenthub")
            self.meter = metrics.NoOpMeterProvider().get_meter("agenthub")
        self._create_instruments(self.meter)

    def _create_instruments(self, meter: Meter) -> None:
        self.http_requests = meter.create_counter("agenthub.http.requests", unit="{request}")
        self.http_duration = meter.create_histogram("agenthub.http.duration", unit="ms")
        self.agent_requests = meter.create_counter("agenthub.agent.requests", unit="{request}")
        self.agent_errors = meter.create_counter("agenthub.agent.errors", unit="{error}")
        self.agent_duration = meter.create_histogram("agenthub.agent.duration", unit="ms")
        self.tool_calls = meter.create_counter("agenthub.tool.calls", unit="{call}")
        self.tool_success = meter.create_counter("agenthub.tool.success", unit="{call}")
        self.tool_duration = meter.create_histogram("agenthub.tool.duration", unit="ms")
        self.retrieval_duration = meter.create_histogram("agenthub.retrieval.duration", unit="ms")
        self.model_tokens = meter.create_counter("agenthub.model.tokens", unit="{token}")
        self.model_cost = meter.create_counter("agenthub.model.cost", unit="USD")
        self.evaluation_score = meter.create_histogram("agenthub.evaluation.score", unit="1")
        self.evaluation_gates = meter.create_counter("agenthub.evaluation.gates", unit="{gate}")
        self.policy_denials = meter.create_counter("agenthub.policy.denials", unit="{denial}")

    @contextmanager
    def span(
        self,
        name: str,
        attributes: AttributeMapping | None = None,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        parent: Context | None = None,
    ) -> Iterator[Span]:
        """Start a safe span and never attach exception messages automatically."""
        with self.tracer.start_as_current_span(
            name,
            context=parent,
            kind=kind,
            attributes=span_attributes(attributes or {}),
            record_exception=False,
            set_status_on_exception=False,
        ) as current:
            try:
                yield current
            except BaseException as exc:
                current.set_attribute(Attribute.ERROR_TYPE.value, type(exc).__name__)
                current.set_status(Status(StatusCode.ERROR))
                raise

    @staticmethod
    def extract(headers: Mapping[str, str]) -> Context:
        return extract(headers)

    @staticmethod
    def inject(carrier: dict[str, str]) -> None:
        inject(carrier)

    @staticmethod
    def trace_id() -> str | None:
        context = trace.get_current_span().get_span_context()
        return f"{context.trace_id:032x}" if context.is_valid else None

    def record_http(self, attributes: AttributeMapping, duration_ms: float) -> None:
        labels = metric_attributes(attributes)
        self.http_requests.add(1, labels)
        self.http_duration.record(duration_ms, labels)
        self.observations.record("http.request", 1, labels)
        self.observations.record("http.duration_ms", duration_ms, labels)

    def record_agent(
        self,
        attributes: AttributeMapping,
        duration_ms: float,
        *,
        success: bool,
    ) -> None:
        labels = metric_attributes(attributes)
        agent_name = labels.get(Attribute.AGENT_NAME.value)
        trace_id = self.trace_id()
        if isinstance(agent_name, str) and trace_id is not None:
            self.remember_trace(agent_name, trace_id)
        self.agent_requests.add(1, labels)
        self.agent_duration.record(duration_ms, labels)
        self.agent_errors.add(int(not success), labels)
        self.observations.record("agent.request", 1, labels)
        self.observations.record("agent.success", float(success), labels)
        self.observations.record("agent.duration_ms", duration_ms, labels)

    def record_tool(
        self,
        attributes: AttributeMapping,
        duration_ms: float,
        *,
        success: bool,
    ) -> None:
        labels = metric_attributes(attributes)
        self.tool_calls.add(1, labels)
        self.tool_duration.record(duration_ms, labels)
        self.tool_success.add(int(success), labels)
        self.observations.record("tool.success", float(success), labels)
        self.observations.record("tool.duration_ms", duration_ms, labels)

    def record_retrieval(self, attributes: AttributeMapping, duration_ms: float) -> None:
        labels = metric_attributes(attributes)
        self.retrieval_duration.record(duration_ms, labels)
        self.observations.record("retrieval.duration_ms", duration_ms, labels)

    def record_model(
        self,
        attributes: AttributeMapping,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        labels = metric_attributes(attributes)
        self.model_tokens.add(
            input_tokens,
            {**labels, Attribute.TOKEN_TYPE.value: "input"},
        )
        self.model_tokens.add(
            output_tokens,
            {**labels, Attribute.TOKEN_TYPE.value: "output"},
        )
        self.model_cost.add(cost_usd, labels)
        self.observations.record("model.tokens", input_tokens + output_tokens, labels)
        self.observations.record("model.cost_usd", cost_usd, labels)

    def record_evaluation(
        self,
        attributes: AttributeMapping,
        metrics_by_name: Mapping[str, float],
        *,
        passed: bool,
    ) -> None:
        labels = metric_attributes(attributes)
        for name, value in metrics_by_name.items():
            metric_labels = {**labels, Attribute.EVALUATION_METRIC.value: name}
            self.evaluation_score.record(value, metric_labels)
            self.observations.record("evaluation.score", value, metric_labels)
        gate_labels = {**labels, Attribute.EVALUATION_GATE_PASSED.value: passed}
        self.evaluation_gates.add(1, gate_labels)
        self.observations.record("evaluation.gate", float(passed), gate_labels)

    def record_policy_denial(self, attributes: AttributeMapping) -> None:
        labels = metric_attributes(attributes)
        self.policy_denials.add(1, labels)
        self.observations.record("policy.denial", 1, labels)

    def remember_trace(self, agent_name: str, trace_id: str) -> None:
        """Remember one safe trace link per bounded agent dimension."""
        safe_name = metric_attributes({Attribute.AGENT_NAME: agent_name}).get(
            Attribute.AGENT_NAME.value
        )
        if safe_name in {None, "unknown"} or len(trace_id) != 32:
            return
        try:
            int(trace_id, 16)
        except ValueError:
            return
        with self._trace_lock:
            if len(self._last_trace_ids) >= 128 and safe_name not in self._last_trace_ids:
                oldest = next(iter(self._last_trace_ids))
                del self._last_trace_ids[oldest]
            self._last_trace_ids[str(safe_name)] = trace_id.lower()

    def last_trace_id(self, agent_name: str) -> str | None:
        with self._trace_lock:
            return self._last_trace_ids.get(agent_name)

    def shutdown(self) -> None:
        """Flush within SDK-configured deadlines; exporter failures remain non-fatal."""
        try:
            if self._meter_provider is not None:
                self._meter_provider.shutdown(timeout_millis=1000)
            if self._tracer_provider is not None:
                self._tracer_provider.shutdown()
        except Exception:
            logger.warning("telemetry_shutdown_failed", extra={"occurred_at": datetime.now(UTC)})

    def force_flush(self, timeout_millis: int = 1000) -> bool:
        """Flush providers for tests and local smoke checks without blocking indefinitely."""
        metrics_flushed = self._meter_provider is None or self._meter_provider.force_flush(
            timeout_millis=timeout_millis
        )
        traces_flushed = self._tracer_provider is None or self._tracer_provider.force_flush(
            timeout_millis=timeout_millis
        )
        return bool(metrics_flushed and traces_flushed)


_NOOP = Telemetry(TelemetryConfig("agenthub", "0", "test"))


def noop_telemetry() -> Telemetry:
    return _NOOP
