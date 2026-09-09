"""Validated, immutable access to the synthetic retail fixtures."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Store(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    store_id: str
    name: str
    city: str
    province: str


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sku: str
    name: str
    aliases: list[str]


class InventoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    store_id: str
    sku: str
    on_hand: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    source_id: str


class SalesHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    store_id: str
    sku: str
    start_date: str
    end_date: str
    daily_units: list[int] = Field(min_length=1)
    source_id: str


class Promotion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    promotion_id: str
    city: str
    sku: str
    start_date: str
    end_date: str
    demand_lift: float = Field(ge=1.0)
    source_id: str


class WeatherForecast(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    city: str
    start_date: str
    end_date: str
    condition: str
    snowfall_cm: float = Field(ge=0.0)
    demand_lift: float = Field(ge=1.0)
    source_id: str


class RetailDataset(BaseModel):
    """Complete fixture set with cross-file referential validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stores: list[Store]
    products: list[Product]
    inventory: list[InventoryRecord]
    sales: list[SalesHistory]
    promotions: list[Promotion]
    weather: list[WeatherForecast]

    @model_validator(mode="after")
    def validate_references(self) -> RetailDataset:
        store_ids = {store.store_id for store in self.stores}
        cities = {store.city.casefold() for store in self.stores}
        skus = {product.sku for product in self.products}
        source_ids: list[str] = []

        for inventory_record in self.inventory:
            if inventory_record.store_id not in store_ids or inventory_record.sku not in skus:
                raise ValueError("Retail fixture contains an unknown store or SKU reference")
            source_ids.append(inventory_record.source_id)
        for sales_record in self.sales:
            if sales_record.store_id not in store_ids or sales_record.sku not in skus:
                raise ValueError("Sales fixture contains an unknown store or SKU reference")
            source_ids.append(sales_record.source_id)
        for promotion in self.promotions:
            if promotion.city.casefold() not in cities or promotion.sku not in skus:
                raise ValueError("Promotion fixture contains an unknown city or SKU reference")
            source_ids.append(promotion.source_id)
        for forecast in self.weather:
            if forecast.city.casefold() not in cities:
                raise ValueError("Weather fixture contains an unknown city reference")
            source_ids.append(forecast.source_id)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Retail fixture source IDs must be unique")
        return self


class RetailData:
    """Read-only query facade over a validated in-memory fixture set."""

    _FILES: ClassVar[dict[str, tuple[str, type[BaseModel]]]] = {
        "stores": ("stores.json", Store),
        "products": ("products.json", Product),
        "inventory": ("inventory.json", InventoryRecord),
        "sales": ("sales.json", SalesHistory),
        "promotions": ("promotions.json", Promotion),
        "weather": ("weather.json", WeatherForecast),
    }

    def __init__(self, dataset: RetailDataset) -> None:
        self.dataset = dataset

    @classmethod
    def load(cls, directory: Path | None = None) -> RetailData:
        fixture_directory = directory or Path(__file__).parents[2] / "data" / "synthetic"
        values: dict[str, list[BaseModel]] = {}
        try:
            for field, (filename, model_type) in cls._FILES.items():
                raw_records = json.loads((fixture_directory / filename).read_text(encoding="utf-8"))
                values[field] = [model_type.model_validate(record) for record in raw_records]
            return cls(RetailDataset.model_validate(values))
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ValueError("Synthetic retail fixtures are invalid") from exc

    def resolve_city(self, query: str) -> str:
        for city in sorted({store.city for store in self.dataset.stores}):
            if city.casefold() in query.casefold():
                return city
        raise LookupError("No supported city was found in the request")

    def resolve_sku(self, query: str) -> str:
        normalized_query = query.casefold()
        for product in self.dataset.products:
            names = [product.name, product.sku, *product.aliases]
            if any(name.casefold() in normalized_query for name in names):
                return product.sku
        raise LookupError("No supported SKU was found in the request")

    def stores_in_city(self, city: str) -> list[Store]:
        self._require_city(city)
        return [store for store in self.dataset.stores if store.city.casefold() == city.casefold()]

    def inventory(self, city: str, sku: str) -> list[InventoryRecord]:
        store_ids = {store.store_id for store in self.stores_in_city(city)}
        self._require_sku(sku)
        return [
            record
            for record in self.dataset.inventory
            if record.store_id in store_ids and record.sku == sku
        ]

    def sales(self, city: str, sku: str) -> list[SalesHistory]:
        store_ids = {store.store_id for store in self.stores_in_city(city)}
        self._require_sku(sku)
        return [
            record
            for record in self.dataset.sales
            if record.store_id in store_ids and record.sku == sku
        ]

    def promotions(self, city: str, sku: str) -> list[Promotion]:
        self._require_city(city)
        self._require_sku(sku)
        return [
            promotion
            for promotion in self.dataset.promotions
            if promotion.city.casefold() == city.casefold() and promotion.sku == sku
        ]

    def weather(self, city: str) -> list[WeatherForecast]:
        self._require_city(city)
        return [
            forecast
            for forecast in self.dataset.weather
            if forecast.city.casefold() == city.casefold()
        ]

    def store_names(self) -> dict[str, str]:
        return {store.store_id: store.name for store in self.dataset.stores}

    def product_name(self, sku: str) -> str:
        self._require_sku(sku)
        return next(product.name for product in self.dataset.products if product.sku == sku)

    def _require_city(self, city: str) -> None:
        if city.casefold() not in {store.city.casefold() for store in self.dataset.stores}:
            raise LookupError("Unknown city")

    def _require_sku(self, sku: str) -> None:
        if sku not in {product.sku for product in self.dataset.products}:
            raise LookupError("Unknown SKU")


def overlapping[Period: (SalesHistory, Promotion, WeatherForecast)](
    start: str, end: str, records: Iterable[Period]
) -> list[Period]:
    """Return fixture periods that overlap an inclusive ISO date range."""
    return [record for record in records if record.start_date <= end and record.end_date >= start]
