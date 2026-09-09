"""Unit tests for validated, read-only retail fixtures and tools."""

import asyncio
from typing import Protocol

import pytest
from pydantic import ValidationError

from agents.inventory.data import InventoryRecord, Product, RetailData, RetailDataset, Store
from agents.inventory.tools import (
    InventoryReadTool,
    PromotionsReadTool,
    SalesReadTool,
    WeatherReadTool,
    default_inventory_tools,
)
from packages.contracts.runtime import JsonValue, ToolErrorCode, ToolExecutionError, ToolObservation


@pytest.fixture(scope="module")
def retail_data() -> RetailData:
    return RetailData.load()


class InvokableTool(Protocol):
    async def invoke(self, arguments: dict[str, JsonValue]) -> ToolObservation: ...


def invoke(tool: InvokableTool, arguments: dict[str, JsonValue]) -> ToolObservation:
    return asyncio.run(tool.invoke(arguments))


@pytest.mark.unit
def test_fixture_set_loads_with_stable_references(retail_data: RetailData) -> None:
    assert len(retail_data.dataset.stores) == 3
    assert retail_data.resolve_city("What about TORONTO this weekend?") == "Toronto"
    assert retail_data.resolve_sku("Will snow shovels run low?") == "snow-shovel"


@pytest.mark.unit
def test_fixture_validation_rejects_unknown_references() -> None:
    with pytest.raises(ValidationError, match="unknown store or SKU"):
        RetailDataset(
            stores=[],
            products=[],
            inventory=[
                InventoryRecord(
                    store_id="missing",
                    sku="missing",
                    on_hand=1,
                    reorder_point=1,
                    source_id="inventory:missing",
                )
            ],
            sales=[],
            promotions=[],
            weather=[],
        )


@pytest.mark.unit
def test_inventory_tool_returns_only_city_sku_records(retail_data: RetailData) -> None:
    observation = invoke(InventoryReadTool(retail_data), {"city": "Toronto", "sku": "snow-shovel"})

    records = observation.data["records"]
    assert isinstance(records, list)
    assert len(records) == 2
    assert {citation.source_id for citation in observation.citations} == {
        "inventory:store-tor-queen:snow-shovel:2026-09-08",
        "inventory:store-tor-york:snow-shovel:2026-09-08",
    }


@pytest.mark.unit
def test_sales_tool_filters_nonoverlapping_history(retail_data: RetailData) -> None:
    observation = invoke(
        SalesReadTool(retail_data),
        {
            "city": "Toronto",
            "sku": "snow-shovel",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
        },
    )

    assert observation.data == {"records": []}
    assert observation.citations == []


@pytest.mark.unit
def test_promotion_and_weather_tools_filter_to_weekend(retail_data: RetailData) -> None:
    period: dict[str, JsonValue] = {
        "start_date": "2026-09-12",
        "end_date": "2026-09-13",
    }

    promotion = invoke(
        PromotionsReadTool(retail_data),
        {"city": "Toronto", "sku": "snow-shovel", **period},
    )
    weather = invoke(WeatherReadTool(retail_data), {"city": "Toronto", **period})

    promotion_records = promotion.data["records"]
    weather_records = weather.data["records"]
    assert isinstance(promotion_records, list)
    assert isinstance(weather_records, list)
    assert isinstance(promotion_records[0], dict)
    assert isinstance(weather_records[0], dict)
    assert promotion_records[0]["demand_lift"] == 1.25
    assert weather_records[0]["snowfall_cm"] == 17.0


@pytest.mark.unit
def test_tools_reject_invalid_dates_without_echoing_values(retail_data: RetailData) -> None:
    with pytest.raises(ToolExecutionError) as raised:
        invoke(
            SalesReadTool(retail_data),
            {
                "city": "Toronto",
                "sku": "snow-shovel",
                "start_date": "not-a-secret-date",
                "end_date": "2026-09-08",
            },
        )

    assert raised.value.code == ToolErrorCode.INVALID_ARGUMENTS
    assert "not-a-secret-date" not in raised.value.message


@pytest.mark.unit
def test_tools_reject_unknown_city_safely(retail_data: RetailData) -> None:
    with pytest.raises(ToolExecutionError) as raised:
        invoke(InventoryReadTool(retail_data), {"city": "Atlantis", "sku": "snow-shovel"})

    assert raised.value.code == ToolErrorCode.NOT_FOUND
    assert raised.value.tool_name == "inventory.read"


@pytest.mark.unit
def test_inventory_tool_handles_valid_empty_data() -> None:
    data = RetailData(
        RetailDataset(
            stores=[Store(store_id="store-1", name="Empty Store", city="Toronto", province="ON")],
            products=[Product(sku="snow-shovel", name="Snow Shovel", aliases=["shovel"])],
            inventory=[],
            sales=[],
            promotions=[],
            weather=[],
        )
    )

    observation = invoke(InventoryReadTool(data), {"city": "Toronto", "sku": "snow-shovel"})

    assert observation.data == {"records": []}
    assert observation.citations == []


@pytest.mark.unit
def test_default_tool_allowlist_contains_only_read_operations(retail_data: RetailData) -> None:
    tools = default_inventory_tools(retail_data)

    assert set(tools) == {
        "inventory.read",
        "sales.read",
        "promotions.read",
        "weather.read",
    }
    assert all(tool.definition.read_only for tool in tools.values())
