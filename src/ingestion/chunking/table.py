"""Conservative table chunks. Only Phase 6 gate-passing structured tables enter."""

from __future__ import annotations

from typing import Any

from ..gate import can_index
from .common import ChunkFactory


def chunk_accepted_tables(document: dict[str, Any], pages: list[dict[str, Any]], factory: ChunkFactory) -> int:
    count = 0
    row_group_size = max(1, int(factory.config.get("table_row_group_size", 12)))
    for page in pages:
        if not can_index(page):
            continue
        for table in page.get("tables") or []:
            if not can_index(table):
                continue
            # Enforce the prior classification gate; unknown/review candidates are not promoted.
            if table.get("classification") not in {"simple_table", "merged_cell_table", "multi_page_table"}:
                continue
            rows = table.get("rows") or []
            parent = factory.add_table(document=document, page=page, table=table,
                                       row_start=0, row_end=len(rows), chunk_type="parent")
            if not parent:
                continue
            count += 1
            if len(rows) <= row_group_size:
                factory.add_table(document=document, page=page, table=table,
                                  row_start=0, row_end=len(rows), chunk_type="child",
                                  parent_chunk_id=parent["chunk_id"])
                continue
            for start in range(0, len(rows), row_group_size):
                factory.add_table(document=document, page=page, table=table,
                                  row_start=start, row_end=min(len(rows), start + row_group_size),
                                  chunk_type="child", parent_chunk_id=parent["chunk_id"])
    return count
