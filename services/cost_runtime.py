from __future__ import annotations

import importlib.util

import pandas as pd
import streamlit as st

from db.paths import DEV_DB_PATH, LOCAL_COST_APP_PATH
from db.runtime import execute, get_connection, query_df
from services.default_resolver_service import resolve_cost_simulation_defaults
from services.reference_data_service import get_item_bom, get_items, get_mb_materials, get_products, get_raw_materials, get_sub_materials
from services.shell_service import render_flash_messages


def _cost_items_df() -> pd.DataFrame:
    process_items = get_items().copy()
    if not process_items.empty:
        process_items = process_items.assign(
            item_id=process_items["item_id"].astype(str),
            item_code=process_items["item_code"].fillna(""),
            item_kind="제품",
            sub_kind="",
            unit="EA",
            current_price_per_kg=0.0,
            current_unit_price=0.0,
        )[["item_id", "item_code", "item_name", "item_kind", "sub_kind", "process_type", "unit", "current_price_per_kg", "current_unit_price", "notes"]]

    raw_df = get_raw_materials().copy()
    if not raw_df.empty:
        raw_df = raw_df.assign(
            item_id=raw_df["raw_material_id"].map(lambda v: f"RAW-{v}"),
            item_code=raw_df["material_code"].fillna(""),
            item_kind="원재료",
            sub_kind=raw_df["material_type"].fillna("원료"),
            process_type="",
            unit="kg",
            current_price_per_kg=0.0,
            current_unit_price=0.0,
        )[["item_id", "item_code", "material_name", "item_kind", "sub_kind", "process_type", "unit", "current_price_per_kg", "current_unit_price", "notes"]].rename(columns={"material_name": "item_name"})

    sub_df = get_sub_materials().copy()
    if not sub_df.empty:
        sub_df = sub_df.assign(
            item_id=sub_df["sub_material_id"].map(lambda v: f"SUB-{v}"),
            item_code=sub_df["material_code"].fillna(""),
            item_kind="부재료",
            sub_kind=sub_df["material_type"].fillna("기타"),
            process_type="",
            unit="EA",
            current_price_per_kg=0.0,
            current_unit_price=0.0,
        )[["item_id", "item_code", "material_name", "item_kind", "sub_kind", "process_type", "unit", "current_price_per_kg", "current_unit_price", "notes"]].rename(columns={"material_name": "item_name"})

    mb_df = get_mb_materials().copy()
    if not mb_df.empty:
        mb_df = mb_df.assign(
            item_id=mb_df["mb_material_id"].map(lambda v: f"MB-{v}"),
            item_code=mb_df["mb_code"].fillna(""),
            item_kind="원재료",
            sub_kind="MB",
            process_type="",
            unit="kg",
            current_price_per_kg=0.0,
            current_unit_price=0.0,
        )[["item_id", "item_code", "mb_name", "item_kind", "sub_kind", "process_type", "unit", "current_price_per_kg", "current_unit_price", "notes"]].rename(columns={"mb_name": "item_name"})

    frames = [df for df in [process_items, raw_df, sub_df, mb_df] if not df.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["item_id", "item_code", "item_name", "item_kind", "sub_kind", "process_type", "unit", "current_price_per_kg", "current_unit_price", "notes"])


def _cost_products_df() -> pd.DataFrame:
    products_df = get_products()
    if products_df.empty:
        return pd.DataFrame(columns=["project_code", "project_name", "product_code", "product_name", "result_item_id", "result_item_code", "result_item_name", "notes"])
    result_df = products_df.copy()
    result_df["result_item_id"] = result_df["linked_item_id"].fillna(result_df["root_item_id"]).fillna("").astype(str)
    result_df["result_item_code"] = result_df["linked_item_code"].fillna("")
    result_df["result_item_name"] = result_df["linked_item_name"].fillna("")
    return result_df[["project_code", "project_name", "product_code", "product_name", "result_item_id", "result_item_code", "result_item_name", "notes"]]


def _cost_bom_df() -> pd.DataFrame:
    bom_df = get_item_bom().copy()
    if bom_df.empty:
        return pd.DataFrame(columns=["bom_id", "parent_item_id", "child_item_id", "quantity", "quantity_unit", "notes", "child_item_name", "child_item_kind"])
    items_df = _cost_items_df()
    kind_map = dict(zip(items_df["item_id"], items_df["item_kind"]))
    name_map = dict(zip(items_df["item_id"], items_df["item_name"]))
    return pd.DataFrame(
        {
            "bom_id": bom_df["bom_id"],
            "parent_item_id": bom_df["parent_item_id"].astype(str),
            "child_item_id": bom_df["child_item_id"].astype(str),
            "quantity": bom_df["qty"],
            "quantity_unit": bom_df["qty_unit"],
            "notes": bom_df["notes"],
            "child_item_name": bom_df["child_item_id"].astype(str).map(name_map).fillna(""),
            "child_item_kind": bom_df["child_item_id"].astype(str).map(kind_map).fillna(""),
        }
    )


