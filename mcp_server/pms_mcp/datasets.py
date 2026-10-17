"""In-memory store for query results.

Tools return a dataset_id plus a preview, so large results stay out of the LLM context
and later tools (charts, spreadsheets, decks) can use the exact rows by id.
"""

import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Dataset:
    id: str
    columns: list[dict[str, str]]  # [{"name": ..., "type": ...}]
    rows: list[list[Any]]
    truncated: bool
    source: str  # SQL text or tool call that produced it
    created_at: float = field(default_factory=time.time)

    def page(self, offset: int, limit: int) -> list[list[Any]]:
        return self.rows[offset:offset + limit]


class DatasetStore:
    """LRU store bounded by number of datasets."""

    def __init__(self, max_datasets: int = 200):
        self.max_datasets = max_datasets
        self._items: OrderedDict[str, Dataset] = OrderedDict()

    def put(self, columns, rows, truncated: bool, source: str) -> Dataset:
        ds = Dataset(f"ds_{secrets.token_hex(6)}", columns, rows, truncated, source)
        self._items[ds.id] = ds
        while len(self._items) > self.max_datasets:
            self._items.popitem(last=False)
        return ds

    def get(self, dataset_id: str) -> Dataset:
        ds = self._items.get(dataset_id)
        if ds is None:
            raise KeyError(dataset_id)
        self._items.move_to_end(dataset_id)
        return ds
