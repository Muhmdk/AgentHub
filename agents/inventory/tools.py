"""Typed, read-only retail tools used by the Inventory Agent."""

from datetime import date
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from agents.inventory.data import (
    InventoryRecord,
    Promotion,
    RetailData,
    SalesHistory,
    WeatherForecast,
    overlapping,
)
from packages.contracts.runtime import (
    Citation,
    JsonValue,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionError,
    ToolObservation,
)


class InventoryTool(Protocol):
    """Common invocation boundary for the Inventory Agent tool allowlist."""

    definition: ClassVar[ToolDefinition]

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation: ...


class _CitySkuInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    city: str
    sku: str


class _DatedCitySkuInput(_CitySkuInput):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates_are_ordered(self) -> _DatedCitySkuInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class _DatedCityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    city: str
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates_are_ordered(self) -> _DatedCityInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class InventoryView(InventoryRecord):
    """Inventory record enriched with a human-readable store name."""

    store_name: str


class InventoryReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: list[InventoryView]


class SalesReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: list[SalesHistory]


class PromotionsReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: list[Promotion]


class WeatherReadOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: list[WeatherForecast]


class ReadOnlyRetailTool:
    """Common validation and error semantics for fixture-backed tools."""

    definition: ClassVar[ToolDefinition]
    input_model: ClassVar[type[BaseModel]]

    def __init__(self, data: RetailData) -> None:
        self._data = data

    def _validate(self, arguments: dict[str, JsonValue]) -> BaseModel:
        try:
            return self.input_model.model_validate(arguments)
        except ValidationError:
            raise ToolExecutionError(
                self.definition.name,
                ToolErrorCode.INVALID_ARGUMENTS,
                f"Invalid arguments for {self.definition.name}",
            ) from None

    def _not_found(self) -> ToolExecutionError:
        return ToolExecutionError(
            self.definition.name,
            ToolErrorCode.NOT_FOUND,
            f"Requested retail data was not found for {self.definition.name}",
        )


class InventoryReadTool(ReadOnlyRetailTool):
    definition = ToolDefinition(
        name="inventory.read",
        description="Read current on-hand inventory and reorder points by city and SKU.",
    )
    input_model = _CitySkuInput

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        parsed = self._validate(arguments)
        assert isinstance(parsed, _CitySkuInput)
        try:
            records = self._data.inventory(parsed.city, parsed.sku)
        except LookupError:
            raise self._not_found() from None
        names = self._data.store_names()
        output = InventoryReadOutput(
            records=[
                InventoryView(**record.model_dump(mode="python"), store_name=names[record.store_id])
                for record in records
            ]
        )
        return ToolObservation(
            data=output.model_dump(mode="json"),
            citations=[
                Citation(source_id=record.source_id, title=f"Inventory at {names[record.store_id]}")
                for record in records
            ],
        )


class SalesReadTool(ReadOnlyRetailTool):
    definition = ToolDefinition(
        name="sales.read",
        description="Read recent unit-sales history by city and SKU.",
    )
    input_model = _DatedCitySkuInput

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        parsed = self._validate(arguments)
        assert isinstance(parsed, _DatedCitySkuInput)
        try:
            records = overlapping(
                parsed.start_date.isoformat(),
                parsed.end_date.isoformat(),
                self._data.sales(parsed.city, parsed.sku),
            )
        except LookupError:
            raise self._not_found() from None
        names = self._data.store_names()
        output = SalesReadOutput(records=records)
        return ToolObservation(
            data=output.model_dump(mode="json"),
            citations=[
                Citation(
                    source_id=record.source_id, title=f"Sales history at {names[record.store_id]}"
                )
                for record in records
            ],
        )


class PromotionsReadTool(ReadOnlyRetailTool):
    definition = ToolDefinition(
        name="promotions.read",
        description="Read promotions overlapping a date range by city and SKU.",
    )
    input_model = _DatedCitySkuInput

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        parsed = self._validate(arguments)
        assert isinstance(parsed, _DatedCitySkuInput)
        try:
            records = overlapping(
                parsed.start_date.isoformat(),
                parsed.end_date.isoformat(),
                self._data.promotions(parsed.city, parsed.sku),
            )
        except LookupError:
            raise self._not_found() from None
        output = PromotionsReadOutput(records=records)
        return ToolObservation(
            data=output.model_dump(mode="json"),
            citations=[
                Citation(source_id=record.source_id, title=f"Promotion {record.promotion_id}")
                for record in records
            ],
        )


class WeatherReadTool(ReadOnlyRetailTool):
    definition = ToolDefinition(
        name="weather.read",
        description="Read a synthetic weather forecast overlapping a city and date range.",
    )
    input_model = _DatedCityInput

    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation:
        parsed = self._validate(arguments)
        assert isinstance(parsed, _DatedCityInput)
        try:
            records = overlapping(
                parsed.start_date.isoformat(),
                parsed.end_date.isoformat(),
                self._data.weather(parsed.city),
            )
        except LookupError:
            raise self._not_found() from None
        output = WeatherReadOutput(records=records)
        return ToolObservation(
            data=output.model_dump(mode="json"),
            citations=[
                Citation(source_id=record.source_id, title=f"Weather forecast for {record.city}")
                for record in records
            ],
        )


def default_inventory_tools(data: RetailData) -> dict[str, InventoryTool]:
    """Build the exact read-only allowlist used by the Inventory Agent."""
    tools: list[InventoryTool] = [
        InventoryReadTool(data),
        SalesReadTool(data),
        PromotionsReadTool(data),
        WeatherReadTool(data),
    ]
    return {tool.definition.name: tool for tool in tools}