def _cost_resource_rates_df() -> pd.DataFrame:
    return query_df("SELECT * FROM resource_rates ORDER BY resource_code")


def _cost_query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    return query_df(sql, params)


def _cost_execute(sql: str, params: tuple = ()) -> None:
    execute(sql, params)


def _cost_get_connection():
    return get_connection(DEV_DB_PATH)


def _cost_init_db() -> None:
    with get_connection(DEV_DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        existing_pre_project_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(pre_estimate_projects)").fetchall()
        } if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pre_estimate_projects'").fetchone() else set()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_rates (
                resource_code TEXT PRIMARY KEY,
                resource_name TEXT NOT NULL,
                daily_rate REAL NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simulation_headers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_name TEXT NOT NULL,
                product_code TEXT NOT NULL,
                product_name TEXT NOT NULL,
                customer TEXT,
                daily_hours REAL NOT NULL DEFAULT 22,
                total_cost REAL NOT NULL DEFAULT 0,
                input_state_json TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS simulation_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulation_id INTEGER NOT NULL,
                route_id INTEGER,
                seq INTEGER NOT NULL,
                process_type TEXT NOT NULL,
                process_name TEXT NOT NULL,
                output_item_id TEXT NOT NULL,
                output_item_name TEXT NOT NULL,
                material_cost REAL NOT NULL DEFAULT 0,
                process_cost REAL NOT NULL DEFAULT 0,
                packaging_cost REAL NOT NULL DEFAULT 0,
                moving_cost REAL NOT NULL DEFAULT 0,
                own_cost REAL NOT NULL DEFAULT 0,
                cumulative_cost REAL NOT NULL DEFAULT 0,
                formula_text TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                item_id TEXT,
                item_name TEXT,
                item_kind TEXT,
                FOREIGN KEY(simulation_id) REFERENCES simulation_headers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pre_estimate_projects (
                pre_project_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                customer_name TEXT,
                item_count INTEGER NOT NULL DEFAULT 1,
                annual_sales_qty REAL NOT NULL DEFAULT 0,
                root_item_name TEXT,
                root_process_type TEXT,
                pc_definition TEXT,
                description TEXT,
                development_type TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        if "root_item_name" not in existing_pre_project_columns:
            conn.execute("ALTER TABLE pre_estimate_projects ADD COLUMN root_item_name TEXT")
        if "item_count" not in existing_pre_project_columns:
            conn.execute("ALTER TABLE pre_estimate_projects ADD COLUMN item_count INTEGER NOT NULL DEFAULT 1")
        if "annual_sales_qty" not in existing_pre_project_columns:
            conn.execute("ALTER TABLE pre_estimate_projects ADD COLUMN annual_sales_qty REAL NOT NULL DEFAULT 0")
        if "root_process_type" not in existing_pre_project_columns:
            conn.execute("ALTER TABLE pre_estimate_projects ADD COLUMN root_process_type TEXT")
        if "pc_definition" not in existing_pre_project_columns:
            conn.execute("ALTER TABLE pre_estimate_projects ADD COLUMN pc_definition TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pre_estimate_items (
                pre_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pre_project_id INTEGER NOT NULL,
                parent_pre_item_id INTEGER,
                item_name TEXT NOT NULL,
                process_type TEXT NOT NULL,
                material_cost REAL NOT NULL DEFAULT 0,
                process_cost REAL NOT NULL DEFAULT 0,
                management_rate_pct REAL NOT NULL DEFAULT 0,
                defect_rate_pct REAL NOT NULL DEFAULT 0,
                packaging_cost REAL NOT NULL DEFAULT 0,
                moving_cost REAL NOT NULL DEFAULT 0,
                mold_cost REAL NOT NULL DEFAULT 0,
                lead_days REAL NOT NULL DEFAULT 0,
                detail_json TEXT,
                notes TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(pre_project_id) REFERENCES pre_estimate_projects(pre_project_id) ON DELETE CASCADE,
                FOREIGN KEY(parent_pre_item_id) REFERENCES pre_estimate_items(pre_item_id) ON DELETE SET NULL
            )
            """
        )
        existing_pre_item_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(pre_estimate_items)").fetchall()
        } if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pre_estimate_items'").fetchone() else set()
        if "detail_json" not in existing_pre_item_columns:
            conn.execute("ALTER TABLE pre_estimate_items ADD COLUMN detail_json TEXT")
        conn.commit()


def _cost_reset_cache() -> None:
    return None


def _render_master_tab(render_rates_tab) -> None:
    st.subheader("기초정보")
    st.info("상품/공정품/BOM/자재는 개발앱 기준정보를 그대로 사용합니다.")
    st.caption("원가앱에서는 사출 임률만 관리합니다.")
    render_rates_tab()


def _apply_development_defaults(defaults: dict[str, dict], tree_df: pd.DataFrame) -> dict[str, dict]:
    item_meta_df = query_df(
        """
        SELECT item_id, project_id, process_type
        FROM items
        """
    )
    if item_meta_df.empty:
        return defaults

    item_meta_map = {str(row["item_id"]): row for _, row in item_meta_df.iterrows()}
    raw_df = get_raw_materials().copy()
    raw_price_map = {}
    if not raw_df.empty:
        raw_price_map = {
            f"RAW-{int(row['raw_material_id'])}": 0.0
            for _, row in raw_df.iterrows()
        }

    for row in tree_df.to_dict("records"):
        node_id = str(row["node_id"])
        item_id = str(row["item_id"])
        item_meta = item_meta_map.get(item_id)
        if item_meta is None or defaults.get(node_id) is None:
            continue
        project_id = int(item_meta["project_id"])
        current_item_id = int(item_meta["item_id"])
        resolved = resolve_cost_simulation_defaults(project_id, current_item_id)
        op_defaults = resolved.get("op_defaults", {})
        node_defaults = defaults[node_id]
        process_type = str(node_defaults.get("process_type") or item_meta["process_type"] or "")

        if process_type != "사출":
            continue

        avg_product_weight = float(op_defaults.get("avg_product_weight") or 0.0)
        runner_weight = float(op_defaults.get("runner_weight") or 0.0)
        cavity = float(op_defaults.get("cavity") or node_defaults.get("cavity") or 1.0)
        ct_sec = float(op_defaults.get("ct_sec") or 0.0)
        raw_material_id = op_defaults.get("raw_material_id")
        mb_request_code = str(op_defaults.get("mb_request_code") or "")
        mb_ratio_pct = float(op_defaults.get("mb_ratio_pct") or 0.0)

        if avg_product_weight > 0:
            node_defaults["weight_g"] = avg_product_weight
        if runner_weight > 0:
            node_defaults["sprue_weight_g"] = runner_weight
        if cavity > 0:
            node_defaults["cavity"] = cavity
        if ct_sec > 0:
            node_defaults["ct_sec"] = ct_sec
        if raw_material_id not in [None, ""]:
            material_code = f"RAW-{int(raw_material_id)}"
            node_defaults["raw_material_1"] = material_code
            node_defaults["raw_material_1_price"] = float(raw_price_map.get(material_code, 0.0))
            node_defaults["raw_material_1_pct"] = max(0.0, 100.0 - max(0.0, min(100.0, mb_ratio_pct))) if mb_ratio_pct > 0 else 100.0
        if mb_request_code:
            node_defaults["mb_code"] = mb_request_code
        if mb_ratio_pct > 0:
            node_defaults["mb_ratio_pct"] = mb_ratio_pct

    return defaults


def load_cost_module():
    spec = importlib.util.spec_from_file_location("local_cost_app", LOCAL_COST_APP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"원가 앱을 불러올 수 없습니다: {LOCAL_COST_APP_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DB_PATH = DEV_DB_PATH
    module.get_connection = _cost_get_connection
    module.query_df = _cost_query_df
    module.execute = _cost_execute
    module.init_db = _cost_init_db
    module.get_items = _cost_items_df
    module.get_products = _cost_products_df
    module.get_item_bom = _cost_bom_df
    module.get_resource_rates = _cost_resource_rates_df
    module.reset_cache = _cost_reset_cache
    original_render_rates_tab = module.render_rates_tab
    original_build_default_item_inputs = module.build_default_item_inputs

    def _patched_render_master_tab() -> None:
        _render_master_tab(original_render_rates_tab)

    def _patched_build_default_item_inputs(tree_df: pd.DataFrame) -> dict[str, dict]:
        defaults = original_build_default_item_inputs(tree_df)
        return _apply_development_defaults(defaults, tree_df)

    module.render_master_tab = _patched_render_master_tab
    module.build_default_item_inputs = _patched_build_default_item_inputs
    return module


def run_cost_app() -> None:
    render_flash_messages()
    load_cost_module().main()
