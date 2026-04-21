from __future__ import annotations

import sqlite3

from db.paths import DEV_DB_PATH, LOCAL_COST_APP_PATH


SYNC_TARGETS = {
    "development_projects": "products",
    "items": "items",
    "item_bom": "item_bom",
    "raw_materials": "items",
    "sub_materials": "items",
    "mb_materials": "items",
}


def list_tables(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [row[0] for row in rows]


def inspect_cost_sync_scope() -> dict[str, object]:
    dev_tables = set(list_tables(str(DEV_DB_PATH)))
    mapped = {src: dst for src, dst in SYNC_TARGETS.items() if src in dev_tables}
    local_cost_tables = {
        "resource_rates",
        "simulation_headers",
        "simulation_lines",
    }
    missing_cost_targets = sorted(table for table in local_cost_tables if table not in dev_tables)
    return {
        "dev_db": str(DEV_DB_PATH),
        "cost_app": str(LOCAL_COST_APP_PATH),
        "mapped_tables": mapped,
        "missing_cost_targets": missing_cost_targets,
    }
