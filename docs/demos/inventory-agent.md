# Inventory Agent demonstration

The Inventory Agent answers bounded stock-risk questions from fictional retail fixtures. It
uses a deterministic reference date and makes no network or paid model calls.

## Reference scenario

```bash
make demo-inventory
```

Question:

```text
Which Toronto stores may run low on snow shovels this weekend?
```

The default `as_of` date is 2026-09-08, so “this weekend” means 2026-09-12 through 2026-09-13.
The graph calls, in order:

1. `inventory.read` for current stock and reorder points;
2. `sales.read` for the prior seven days of unit history;
3. `promotions.read` for promotions overlapping the weekend;
4. `weather.read` for the weekend forecast.

All four tools are schema-validated and read-only. Their outputs include stable source IDs from
the files under `data/synthetic/`.

## Calculation

The deterministic risk heuristic is:

```text
average daily sales × 2 weekend days × promotion lift × weather lift
```

A store is reported at risk when projected remaining stock falls below its reorder point. The
reference fixtures apply a `1.25` promotion lift and a `1.5` snow-weather lift:

| Store | On hand | Projected demand | Reorder point | Result |
|---|---:|---:|---:|---|
| Queen Street | 10 | 20.4 | 15 | May run low |
| York Mills | 42 | 10.7 | 18 | Not currently at risk |

This is an inspectable demo heuristic, not a trained forecast or a production replenishment
recommendation.

## Alternate CLI input

```bash
.venv/bin/python -m agents.inventory \
  'Which Toronto stores may run low on ice melt this weekend?' \
  --seed 12 \
  --as-of 2026-09-08
```

The CLI writes JSON containing `answer`, `model`, `citations`, `tool_calls`, and `usage`.
Identical query, seed, date, fixtures, and code produce identical output.

## HTTP invocation

Start the service with `make run`, then call:

```bash
curl -s http://127.0.0.1:8000/agents/inventory/invoke \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: inventory-demo-1' \
  -d '{"query":"Which Toronto stores may run low on snow shovels this weekend?","seed":7,"as_of":"2026-09-08"}'
```

Invalid cities, products, dates, and payloads return the standard error envelope without
echoing submitted values. Tool, model, total-timeout, and step-limit failures also map to stable
error codes.

## Limitations

- City and product recognition is deterministic matching over fixture names and aliases.
- Only Toronto, Vancouver, Snow Shovel, and Ice Melt exist in the Phase 01 fixtures.
- The fake model demonstrates the runtime contract, replay, and evidence flow; it does not
  demonstrate hosted-model answer quality.
- Inventory and evidence are read-only in Phase 01. Registration and persistence begin in later
  phases.
