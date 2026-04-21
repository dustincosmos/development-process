from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st
from services.shell_service import flash_success


DB_PATH = Path(__file__).resolve().parent / "cost_management.db"
DEFAULT_DAILY_HOURS = 22.0
PROCESS_TYPES = ["사출", "증착", "코팅", "인쇄", "조립", "사상", "기타", "포장", "이동"]
PRODUCT_UNITS = ["EA"]
MATERIAL_UNITS = ["EA", "g", "kg"]
QTY_UNITS = ["ea", "percent", "g"]
MATERIAL_SUBKINDS = ["원료", "MB", "바킹", "기타"]
PROCESS_CODE_PREFIXES = {
    "사출": "SI",
    "증착": "SV",
    "코팅": "SC",
    "인쇄": "SP",
    "조립": "SA",
    "사상": "SK",
    "기타": "ETC",
    "포장": "PKG",
    "이동": "MOV",
}
MATERIAL_SUBKIND_PREFIXES = {
    "원료": "4M",
    "MB": "5M",
    "바킹": "C",
    "기타": "SUB",
}


st.set_page_config(page_title="원가관리 도구", layout="wide")


def render_app_header() -> None:
    st.markdown(
        """
        <div style="display:flex; justify-content:flex-end; margin-bottom:0.5rem;">
            <div style="font-size:0.9rem; color:#666;">원가관리 도구</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def execute(sql: str, params: tuple = ()) -> None:
    with get_connection() as conn:
        conn.execute(sql, params)
        conn.commit()


def executemany(sql: str, rows: list[tuple]) -> None:
    with get_connection() as conn:
        conn.executemany(sql, rows)
        conn.commit()


def safe_float(value: object) -> float:
    try:
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return 0.0
        if pd.isna(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def estimate_dataframe_width(df: pd.DataFrame, padding: int = 120) -> int:
    if df is None or df.empty:
        return 640
    width = padding
    sample_df = df.head(20).fillna("")
    for column in sample_df.columns:
        max_len = max(len(str(column)), sample_df[column].astype(str).map(len).max())
        width += min(max_len * 11 + 36, 320)
    return max(560, min(width, 1400))


def render_dataframe(df: pd.DataFrame) -> None:
    st.dataframe(df, width=estimate_dataframe_width(df), hide_index=True)


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in get_table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                item_name TEXT NOT NULL,
                item_kind TEXT NOT NULL,
                sub_kind TEXT,
                process_type TEXT,
                unit TEXT NOT NULL,
                current_price_per_kg REAL NOT NULL DEFAULT 0,
                current_unit_price REAL NOT NULL DEFAULT 0,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS products (
                product_code TEXT PRIMARY KEY,
                product_name TEXT NOT NULL,
                result_item_id TEXT NOT NULL UNIQUE,
                notes TEXT,
                FOREIGN KEY(result_item_id) REFERENCES items(item_id)
            );

            CREATE TABLE IF NOT EXISTS resource_rates (
                resource_code TEXT PRIMARY KEY,
                resource_name TEXT NOT NULL,
                daily_rate REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS item_bom (
                bom_id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_item_id TEXT NOT NULL,
                child_item_id TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                quantity_unit TEXT NOT NULL DEFAULT 'ea',
                notes TEXT,
                UNIQUE(parent_item_id, child_item_id),
                FOREIGN KEY(parent_item_id) REFERENCES items(item_id),
                FOREIGN KEY(child_item_id) REFERENCES items(item_id)
            );

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
            );

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
            );

            """
        )
        add_column_if_missing(conn, "items", "sub_kind", "TEXT")
        add_column_if_missing(conn, "items", "process_type", "TEXT")
        add_column_if_missing(conn, "simulation_headers", "input_state_json", "TEXT")
        add_column_if_missing(conn, "simulation_lines", "route_id", "INTEGER")
        add_column_if_missing(conn, "simulation_lines", "process_name", "TEXT")
        add_column_if_missing(conn, "simulation_lines", "output_item_id", "TEXT")
        add_column_if_missing(conn, "simulation_lines", "output_item_name", "TEXT")
        add_column_if_missing(conn, "simulation_lines", "material_cost", "REAL NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "simulation_lines", "process_cost", "REAL NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "simulation_lines", "packaging_cost", "REAL NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "simulation_lines", "moving_cost", "REAL NOT NULL DEFAULT 0")
        add_column_if_missing(conn, "simulation_lines", "item_id", "TEXT")
        add_column_if_missing(conn, "simulation_lines", "item_name", "TEXT")
        add_column_if_missing(conn, "simulation_lines", "item_kind", "TEXT")
        conn.commit()


@st.cache_data(show_spinner=False)
def get_items() -> pd.DataFrame:
    return query_df("SELECT * FROM items ORDER BY item_id")


@st.cache_data(show_spinner=False)
def get_products() -> pd.DataFrame:
    return query_df(
        """
        SELECT p.*, i.item_name AS result_item_name
        FROM products p
        LEFT JOIN items i ON p.result_item_id = i.item_id
        ORDER BY p.product_code
        """
    )


@st.cache_data(show_spinner=False)
def get_resource_rates() -> pd.DataFrame:
    return query_df("SELECT * FROM resource_rates ORDER BY resource_code")


@st.cache_data(show_spinner=False)
def get_item_bom() -> pd.DataFrame:
    return query_df(
        """
        SELECT b.*, c.item_name AS child_item_name, c.item_kind AS child_item_kind
        FROM item_bom b
        LEFT JOIN items c ON b.child_item_id = c.item_id
        ORDER BY b.parent_item_id, b.child_item_id
        """
    )


def reset_cache() -> None:
    get_items.clear()
    get_products.clear()
    get_resource_rates.clear()
    get_item_bom.clear()


def next_code_for_prefix(prefix: str, item_ids: list[str]) -> str:
    max_seq = 0
    for item_id in item_ids:
        if not item_id.startswith(prefix):
            continue
        suffix = item_id[len(prefix):]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:04d}"


def reset_widget_keys(keys: list[str]) -> None:
    for key in keys:
        st.session_state.pop(key, None)


def ensure_widget_value(key: str, value: object, overwrite: bool = False) -> None:
    if overwrite or key not in st.session_state:
        st.session_state[key] = value


def simulation_widget_key(node_id: str, field_name: str, prefix: str = "simulation") -> str:
    return f"{prefix}_{node_id}_{field_name}"


def prime_simulation_widget(node_id: str, field_name: str, value: object, prefix: str = "simulation") -> str:
    widget_key = simulation_widget_key(node_id, field_name, prefix=prefix)
    if widget_key not in st.session_state:
        st.session_state[widget_key] = value
    return widget_key


def sync_simulation_widget(node_id: str, field_name: str, value: object, prefix: str = "simulation") -> str:
    widget_key = simulation_widget_key(node_id, field_name, prefix=prefix)
    force_sync_key = f"{prefix}_force_widget_sync"
    if st.session_state.get(force_sync_key) or widget_key not in st.session_state:
        st.session_state[widget_key] = value
    return widget_key


def serialize_simulation_inputs(item_inputs: dict[str, dict]) -> str:
    return json.dumps(item_inputs, ensure_ascii=False)


def load_saved_simulation_inputs(simulation_id: int) -> dict[str, dict] | None:
    row = query_df("SELECT input_state_json FROM simulation_headers WHERE id = ?", (simulation_id,))
    if row.empty:
        return None
    raw = row.iloc[0]["input_state_json"]
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def derive_header_daily_hours(item_inputs: dict[str, dict]) -> float:
    for values in item_inputs.values():
        if (values.get("process_type") or "") == "사출":
            return max(1.0, safe_float(values.get("daily_hours")) or DEFAULT_DAILY_HOURS)
    return DEFAULT_DAILY_HOURS


def would_create_bom_cycle(parent_item_id: str, child_item_id: str) -> bool:
    if parent_item_id == child_item_id:
        return True

    bom_map: dict[str, list[str]] = {}
    for _, row in get_item_bom().iterrows():
        bom_map.setdefault(row["parent_item_id"], []).append(row["child_item_id"])

    stack = [child_item_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == parent_item_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(bom_map.get(current, []))
    return False


def build_product_bom_tree(root_item_id: str) -> pd.DataFrame:
    items_by_id = {row["item_id"]: row.to_dict() for _, row in get_items().iterrows()}
    bom_map: dict[str, list[dict]] = {}
    for _, row in get_item_bom().iterrows():
        bom_map.setdefault(row["parent_item_id"], []).append(row.to_dict())
    rows: list[dict] = []

    def walk(item_id: str, node_id: str, parent_node_id: str | None, level: int, path: tuple[str, ...]) -> None:
        if item_id in path:
            cycle_path = " -> ".join([*path, item_id])
            raise ValueError(f"BOM 순환이 감지되었습니다: {cycle_path}")
        item = items_by_id[item_id]
        rows.append(
            {
                "node_id": node_id,
                "parent_node_id": parent_node_id or "",
                "level": level,
                "item_id": item_id,
                "item_code": item.get("item_code") or item_id,
                "item_name": item["item_name"],
                "item_kind": item["item_kind"],
                "label": f"{'  ' * level}{item.get('item_code') or item_id} | {item['item_name']}",
            }
        )
        for idx, child in enumerate(bom_map.get(item_id, []), start=1):
            child_item = items_by_id[child["child_item_id"]]
            if child_item["item_kind"] != "제품":
                continue
            walk(child["child_item_id"], f"{node_id}.{idx}", node_id, level + 1, (*path, item_id))

    walk(root_item_id, "1", None, 0, ())
    return pd.DataFrame(rows)


def build_default_item_inputs(tree_df: pd.DataFrame) -> dict[str, dict]:
    items_by_id = {row["item_id"]: row.to_dict() for _, row in get_items().iterrows()}
    bom_map: dict[str, list[dict]] = {}
    for _, row in get_item_bom().iterrows():
        bom_map.setdefault(row["parent_item_id"], []).append(row.to_dict())

    defaults: dict[str, dict] = {}
    for row in tree_df.to_dict("records"):
        item = items_by_id[row["item_id"]]
        defaults[row["node_id"]] = {
            "process_type": item.get("process_type") or "",
            "daily_hours": DEFAULT_DAILY_HOURS,
            "resource_code": "",
            "daily_rate": 0.0,
            "ct_sec": 0.0,
            "cavity": 1.0,
            "weight_g": 0.0,
            "sprue_weight_g": 0.0,
            "process_cost": 0.0,
            "packaging_cost": 0.0,
            "moving_cost": 0.0,
            "management_rate_pct": 0.0,
            "defect_rate_pct": 0.0,
            "quantity": 1.0,
            "quantity_unit": "ea",
            "price_per_kg": safe_float(item.get("current_price_per_kg")),
            "unit_price": safe_float(item.get("current_unit_price")),
            "notes": item.get("notes") or "",
            "raw_material_1": "",
            "raw_material_1_pct": 0.0,
            "raw_material_1_price": 0.0,
            "mb_code": "",
            "mb_ratio_pct": 0.0,
            "mb_price": 0.0,
            "raw_material_2": "",
            "raw_material_2_pct": 0.0,
            "raw_material_2_price": 0.0,
            "raw_material_3": "",
            "raw_material_3_pct": 0.0,
            "raw_material_3_price": 0.0,
            "assembly_material_1": "",
            "assembly_material_1_qty": 0.0,
            "assembly_material_2": "",
            "assembly_material_2_qty": 0.0,
        }
        material_children = [child for child in bom_map.get(row["item_id"], []) if items_by_id[child["child_item_id"]]["item_kind"] != "제품"]
        raw_children = []
        mb_children = []
        for child in material_children:
            child_item = items_by_id[child["child_item_id"]]
            if str(child_item.get("sub_kind") or "") == "MB":
                mb_children.append((child, child_item))
            else:
                raw_children.append((child, child_item))

        if raw_children:
            child, child_item = raw_children[0]
            defaults[row["node_id"]]["raw_material_1"] = child["child_item_id"]
            defaults[row["node_id"]]["raw_material_1_pct"] = safe_float(child["quantity"])
            defaults[row["node_id"]]["raw_material_1_price"] = safe_float(child_item.get("current_price_per_kg"))
        if mb_children:
            child, child_item = mb_children[0]
            defaults[row["node_id"]]["mb_code"] = child_item.get("item_code") or child_item.get("item_id") or ""
            defaults[row["node_id"]]["mb_ratio_pct"] = safe_float(child["quantity"])
            defaults[row["node_id"]]["mb_price"] = safe_float(child_item.get("current_price_per_kg"))
        if len(raw_children) > 1:
            child, child_item = raw_children[1]
            defaults[row["node_id"]]["raw_material_2"] = child["child_item_id"]
            defaults[row["node_id"]]["raw_material_2_pct"] = safe_float(child["quantity"])
            defaults[row["node_id"]]["raw_material_2_price"] = safe_float(child_item.get("current_price_per_kg"))
        if len(raw_children) > 2:
            child, child_item = raw_children[2]
            defaults[row["node_id"]]["raw_material_3"] = child["child_item_id"]
            defaults[row["node_id"]]["raw_material_3_pct"] = safe_float(child["quantity"])
            defaults[row["node_id"]]["raw_material_3_price"] = safe_float(child_item.get("current_price_per_kg"))
    return defaults


def normalize_bom_inputs(tree_df: pd.DataFrame, current_inputs: dict[str, dict] | None) -> dict[str, dict]:
    defaults = build_default_item_inputs(tree_df)
    if not current_inputs:
        return defaults
    normalized: dict[str, dict] = {}
    for node_id, default_values in defaults.items():
        merged = default_values.copy()
        if node_id in current_inputs and isinstance(current_inputs[node_id], dict):
            merged.update(current_inputs[node_id])
        normalized[node_id] = merged
    return normalized


def build_bom_simulation(tree_df: pd.DataFrame, item_inputs: dict[str, dict]) -> pd.DataFrame:
    row_map = {row["node_id"]: row for row in tree_df.to_dict("records")}
    children: dict[str, list[str]] = {}
    for row in tree_df.to_dict("records"):
        if row["parent_node_id"]:
            children.setdefault(row["parent_node_id"], []).append(row["node_id"])

    calc: dict[str, dict] = {}

    def walk(node_id: str, parent_weight_g: float) -> float:
        row = row_map[node_id]
        item_input = item_inputs[node_id]
        item_kind = row["item_kind"]
        own_cost = 0.0
        formula_text = ""

        if item_kind in {"원재료", "부재료"}:
            qty = safe_float(item_input["quantity"])
            qty_unit = item_input["quantity_unit"]
            if qty_unit == "ea":
                own_cost = qty * safe_float(item_input["unit_price"])
                formula_text = f"{qty:,.2f}ea x {safe_float(item_input['unit_price']):,.2f}"
            elif qty_unit == "g":
                own_cost = (qty / 1000.0) * safe_float(item_input["price_per_kg"])
                formula_text = f"({qty:,.2f}g/1000) x {safe_float(item_input['price_per_kg']):,.2f}"
            else:
                own_cost = (parent_weight_g / 1000.0) * (qty / 100.0) * safe_float(item_input["price_per_kg"])
                formula_text = f"({parent_weight_g:,.3f}g/1000) x ({qty:,.2f}/100) x {safe_float(item_input['price_per_kg']):,.2f}"
            cumulative = own_cost
        else:
            process_type = item_input.get("process_type") or ""
            material_cost = 0.0
            process_cost = safe_float(item_input["process_cost"])
            management_rate_pct = min(99.99, max(0.0, safe_float(item_input.get("management_rate_pct"))))
            defect_rate_pct = min(99.99, max(0.0, safe_float(item_input.get("defect_rate_pct"))))
            management_cost = 0.0
            defect_cost = 0.0
            if process_type == "사출":
                daily_hours = max(1.0, safe_float(item_input.get("daily_hours")) or DEFAULT_DAILY_HOURS)
                daily_rate = safe_float(item_input["daily_rate"])
                ct_sec = safe_float(item_input["ct_sec"])
                cavity = max(1.0, safe_float(item_input["cavity"]) or 1.0)
                weight_g = safe_float(item_input["weight_g"])
                sprue_weight_g = safe_float(item_input.get("sprue_weight_g"))
                material_weight_g = weight_g + (sprue_weight_g / cavity)
                process_cost = 0.0
                if daily_rate > 0 and ct_sec > 0:
                    process_cost = daily_rate / ((daily_hours * 3600.0 / ct_sec) * cavity)
                formulas = []
                mb_code = item_input.get("mb_code") or ""
                mb_ratio_pct = safe_float(item_input.get("mb_ratio_pct"))
                mb_price = safe_float(item_input.get("mb_price"))
                for idx in range(1, 4):
                    material_id = item_input.get(f"raw_material_{idx}") or ""
                    pct = safe_float(item_input.get(f"raw_material_{idx}_pct"))
                    price_per_kg = safe_float(item_input.get(f"raw_material_{idx}_price"))
                    if not material_id or pct <= 0:
                        continue
                    component = (material_weight_g / 1000.0) * (pct / 100.0) * price_per_kg
                    material_cost += component
                    formulas.append(
                        f"{material_id}: (({weight_g:,.3f}g + ({sprue_weight_g:,.3f}g/{cavity:,.2f}))/1000) x ({pct:,.2f}/100) x {price_per_kg:,.2f}"
                    )
                if mb_code and mb_ratio_pct > 0:
                    component = (material_weight_g / 1000.0) * (mb_ratio_pct / 100.0) * mb_price
                    material_cost += component
                    formulas.append(
                        f"{mb_code}: (({weight_g:,.3f}g + ({sprue_weight_g:,.3f}g/{cavity:,.2f}))/1000) x ({mb_ratio_pct:,.2f}/100) x {mb_price:,.2f}"
                    )
                formula_text = " | ".join(formulas)
                own_cost = material_cost + process_cost
                management_cost = own_cost * (management_rate_pct / 100.0)
                defect_cost = own_cost * (defect_rate_pct / 100.0)
            elif process_type == "조립":
                formulas = []
                material_items = {row["item_id"]: row.to_dict() for _, row in get_items().iterrows()}
                for idx in range(1, 3):
                    material_id = item_input.get(f"assembly_material_{idx}") or ""
                    qty = safe_float(item_input.get(f"assembly_material_{idx}_qty"))
                    if not material_id or qty <= 0:
                        continue
                    unit_price = safe_float(material_items.get(material_id, {}).get("current_unit_price"))
                    material_cost += qty * unit_price
                    formulas.append(f"{material_id}: {qty:,.2f} x {unit_price:,.2f}")
                formula_text = " | ".join(formulas)
            elif process_type != "사출":
                formula_text = ""
            child_total = 0.0
            for child_id in children.get(node_id, []):
                child_total += walk(child_id, safe_float(item_input["weight_g"]))
            if process_type == "사출":
                cumulative = own_cost
            elif process_type == "조립":
                own_cost = material_cost + process_cost
                management_cost = own_cost * (management_rate_pct / 100.0)
                defect_cost = own_cost * (defect_rate_pct / 100.0)
                cumulative = child_total + own_cost + management_cost + defect_cost + safe_float(item_input["packaging_cost"]) + safe_float(item_input["moving_cost"])
            else:
                own_cost = process_cost
                management_cost = own_cost * (management_rate_pct / 100.0)
                defect_cost = own_cost * (defect_rate_pct / 100.0)
                cumulative = child_total + own_cost + management_cost + defect_cost + safe_float(item_input["packaging_cost"]) + safe_float(item_input["moving_cost"])

        calc[node_id] = {
            "own_cost": round(own_cost, 4),
            "cumulative_cost": round(cumulative, 4),
            "formula_text": formula_text,
        }
        return cumulative

    walk("1", 0.0)
    result = tree_df.copy()
    result["own_cost"] = result["node_id"].map(lambda x: calc[x]["own_cost"])
    result["cumulative_cost"] = result["node_id"].map(lambda x: calc[x]["cumulative_cost"])
    result["formula_text"] = result["node_id"].map(lambda x: calc[x]["formula_text"])
    return result


def load_product_tree_or_error(root_item_id: str) -> pd.DataFrame | None:
    try:
        return build_product_bom_tree(root_item_id)
    except ValueError as exc:
        st.error(str(exc))
        return None


def render_simulation_summary_panel(
    *,
    tree_df: pd.DataFrame,
    item_inputs: dict[str, dict],
    selected_item_key: str,
    product_label: str,
    total_cost_label: str | None = None,
) -> dict:
    sim_df = build_bom_simulation(tree_df, item_inputs)
    display_df = sim_df[["label", "own_cost", "cumulative_cost"]].rename(
        columns={"label": "코드 / 이름", "own_cost": "공정단가", "cumulative_cost": "누적단가"}
    )

    if product_label:
        st.write(product_label)
    if total_cost_label:
        st.write(total_cost_label)
    render_dataframe(display_df)
    tree_options = sim_df.apply(lambda row: f"{row['node_id']} | {row['label'].strip()}", axis=1).tolist()
    select_col, current_col = st.columns([1.1, 1.4], gap="large")
    with select_col:
        selected_tree_label = st.selectbox("공정품 선택", options=tree_options, key=selected_item_key)
    selected_node_id = selected_tree_label.split(" | ")[0]
    selected_tree_row = sim_df[sim_df["node_id"] == selected_node_id].iloc[0].to_dict()
    with current_col:
        st.text_input("선택 품목", value=selected_tree_row["label"].strip(), disabled=True, key=f"{selected_item_key}_current")
    return selected_tree_row


def build_history_options_for_product(product_code: str) -> tuple[pd.DataFrame, list[str]]:
    headers = query_df(
        "SELECT id, simulation_name, customer, total_cost, notes, created_at FROM simulation_headers WHERE product_code = ? ORDER BY created_at DESC, id DESC",
        (product_code,),
    )
    options = ["새 시뮬레이션"]
    if not headers.empty:
        headers["label"] = headers.apply(lambda row: f"{row['id']} | {row['simulation_name']} | {row['created_at']}", axis=1)
        options += headers["label"].tolist()
    return headers, options


def save_tree_simulation(
    product_code: str,
    product_name: str,
    simulation_name: str,
    customer: str,
    notes: str,
    sim_df: pd.DataFrame,
    item_inputs: dict[str, dict],
) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    total_cost = safe_float(sim_df.loc[sim_df["node_id"] == "1", "cumulative_cost"].iloc[0]) if not sim_df.empty else 0.0
    daily_hours = derive_header_daily_hours(item_inputs)
    input_state_json = serialize_simulation_inputs(item_inputs)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO simulation_headers (
                simulation_name, product_code, product_name, customer, daily_hours, total_cost, input_state_json, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (simulation_name, product_code, product_name, customer, daily_hours, total_cost, input_state_json, notes, created_at),
        )
        simulation_id = int(cur.lastrowid)
        rows = []
        for seq, row in enumerate(sim_df.to_dict("records"), start=1):
            item_kind = row["item_kind"]
            own_cost = safe_float(row["own_cost"])
            rows.append(
                (
                    simulation_id,
                    None,
                    seq,
                    row.get("process_type") or item_kind,
                    row["item_name"],
                    row["item_id"],
                    row["item_name"],
                    own_cost if item_kind in {"원재료", "부재료"} else 0.0,
                    own_cost if item_kind == "제품" else 0.0,
                    0.0,
                    0.0,
                    own_cost,
                    safe_float(row["cumulative_cost"]),
                    row.get("formula_text") or "",
                    "",
                    created_at,
                )
            )
        cur.executemany(
            """
            INSERT INTO simulation_lines (
                simulation_id, route_id, seq, process_type, process_name, output_item_id, output_item_name,
                material_cost, process_cost, packaging_cost, moving_cost, own_cost, cumulative_cost, formula_text, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return simulation_id


def update_tree_simulation(
    simulation_id: int,
    product_code: str,
    product_name: str,
    simulation_name: str,
    customer: str,
    notes: str,
    sim_df: pd.DataFrame,
    item_inputs: dict[str, dict],
) -> int:
    created_at = datetime.now().isoformat(timespec="seconds")
    total_cost = safe_float(sim_df.loc[sim_df["node_id"] == "1", "cumulative_cost"].iloc[0]) if not sim_df.empty else 0.0
    daily_hours = derive_header_daily_hours(item_inputs)
    input_state_json = serialize_simulation_inputs(item_inputs)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE simulation_headers
            SET simulation_name = ?, product_code = ?, product_name = ?, customer = ?, daily_hours = ?,
                total_cost = ?, input_state_json = ?, notes = ?, created_at = ?
            WHERE id = ?
            """,
            (simulation_name, product_code, product_name, customer, daily_hours, total_cost, input_state_json, notes, created_at, simulation_id),
        )
        cur.execute("DELETE FROM simulation_lines WHERE simulation_id = ?", (simulation_id,))
        rows = []
        for seq, row in enumerate(sim_df.to_dict("records"), start=1):
            item_kind = row["item_kind"]
            own_cost = safe_float(row["own_cost"])
            rows.append(
                (
                    simulation_id,
                    None,
                    seq,
                    row.get("process_type") or item_kind,
                    row["item_name"],
                    row["item_id"],
                    row["item_name"],
                    own_cost if item_kind in {"원재료", "부재료"} else 0.0,
                    own_cost if item_kind == "제품" else 0.0,
                    0.0,
                    0.0,
                    own_cost,
                    safe_float(row["cumulative_cost"]),
                    row.get("formula_text") or "",
                    "",
                    created_at,
                )
            )
        cur.executemany(
            """
            INSERT INTO simulation_lines (
                simulation_id, route_id, seq, process_type, process_name, output_item_id, output_item_name,
                material_cost, process_cost, packaging_cost, moving_cost, own_cost, cumulative_cost, formula_text, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return simulation_id


def render_product_items_tab() -> None:
    st.subheader("품목 등록")
    if st.session_state.pop("reset_new_product_form", False):
        reset_widget_keys(["new_product_item_id", "new_product_item_name", "new_product_notes"])
    item_ids = get_items()["item_id"].tolist()
    c1, c2 = st.columns(2)
    with c1:
        process_type = st.selectbox("기본 공정", options=[""] + PROCESS_TYPES, key="new_product_process_type")
        suggested_code = next_code_for_prefix(PROCESS_CODE_PREFIXES.get(process_type, "ITEM"), item_ids)
        current_code = st.session_state.get("new_product_item_id", "")
        if not current_code or current_code.startswith(tuple(PROCESS_CODE_PREFIXES.values())) or current_code.startswith("ITEM"):
            st.session_state["new_product_item_id"] = suggested_code
        item_id = st.text_input("코드", key="new_product_item_id")
        item_name = st.text_input("이름", key="new_product_item_name")
    with c2:
        unit = st.selectbox("단위", options=PRODUCT_UNITS, key="new_product_unit")
        notes = st.text_area("비고", height=88, key="new_product_notes")
    if st.button("품목 저장", key="save_new_product_item"):
        execute(
            """
            INSERT OR REPLACE INTO items (
                item_id, item_name, item_kind, sub_kind, process_type, unit, current_price_per_kg, current_unit_price, notes
            ) VALUES (?, ?, '제품', NULL, ?, ?, 0, 0, ?)
            """,
            (item_id, item_name, process_type or None, unit, notes),
        )
        reset_cache()
        st.session_state["reset_new_product_form"] = True
        flash_success("저장했습니다.")
        st.rerun()

    items = get_items()
    product_items = items[items["item_kind"] == "제품"].copy()
    if not product_items.empty:
        st.markdown("---")
        product_items["label"] = product_items.apply(lambda row: f"{row['item_id']} | {row['item_name']}", axis=1)
        selected_label = st.selectbox("수정 품목", options=product_items["label"].tolist(), key="edit_product_label")
        selected = product_items[product_items["label"] == selected_label].iloc[0]
        with st.form("edit_product_form"):
            item_name = st.text_input("이름", value=selected["item_name"])
            process_options = [""] + PROCESS_TYPES
            current_process = selected["process_type"] or ""
            process_type = st.selectbox("기본 공정", options=process_options, index=process_options.index(current_process) if current_process in process_options else 0)
            notes = st.text_area("비고", value=selected["notes"] or "", height=88)
            if st.form_submit_button("수정 저장"):
                execute(
                    "UPDATE items SET item_name = ?, process_type = ?, notes = ? WHERE item_id = ?",
                    (item_name, process_type or None, notes, selected["item_id"]),
                )
                reset_cache()
                st.success("수정했습니다.")
        render_dataframe(product_items[["item_id", "item_name", "process_type", "unit", "notes"]])


def render_material_items_tab() -> None:
    st.subheader("원료 / 부재료")
    if st.session_state.pop("reset_new_material_form", False):
        reset_widget_keys(["new_material_item_id", "new_material_item_name", "new_material_notes", "new_material_price_per_kg", "new_material_unit_price"])
    item_ids = get_items()["item_id"].tolist()
    c1, c2 = st.columns(2)
    with c1:
        sub_kind = st.selectbox("구분", options=MATERIAL_SUBKINDS, key="new_material_sub_kind")
        suggested_code = next_code_for_prefix(MATERIAL_SUBKIND_PREFIXES[sub_kind], item_ids)
        current_code = st.session_state.get("new_material_item_id", "")
        if not current_code or current_code.startswith(tuple(MATERIAL_SUBKIND_PREFIXES.values())):
            st.session_state["new_material_item_id"] = suggested_code
        item_id = st.text_input("코드", key="new_material_item_id")
        item_name = st.text_input("이름", key="new_material_item_name")
        unit = st.selectbox("단위", options=MATERIAL_UNITS, key="new_material_unit")
    with c2:
        price_per_kg = st.number_input("kg당 단가", min_value=0.0, step=1.0, key="new_material_price_per_kg")
        unit_price = st.number_input("개당 단가", min_value=0.0, step=1.0, key="new_material_unit_price")
        notes = st.text_area("비고", height=88, key="new_material_notes")
    item_kind = "원재료" if sub_kind in {"원료", "MB"} else "부재료"
    if st.button("재료 저장", key="save_new_material_item"):
        execute(
            """
            INSERT OR REPLACE INTO items (
                item_id, item_name, item_kind, sub_kind, process_type, unit, current_price_per_kg, current_unit_price, notes
            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (item_id, item_name, item_kind, sub_kind, unit, price_per_kg, unit_price, notes),
        )
        reset_cache()
        st.session_state["reset_new_material_form"] = True
        flash_success("저장했습니다.")
        st.rerun()

    items = get_items()
    material_items = items[items["item_kind"].isin(["원재료", "부재료"])].copy()
    if not material_items.empty:
        st.markdown("---")
        material_items["label"] = material_items.apply(lambda row: f"{row['item_id']} | {row['item_name']}", axis=1)
        selected_label = st.selectbox("수정 재료", options=material_items["label"].tolist(), key="edit_material_label")
        selected = material_items[material_items["label"] == selected_label].iloc[0]
        with st.form("edit_material_form"):
            item_name = st.text_input("이름", value=selected["item_name"])
            current_sub_kind = selected["sub_kind"] if selected["sub_kind"] in MATERIAL_SUBKINDS else ("원료" if selected["item_kind"] == "원재료" else "기타")
            sub_kind = st.selectbox("구분", options=MATERIAL_SUBKINDS, index=MATERIAL_SUBKINDS.index(current_sub_kind))
            unit = st.selectbox("단위", options=MATERIAL_UNITS, index=MATERIAL_UNITS.index(selected["unit"]) if selected["unit"] in MATERIAL_UNITS else 0)
            price_per_kg = st.number_input("kg당 단가", min_value=0.0, value=safe_float(selected["current_price_per_kg"]), step=1.0)
            unit_price = st.number_input("개당 단가", min_value=0.0, value=safe_float(selected["current_unit_price"]), step=1.0)
            notes = st.text_area("비고", value=selected["notes"] or "", height=88)
            if st.form_submit_button("수정 저장"):
                item_kind = "원재료" if sub_kind in {"원료", "MB"} else "부재료"
                execute(
                    """
                    UPDATE items
                    SET item_name = ?, item_kind = ?, sub_kind = ?, unit = ?, current_price_per_kg = ?, current_unit_price = ?, notes = ?
                    WHERE item_id = ?
                    """,
                    (item_name, item_kind, sub_kind, unit, price_per_kg, unit_price, notes, selected["item_id"]),
                )
                reset_cache()
                st.success("수정했습니다.")
        render_dataframe(material_items[["item_id", "item_name", "item_kind", "sub_kind", "unit", "current_price_per_kg", "current_unit_price"]])


def render_products_tab() -> None:
    st.subheader("상품")
    product_items = get_items()
    product_items = product_items[product_items["item_kind"] == "제품"].copy()
    if product_items.empty:
        st.info("먼저 제품을 등록하세요.")
        return
    product_options = product_items.apply(lambda row: f"{row['item_id']} | {row['item_name']}", axis=1).tolist()
    with st.form("product_form"):
        product_code = st.text_input("상품 코드")
        product_name = st.text_input("상품명")
        result_item_label = st.selectbox("대응 제품", options=product_options)
        notes = st.text_area("비고", height=88)
        if st.form_submit_button("저장"):
            execute(
                "INSERT OR REPLACE INTO products (product_code, product_name, result_item_id, notes) VALUES (?, ?, ?, ?)",
                (product_code, product_name, result_item_label.split(" | ")[0], notes),
            )
            reset_cache()
            flash_success("저장했습니다.")
    products = get_products()
    if not products.empty:
        render_dataframe(products[["product_code", "product_name", "result_item_id", "notes"]])


def render_rates_tab() -> None:
    st.subheader("사출 임률")
    with st.form("rate_form"):
        resource_code = st.text_input("코드")
        resource_name = st.text_input("이름")
        daily_rate = st.number_input("일 임률", min_value=0.0, step=1000.0)
        if st.form_submit_button("저장"):
            execute(
                "INSERT OR REPLACE INTO resource_rates (resource_code, resource_name, daily_rate) VALUES (?, ?, ?)",
                (resource_code, resource_name, daily_rate),
            )
            reset_cache()
            flash_success("저장했습니다.")
    rates = get_resource_rates()
    if not rates.empty:
        render_dataframe(rates)


def render_item_bom_tab() -> None:
    st.subheader("제품 BOM")
    items = get_items()
    product_items = items[items["item_kind"] == "제품"].copy()
    if product_items.empty:
        st.info("먼저 제품을 등록하세요.")
        return
    item_options = product_items.apply(lambda row: f"{row['item_id']} | {row['item_name']}", axis=1).tolist()
    with st.form("item_bom_form"):
        parent_label = st.selectbox("부모 제품", options=item_options)
        child_label = st.selectbox("하위 제품", options=item_options)
        quantity = st.number_input("수량", min_value=0.0, value=1.0, step=1.0)
        quantity_unit = st.selectbox("수량 단위", options=QTY_UNITS)
        notes = st.text_input("비고")
        if st.form_submit_button("저장"):
            parent_item_id = parent_label.split(" | ")[0]
            child_item_id = child_label.split(" | ")[0]
            if would_create_bom_cycle(parent_item_id, child_item_id):
                st.error("순환 BOM이 되므로 저장할 수 없습니다.")
                return
            execute(
                "INSERT OR REPLACE INTO item_bom (parent_item_id, child_item_id, quantity, quantity_unit, notes) VALUES (?, ?, ?, ?, ?)",
                (parent_item_id, child_item_id, quantity, quantity_unit, notes),
            )
            reset_cache()
            flash_success("저장했습니다.")
    bom_df = get_item_bom()
    if not bom_df.empty:
        render_dataframe(bom_df[["parent_item_id", "child_item_id", "quantity", "quantity_unit", "notes"]])


def render_master_tab() -> None:
    submenu = st.sidebar.radio("기초정보", ["품목 등록", "원료 / 부재료", "상품", "사출 임률", "제품 BOM"], key="master_submenu")
    if submenu == "품목 등록":
        render_product_items_tab()
    elif submenu == "원료 / 부재료":
        render_material_items_tab()
    elif submenu == "상품":
        render_products_tab()
    elif submenu == "사출 임률":
        render_rates_tab()
    else:
        render_item_bom_tab()


def render_bom_item_form(
    selected_row: dict,
    tree_df: pd.DataFrame | None = None,
    bom_inputs: dict[str, dict] | None = None,
    state_prefix: str = "simulation",
    read_only: bool = False,
) -> None:
    tree_df = tree_df if tree_df is not None else st.session_state["simulation_tree_df"]
    current_inputs = bom_inputs if bom_inputs is not None else st.session_state.get("bom_inputs")
    normalized_inputs = normalize_bom_inputs(tree_df, current_inputs)
    item_input = normalized_inputs[selected_row["node_id"]]
    if not read_only:
        st.session_state["bom_inputs"][selected_row["node_id"]] = item_input

    if selected_row["item_kind"] == "제품":
        process_type = item_input["process_type"] if item_input["process_type"] in PROCESS_TYPES else ""
        general_col, process_col, material_col = st.columns(3, gap="large")
        with general_col:
            st.markdown("**일반**")
            sync_simulation_widget(selected_row["node_id"], "packaging_cost", safe_float(item_input["packaging_cost"]), prefix=state_prefix)
            packaging_cost = st.number_input(
                "포장비",
                min_value=0.0,
                step=1.0,
                key=simulation_widget_key(selected_row["node_id"], "packaging_cost", prefix=state_prefix),
                disabled=read_only,
            )
            sync_simulation_widget(selected_row["node_id"], "moving_cost", safe_float(item_input["moving_cost"]), prefix=state_prefix)
            moving_cost = st.number_input(
                "이동비",
                min_value=0.0,
                step=1.0,
                key=simulation_widget_key(selected_row["node_id"], "moving_cost", prefix=state_prefix),
                disabled=read_only,
            )
            management_rate_pct = min(99.99, max(0.0, safe_float(item_input.get("management_rate_pct"))))
            defect_rate_pct = min(99.99, max(0.0, safe_float(item_input.get("defect_rate_pct"))))
            sync_simulation_widget(selected_row["node_id"], "management_rate_pct", management_rate_pct, prefix=state_prefix)
            management_rate_pct = st.number_input(
                "관리비(%)",
                min_value=0.0,
                max_value=99.99,
                step=0.1,
                key=simulation_widget_key(selected_row["node_id"], "management_rate_pct", prefix=state_prefix),
                disabled=read_only,
            )
            sync_simulation_widget(selected_row["node_id"], "defect_rate_pct", defect_rate_pct, prefix=state_prefix)
            defect_rate_pct = st.number_input(
                "불량률(%)",
                min_value=0.0,
                max_value=99.99,
                step=0.1,
                key=simulation_widget_key(selected_row["node_id"], "defect_rate_pct", prefix=state_prefix),
                disabled=read_only,
            )
            sync_simulation_widget(selected_row["node_id"], "notes", item_input.get("notes", ""), prefix=state_prefix)
            notes = st.text_area(
                "비고",
                height=90,
                key=simulation_widget_key(selected_row["node_id"], "notes", prefix=state_prefix),
                disabled=read_only,
            )
        with process_col:
            st.markdown("**공정**")
            resource_code = item_input["resource_code"]
            daily_hours = max(1.0, safe_float(item_input.get("daily_hours")) or DEFAULT_DAILY_HOURS)
            daily_rate = safe_float(item_input["daily_rate"])
            ct_sec = safe_float(item_input["ct_sec"])
            cavity = max(1.0, safe_float(item_input["cavity"]) or 1.0)
            weight_g = safe_float(item_input["weight_g"])
            sprue_weight_g = safe_float(item_input.get("sprue_weight_g"))
            process_cost = safe_float(item_input["process_cost"])
            raw_material_1 = item_input["raw_material_1"]
            raw_material_1_pct = safe_float(item_input["raw_material_1_pct"])
            raw_material_1_price = safe_float(item_input["raw_material_1_price"])
            mb_code = item_input.get("mb_code", "")
            mb_ratio_pct = safe_float(item_input.get("mb_ratio_pct"))
            mb_price = safe_float(item_input.get("mb_price"))
            raw_material_2 = item_input["raw_material_2"]
            raw_material_2_pct = safe_float(item_input["raw_material_2_pct"])
            raw_material_2_price = safe_float(item_input["raw_material_2_price"])
            raw_material_3 = item_input["raw_material_3"]
            raw_material_3_pct = safe_float(item_input["raw_material_3_pct"])
            raw_material_3_price = safe_float(item_input["raw_material_3_price"])
            assembly_material_1 = item_input["assembly_material_1"]
            assembly_material_1_qty = safe_float(item_input["assembly_material_1_qty"])
            assembly_material_2 = item_input["assembly_material_2"]
            assembly_material_2_qty = safe_float(item_input["assembly_material_2_qty"])
            preview_lines: list[str] = []

            if process_type == "사출":
                rates = get_resource_rates()
                rate_options = [""] + rates["resource_code"].tolist()
                material_items = get_items()
                material_items = material_items[material_items["item_kind"].isin(["원재료", "부재료"])].copy()
                material_items["label"] = material_items.apply(lambda row: f"{row['item_name']} ({row['item_id']})", axis=1)
                label_to_id = dict(zip(material_items["label"], material_items["item_id"]))
                raw_options = [""] + material_items["label"].tolist()

                c1, c2 = st.columns(2)
                with c1:
                    sync_simulation_widget(selected_row["node_id"], "resource_code", item_input["resource_code"], prefix=state_prefix)
                    resource_code = st.selectbox("톤수 코드", options=rate_options, key=simulation_widget_key(selected_row["node_id"], "resource_code", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "daily_rate", safe_float(item_input["daily_rate"]), prefix=state_prefix)
                    daily_rate = st.number_input("일 임률", min_value=0.0, step=1000.0, key=simulation_widget_key(selected_row["node_id"], "daily_rate", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "daily_hours", daily_hours, prefix=state_prefix)
                    daily_hours = st.number_input("일 가동시간", min_value=1.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "daily_hours", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "ct_sec", safe_float(item_input["ct_sec"]), prefix=state_prefix)
                    ct_sec = st.number_input("CT(초)", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "ct_sec", prefix=state_prefix), disabled=read_only)
                with c2:
                    sync_simulation_widget(selected_row["node_id"], "cavity", cavity, prefix=state_prefix)
                    cavity = st.number_input("Cavity", min_value=1.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "cavity", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "weight_g", weight_g, prefix=state_prefix)
                    weight_g = st.number_input("제품무게(g)", min_value=0.0, step=0.01, key=simulation_widget_key(selected_row["node_id"], "weight_g", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "sprue_weight_g", safe_float(item_input.get("sprue_weight_g")), prefix=state_prefix)
                    sprue_weight_g = st.number_input(
                        "스프루무게(g)",
                        min_value=0.0,
                        step=0.01,
                        key=simulation_widget_key(selected_row["node_id"], "sprue_weight_g", prefix=state_prefix),
                        disabled=read_only,
                    )

                if resource_code and safe_float(daily_rate) <= 0:
                    rate_match = rates[rates["resource_code"] == resource_code]
                    if not rate_match.empty:
                        daily_rate = safe_float(rate_match.iloc[0]["daily_rate"])
                if daily_rate > 0 and ct_sec > 0:
                    unit_process_cost = daily_rate / ((daily_hours * 3600.0 / ct_sec) * cavity)
                    preview_lines.append(f"가공비: {daily_rate:,.2f} / ((({daily_hours:,.2f} x 3600) / {ct_sec:,.2f}) x {cavity:,.2f}) = {unit_process_cost:,.2f}")

            elif process_type == "조립":
                sync_simulation_widget(selected_row["node_id"], "process_cost", process_cost, prefix=state_prefix)
                process_cost = st.number_input("공정단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "process_cost", prefix=state_prefix), disabled=read_only)
                preview_lines.append(f"가공비: 공정단가 {process_cost:,.2f}")
            else:
                sync_simulation_widget(selected_row["node_id"], "process_cost", process_cost, prefix=state_prefix)
                process_cost = st.number_input("공정단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "process_cost", prefix=state_prefix), disabled=read_only)
                preview_lines.append(f"가공비: 공정단가 {process_cost:,.2f}")

            preview_material_cost = 0.0
            if process_type == "사출":
                formulas = []
                material_weight_g = weight_g + (sprue_weight_g / cavity)
                for material_id, pct, price_per_kg in [
                    (raw_material_1, raw_material_1_pct, raw_material_1_price),
                    (raw_material_2, raw_material_2_pct, raw_material_2_price),
                    (raw_material_3, raw_material_3_pct, raw_material_3_price),
                ]:
                    if not material_id or pct <= 0:
                        continue
                    component = (material_weight_g / 1000.0) * (pct / 100.0) * price_per_kg
                    preview_material_cost += component
                    formulas.append(
                        f"{material_id} = (({weight_g:,.3f}g + ({sprue_weight_g:,.3f}g / {cavity:,.2f})) / 1000) x ({pct:,.2f} / 100) x {price_per_kg:,.2f}"
                    )
                if mb_code and mb_ratio_pct > 0:
                    component = (material_weight_g / 1000.0) * (mb_ratio_pct / 100.0) * mb_price
                    preview_material_cost += component
                    formulas.append(
                        f"{mb_code} = (({weight_g:,.3f}g + ({sprue_weight_g:,.3f}g / {cavity:,.2f})) / 1000) x ({mb_ratio_pct:,.2f} / 100) x {mb_price:,.2f}"
                    )
                preview_lines.insert(0, ("재료비:\n" + "\n".join(formulas) + f"\n합계 = {preview_material_cost:,.2f}") if formulas else "재료비:\n합계 = 0")
            elif process_type == "조립":
                materials = {row["item_id"]: row.to_dict() for _, row in get_items().iterrows()}
                if assembly_material_1 and assembly_material_1_qty > 0:
                    preview_material_cost += assembly_material_1_qty * safe_float(materials.get(assembly_material_1, {}).get("current_unit_price"))
                if assembly_material_2 and assembly_material_2_qty > 0:
                    preview_material_cost += assembly_material_2_qty * safe_float(materials.get(assembly_material_2, {}).get("current_unit_price"))
        if process_type == "사출":
            preview_own_cost = preview_material_cost + process_cost
            preview_management_cost = 0.0
            preview_defect_cost = 0.0
        else:
            preview_management_cost = 0.0
            preview_defect_cost = 0.0

        with material_col:
            st.markdown("**원료**")
            if process_type == "사출":
                top_left, top_right = st.columns(2, gap="medium")
                with top_left:
                    sync_simulation_widget(selected_row["node_id"], "raw_material_1_label", next((label for label, iid in label_to_id.items() if iid == raw_material_1), ""), prefix=state_prefix)
                    raw1_label = st.selectbox("원료1", options=raw_options, key=simulation_widget_key(selected_row["node_id"], "raw_material_1_label", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "raw_material_1_pct", raw_material_1_pct, prefix=state_prefix)
                    raw_material_1_pct = st.number_input("원료1 %", min_value=0.0, step=0.1, key=simulation_widget_key(selected_row["node_id"], "raw_material_1_pct", prefix=state_prefix), disabled=read_only)
                    raw_material_1 = label_to_id.get(raw1_label, "")
                    if raw_material_1:
                        base_price = safe_float(material_items[material_items["item_id"] == raw_material_1].iloc[0]["current_price_per_kg"])
                        sync_simulation_widget(selected_row["node_id"], "raw_material_1_price", safe_float(item_input.get("raw_material_1_price")) or base_price, prefix=state_prefix)
                    raw_material_1_price = st.number_input("원료1 kg단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "raw_material_1_price", prefix=state_prefix), disabled=read_only)
                with top_right:
                    sync_simulation_widget(selected_row["node_id"], "mb_code", mb_code, prefix=state_prefix)
                    mb_code = st.text_input("MB 코드", key=simulation_widget_key(selected_row["node_id"], "mb_code", prefix=state_prefix), disabled=True)
                    sync_simulation_widget(selected_row["node_id"], "mb_ratio_pct", mb_ratio_pct, prefix=state_prefix)
                    mb_ratio_pct = st.number_input("MB %", min_value=0.0, step=0.1, key=simulation_widget_key(selected_row["node_id"], "mb_ratio_pct", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "mb_price", mb_price, prefix=state_prefix)
                    mb_price = st.number_input("MB kg단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "mb_price", prefix=state_prefix), disabled=read_only)

                bottom_left, bottom_right = st.columns(2, gap="medium")
                with bottom_left:
                    sync_simulation_widget(selected_row["node_id"], "raw_material_2_label", next((label for label, iid in label_to_id.items() if iid == raw_material_2), ""), prefix=state_prefix)
                    raw2_label = st.selectbox("원료2", options=raw_options, key=simulation_widget_key(selected_row["node_id"], "raw_material_2_label", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "raw_material_2_pct", raw_material_2_pct, prefix=state_prefix)
                    raw_material_2_pct = st.number_input("원료2 %", min_value=0.0, step=0.1, key=simulation_widget_key(selected_row["node_id"], "raw_material_2_pct", prefix=state_prefix), disabled=read_only)
                    raw_material_2 = label_to_id.get(raw2_label, "")
                    if raw_material_2:
                        base_price = safe_float(material_items[material_items["item_id"] == raw_material_2].iloc[0]["current_price_per_kg"])
                        sync_simulation_widget(selected_row["node_id"], "raw_material_2_price", safe_float(item_input.get("raw_material_2_price")) or base_price, prefix=state_prefix)
                    raw_material_2_price = st.number_input("원료2 kg단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "raw_material_2_price", prefix=state_prefix), disabled=read_only)
                with bottom_right:
                    sync_simulation_widget(selected_row["node_id"], "raw_material_3_label", next((label for label, iid in label_to_id.items() if iid == raw_material_3), ""), prefix=state_prefix)
                    raw3_label = st.selectbox("원료3", options=raw_options, key=simulation_widget_key(selected_row["node_id"], "raw_material_3_label", prefix=state_prefix), disabled=read_only)
                    sync_simulation_widget(selected_row["node_id"], "raw_material_3_pct", raw_material_3_pct, prefix=state_prefix)
                    raw_material_3_pct = st.number_input("원료3 %", min_value=0.0, step=0.1, key=simulation_widget_key(selected_row["node_id"], "raw_material_3_pct", prefix=state_prefix), disabled=read_only)
                    raw_material_3 = label_to_id.get(raw3_label, "")
                    if raw_material_3:
                        base_price = safe_float(material_items[material_items["item_id"] == raw_material_3].iloc[0]["current_price_per_kg"])
                        sync_simulation_widget(selected_row["node_id"], "raw_material_3_price", safe_float(item_input.get("raw_material_3_price")) or base_price, prefix=state_prefix)
                    raw_material_3_price = st.number_input("원료3 kg단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "raw_material_3_price", prefix=state_prefix), disabled=read_only)
            elif process_type == "조립":
                st.markdown("**부재료**")
                materials = get_items()
                materials = materials[materials["item_kind"] == "부재료"].copy()
                materials["label"] = materials.apply(lambda row: f"{row['item_name']} ({row['item_id']})", axis=1)
                label_to_id = dict(zip(materials["label"], materials["item_id"]))
                options = [""] + materials["label"].tolist()
                sync_simulation_widget(selected_row["node_id"], "assembly_material_1_label", next((label for label, iid in label_to_id.items() if iid == assembly_material_1), ""), prefix=state_prefix)
                assembly1_label = st.selectbox("부재료1", options=options, key=simulation_widget_key(selected_row["node_id"], "assembly_material_1_label", prefix=state_prefix), disabled=read_only)
                sync_simulation_widget(selected_row["node_id"], "assembly_material_1_qty", assembly_material_1_qty, prefix=state_prefix)
                assembly_material_1_qty = st.number_input("부재료1 수량", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "assembly_material_1_qty", prefix=state_prefix), disabled=read_only)
                sync_simulation_widget(selected_row["node_id"], "assembly_material_2_label", next((label for label, iid in label_to_id.items() if iid == assembly_material_2), ""), prefix=state_prefix)
                assembly2_label = st.selectbox("부재료2", options=options, key=simulation_widget_key(selected_row["node_id"], "assembly_material_2_label", prefix=state_prefix), disabled=read_only)
                sync_simulation_widget(selected_row["node_id"], "assembly_material_2_qty", assembly_material_2_qty, prefix=state_prefix)
                assembly_material_2_qty = st.number_input("부재료2 수량", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "assembly_material_2_qty", prefix=state_prefix), disabled=read_only)
                assembly_material_1 = label_to_id.get(assembly1_label, "")
                assembly_material_2 = label_to_id.get(assembly2_label, "")
            else:
                st.caption("원료 입력 없음")

        updated_values = {
            "process_type": process_type,
            "daily_hours": daily_hours,
            "resource_code": resource_code,
            "daily_rate": daily_rate,
            "ct_sec": ct_sec,
            "cavity": cavity,
            "weight_g": weight_g,
            "sprue_weight_g": sprue_weight_g,
            "process_cost": process_cost,
            "packaging_cost": packaging_cost,
            "moving_cost": moving_cost,
            "management_rate_pct": management_rate_pct,
            "defect_rate_pct": defect_rate_pct,
            "raw_material_1": raw_material_1,
            "raw_material_1_pct": raw_material_1_pct,
            "raw_material_1_price": raw_material_1_price,
            "mb_code": mb_code,
            "mb_ratio_pct": mb_ratio_pct,
            "mb_price": mb_price,
            "raw_material_2": raw_material_2,
            "raw_material_2_pct": raw_material_2_pct,
            "raw_material_2_price": raw_material_2_price,
            "raw_material_3": raw_material_3,
            "raw_material_3_pct": raw_material_3_pct,
            "raw_material_3_price": raw_material_3_price,
            "assembly_material_1": assembly_material_1,
            "assembly_material_1_qty": assembly_material_1_qty,
            "assembly_material_2": assembly_material_2,
            "assembly_material_2_qty": assembly_material_2_qty,
            "notes": notes,
        }

        preview_inputs = {node: values.copy() for node, values in normalized_inputs.items()}
        preview_inputs[selected_row["node_id"]] = {**preview_inputs[selected_row["node_id"]], **updated_values}
        preview_sim_df = build_bom_simulation(tree_df, preview_inputs)
        preview_row = preview_sim_df[preview_sim_df["node_id"] == selected_row["node_id"]].iloc[0]
        child_total_preview = safe_float(
            preview_sim_df.loc[preview_sim_df["parent_node_id"] == selected_row["node_id"], "cumulative_cost"].sum()
        )
        own_cost_preview = safe_float(preview_row["own_cost"])
        cumulative_preview = safe_float(preview_row["cumulative_cost"])
        preview_process_cost = process_cost
        preview_own_cost = own_cost_preview
        preview_management_cost = 0.0
        preview_defect_cost = 0.0

        if process_type == "사출" and daily_rate > 0 and ct_sec > 0 and cavity > 0:
            preview_process_cost = daily_rate / ((daily_hours * 3600.0 / ct_sec) * cavity)
            preview_own_cost = preview_material_cost + preview_process_cost
            preview_management_cost = 0.0
            preview_defect_cost = 0.0
            cumulative_preview = preview_own_cost
        elif process_type == "조립":
            preview_process_cost = process_cost
            preview_own_cost = preview_material_cost + preview_process_cost
            preview_management_cost = preview_own_cost * (management_rate_pct / 100.0)
            preview_defect_cost = preview_own_cost * (defect_rate_pct / 100.0)
            cumulative_preview = child_total_preview + preview_own_cost + preview_management_cost + preview_defect_cost + packaging_cost + moving_cost
        else:
            preview_process_cost = process_cost
            preview_own_cost = preview_process_cost
            preview_management_cost = preview_own_cost * (management_rate_pct / 100.0)
            preview_defect_cost = preview_own_cost * (defect_rate_pct / 100.0)
            cumulative_preview = child_total_preview + preview_own_cost + preview_management_cost + preview_defect_cost + packaging_cost + moving_cost

        if process_type == "사출":
            formula_material = preview_lines[0] if preview_lines else "재료비: 0"
            formula_process = preview_lines[1] if len(preview_lines) > 1 else f"가공비: {preview_process_cost:,.2f}"
            formula_own = f"재료비 {preview_material_cost:,.2f} + 가공비 {preview_process_cost:,.2f} = {preview_own_cost:,.2f}"
            formula_cumulative = f"사출은 공정단가 = 누적단가 = {cumulative_preview:,.2f}"
        elif process_type == "조립":
            formula_material = f"부재료비 = {preview_material_cost:,.2f}"
            formula_process = preview_lines[0] if preview_lines else f"가공비: 공정단가 {preview_process_cost:,.2f}"
            formula_own = f"부재료비 {preview_material_cost:,.2f} + 가공비 {preview_process_cost:,.2f} = {preview_own_cost:,.2f}"
            formula_cumulative = (
                f"하위누적단가 {child_total_preview:,.2f} + 공정단가 {preview_own_cost:,.2f} + 관리비 {preview_management_cost:,.2f} + "
                f"불량비용 {preview_defect_cost:,.2f} + 이동비 {moving_cost:,.2f} + 포장비 {packaging_cost:,.2f} = {cumulative_preview:,.2f}"
            )
        else:
            formula_material = f"재료비: 하위 child 합계 = {child_total_preview:,.2f}"
            formula_process = preview_lines[0] if preview_lines else f"가공비: 공정단가 {preview_process_cost:,.2f}"
            formula_own = f"공정단가 = 가공비 {preview_process_cost:,.2f}"
            formula_cumulative = (
                f"하위누적단가 {child_total_preview:,.2f} + 공정단가 {preview_own_cost:,.2f} + 관리비 {preview_management_cost:,.2f} + "
                f"불량비용 {preview_defect_cost:,.2f} + 이동비 {moving_cost:,.2f} + 포장비 {packaging_cost:,.2f} = {cumulative_preview:,.2f}"
            )

        st.markdown("**계산식 확인**")
        formula_c1, formula_c2 = st.columns(2, gap="large")
        with formula_c1:
            st.text_area("재료비", value=formula_material, height=72, disabled=True, key=f"{state_prefix}_{selected_row['node_id']}_formula_material")
            st.text_area("공정단가", value=formula_own, height=88, disabled=True, key=f"{state_prefix}_{selected_row['node_id']}_formula_own")
        with formula_c2:
            st.text_area("가공비", value=formula_process, height=72, disabled=True, key=f"{state_prefix}_{selected_row['node_id']}_formula_process")
            st.text_area("누적단가", value=formula_cumulative, height=88, disabled=True, key=f"{state_prefix}_{selected_row['node_id']}_formula_cumulative")

        if not read_only:
            if any(item_input.get(key) != value for key, value in updated_values.items()):
                st.session_state["bom_inputs"][selected_row["node_id"]].update(updated_values)
                st.rerun()
    else:
        general_col, process_col = st.columns(2, gap="large")
        with general_col:
            st.markdown("**일반**")
            sync_simulation_widget(selected_row["node_id"], "quantity", safe_float(item_input["quantity"]), prefix=state_prefix)
            quantity = st.number_input("수량", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "quantity", prefix=state_prefix), disabled=read_only)
            sync_simulation_widget(selected_row["node_id"], "quantity_unit", item_input["quantity_unit"], prefix=state_prefix)
            quantity_unit = st.selectbox("수량 단위", options=QTY_UNITS, key=simulation_widget_key(selected_row["node_id"], "quantity_unit", prefix=state_prefix), disabled=read_only)
            sync_simulation_widget(selected_row["node_id"], "notes", item_input.get("notes", ""), prefix=state_prefix)
            notes = st.text_area("비고", height=90, key=simulation_widget_key(selected_row["node_id"], "notes", prefix=state_prefix), disabled=read_only)
        with process_col:
            st.markdown("**공정**")
            if quantity_unit in {"g", "percent"}:
                sync_simulation_widget(selected_row["node_id"], "price_per_kg", safe_float(item_input["price_per_kg"]), prefix=state_prefix)
                price_per_kg = st.number_input("kg당 단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "price_per_kg", prefix=state_prefix), disabled=read_only)
                unit_price = safe_float(item_input["unit_price"])
            else:
                sync_simulation_widget(selected_row["node_id"], "unit_price", safe_float(item_input["unit_price"]), prefix=state_prefix)
                unit_price = st.number_input("개당 단가", min_value=0.0, step=1.0, key=simulation_widget_key(selected_row["node_id"], "unit_price", prefix=state_prefix), disabled=read_only)
                price_per_kg = safe_float(item_input["price_per_kg"])
        if quantity_unit == "g":
            st.text(f"재료비: ({quantity:,.2f}g / 1000) x {price_per_kg:,.2f}")
        elif quantity_unit == "percent":
            st.text(f"재료비: 상위 제품무게 기준 {quantity:,.2f}% x {price_per_kg:,.2f}")
        else:
            st.text(f"재료비: {quantity:,.2f} x {unit_price:,.2f}")
        if not read_only:
            updated_values = {
                "quantity": quantity,
                "quantity_unit": quantity_unit,
                "price_per_kg": price_per_kg,
                "unit_price": unit_price,
                "notes": notes,
            }
            if any(item_input.get(key) != value for key, value in updated_values.items()):
                st.session_state["bom_inputs"][selected_row["node_id"]].update(updated_values)
                st.rerun()


def render_simulation_tab() -> None:
    products = get_products()
    if products.empty:
        st.info("먼저 프로젝트와 제품구성을 등록하세요.")
        return

    products["label"] = products.apply(lambda row: f"{row['product_code']} | {row['product_name']}", axis=1)
    product_labels = products["label"].tolist()
    if "simulation_product_label" not in st.session_state or st.session_state["simulation_product_label"] not in product_labels:
        st.session_state["simulation_product_label"] = product_labels[0]
    selected_label = st.sidebar.selectbox("프로젝트 / 상품 선택", options=product_labels, key="simulation_product_label")
    selected_product = products[products["label"] == selected_label].iloc[0]
    product_code = selected_product["product_code"]
    root_item_id = selected_product["result_item_id"]
    st.sidebar.markdown("**선택 정보**")
    st.sidebar.caption(f"프로젝트: {selected_product.get('project_code', '-') or '-'}")
    st.sidebar.caption(f"프로젝트명: {selected_product.get('project_name', '-') or '-'}")
    st.sidebar.caption(f"상품: {selected_product['product_code']} | {selected_product['product_name']}")
    linked_item_code = selected_product["result_item_code"] if "result_item_code" in selected_product.index else root_item_id
    st.sidebar.caption(f"연결 공정품: {linked_item_code or '-'} | {selected_product['result_item_name'] or '-'}")

    if st.session_state.get("loaded_product_code") != product_code:
        st.session_state["loaded_product_code"] = product_code
        st.session_state["loaded_simulation_id"] = None
        st.session_state["simulation_force_widget_sync"] = True

    headers, options = build_history_options_for_product(product_code)
    history_key = f"simulation_history_{product_code}"
    if history_key not in st.session_state or st.session_state[history_key] not in options:
        st.session_state[history_key] = "새 시뮬레이션"
    main_history_key = f"main_{history_key}"
    if main_history_key not in st.session_state or st.session_state[main_history_key] not in options:
        st.session_state[main_history_key] = st.session_state[history_key]

    top_c1, top_c2 = st.columns([1.3, 1], gap="large")
    with top_c1:
        selected_history_label = st.selectbox("시뮬레이션 이력", options=options, key=main_history_key)
    if selected_history_label != st.session_state.get(history_key):
        st.session_state[history_key] = selected_history_label
        st.rerun()

    selected_history = None
    if selected_history_label != "새 시뮬레이션":
        selected_history = headers[headers["label"] == selected_history_label].iloc[0]
    selected_history_id = int(selected_history["id"]) if selected_history is not None else None

    current_loaded_id = st.session_state.get("loaded_simulation_id")
    current_product_code = st.session_state.get("simulation_product_code")
    if current_product_code != product_code:
        tree_df = load_product_tree_or_error(root_item_id)
        if tree_df is None:
            return
        st.session_state["loaded_simulation_id"] = None
        st.session_state["simulation_product_code"] = product_code
        st.session_state["simulation_tree_df"] = tree_df
        st.session_state["bom_inputs"] = build_default_item_inputs(tree_df)
        st.session_state["simulation_force_widget_sync"] = True
        st.rerun()
    if selected_history_id is None and current_loaded_id is not None:
        tree_df = load_product_tree_or_error(root_item_id)
        if tree_df is None:
            return
        st.session_state["loaded_simulation_id"] = None
        st.session_state["simulation_tree_df"] = tree_df
        st.session_state["bom_inputs"] = build_default_item_inputs(tree_df)
        st.session_state["simulation_force_widget_sync"] = True
        st.rerun()
    elif selected_history_id is not None and current_loaded_id != selected_history_id:
        tree_df = load_product_tree_or_error(root_item_id)
        if tree_df is None:
            return
        st.session_state["loaded_simulation_id"] = selected_history_id
        st.session_state["simulation_tree_df"] = tree_df
        st.session_state["bom_inputs"] = normalize_bom_inputs(tree_df, load_saved_simulation_inputs(selected_history_id))
        st.session_state["simulation_force_widget_sync"] = True
        st.rerun()

    tree_df = st.session_state.get("simulation_tree_df")
    if tree_df is None:
        tree_df = load_product_tree_or_error(root_item_id)
        if tree_df is None:
            return
        st.session_state["simulation_tree_df"] = tree_df
        st.session_state["bom_inputs"] = build_default_item_inputs(tree_df)
        st.session_state["simulation_force_widget_sync"] = True
        st.rerun()

    st.session_state["bom_inputs"] = normalize_bom_inputs(tree_df, st.session_state.get("bom_inputs"))
    sim_df = build_bom_simulation(tree_df, st.session_state["bom_inputs"])
    total_cost = safe_float(sim_df.loc[sim_df["node_id"] == "1", "cumulative_cost"].iloc[0]) if not sim_df.empty else 0.0
    with top_c2:
        st.metric("총 누적단가", f"{total_cost:,.2f}")

    selected_tree_row = render_simulation_summary_panel(
        tree_df=tree_df,
        item_inputs=st.session_state["bom_inputs"],
        selected_item_key="simulation_selected_tree_label",
        product_label="",
    )

    st.markdown("---")
    render_bom_item_form(selected_tree_row)
    st.session_state["simulation_force_widget_sync"] = False
    save_mode = st.radio("저장 방식", ["수정", "새로 만들기"], horizontal=True) if selected_history is not None else "새로 만들기"
    save_label = "시뮬레이션 수정 저장" if selected_history is not None and save_mode == "수정" else "시뮬레이션 저장"
    if st.button(save_label):
        customer = selected_product.get("project_name", "") or ""
        simulation_name = selected_history["simulation_name"] if selected_history is not None and save_mode == "수정" else f"{selected_product['product_code']} 원가시뮬레이션"
        notes = ""
        if selected_history is not None and save_mode == "수정":
            simulation_id = update_tree_simulation(
                simulation_id=int(selected_history["id"]),
                product_code=selected_product["product_code"],
                product_name=selected_product["product_name"],
                simulation_name=simulation_name,
                customer=customer,
                notes=notes,
                sim_df=sim_df,
                item_inputs=st.session_state["bom_inputs"],
            )
        else:
            simulation_id = save_tree_simulation(
                product_code=selected_product["product_code"],
                product_name=selected_product["product_name"],
                simulation_name=simulation_name,
                customer=customer,
                notes=notes,
                sim_df=sim_df,
                item_inputs=st.session_state["bom_inputs"],
            )
        flash_success(f"저장했습니다. ID: {simulation_id}")


def render_history_tab() -> None:
    products = get_products()
    if products.empty:
        st.info("저장된 프로젝트가 없습니다.")
        return
    products["label"] = products.apply(lambda row: f"{row['product_code']} | {row['product_name']}", axis=1)
    product_labels = products["label"].tolist()
    if "history_product_label" not in st.session_state or st.session_state["history_product_label"] not in product_labels:
        st.session_state["history_product_label"] = product_labels[0]
    selected_product_label = st.sidebar.selectbox("프로젝트 선택", options=product_labels, key="history_product_label")
    selected_product = products[products["label"] == selected_product_label].iloc[0]

    headers, options = build_history_options_for_product(selected_product["product_code"])
    if len(options) == 1:
        st.info("선택한 상품의 저장된 시뮬레이션이 없습니다.")
        return
    history_key = f"history_simulation_{selected_product['product_code']}"
    if history_key not in st.session_state or st.session_state[history_key] not in options[1:]:
        st.session_state[history_key] = options[1]
    selected_label = st.sidebar.selectbox("시뮬레이션 선택", options=options[1:], key=history_key)
    selected_history = headers[headers["label"] == selected_label].iloc[0]
    simulation_id = int(selected_history["id"])

    tree_df = load_product_tree_or_error(selected_product["result_item_id"])
    if tree_df is None:
        return
    saved_inputs = normalize_bom_inputs(tree_df, load_saved_simulation_inputs(simulation_id))
    st.session_state["history_force_widget_sync"] = True

    top_left, top_right = st.columns([1, 1.2], gap="large")
    with top_left:
        linked_item_code = selected_product["result_item_code"] if "result_item_code" in selected_product.index else selected_product["result_item_id"]
        st.write(f"대상 공정품: `{linked_item_code or selected_product['result_item_id']}` {selected_product['result_item_name'] or selected_product['result_item_id']}")
        st.write(f"저장 총원가: {safe_float(selected_history['total_cost']):,.2f}")
        st.write(f"시뮬레이션 ID: `{simulation_id}`")
        st.caption(f"저장일시: {selected_history['created_at']}")
    with top_right:
        selected_tree_row = render_simulation_summary_panel(
            tree_df=tree_df,
            item_inputs=saved_inputs,
            selected_item_key="history_selected_tree_label",
            product_label="",
        )
    st.markdown("---")
    render_bom_item_form(selected_tree_row, tree_df=tree_df, bom_inputs=saved_inputs, state_prefix="history", read_only=True)
    st.session_state["history_force_widget_sync"] = False


def get_pre_estimate_projects_df() -> pd.DataFrame:
    return query_df(
        """
        SELECT pre_project_id, project_name, customer_name, item_count, annual_sales_qty, root_item_name, root_process_type, pc_definition,
               description, development_type, notes, created_at, updated_at
        FROM pre_estimate_projects
        ORDER BY pre_project_id DESC
        """
    )


def get_pre_estimate_items_df(pre_project_id: int) -> pd.DataFrame:
    return query_df(
        """
        SELECT pre_item_id, pre_project_id, parent_pre_item_id, item_name, process_type,
               material_cost, process_cost, management_rate_pct, defect_rate_pct,
               packaging_cost, moving_cost, mold_cost, lead_days, detail_json, notes, sort_order,
               created_at, updated_at
        FROM pre_estimate_items
        WHERE pre_project_id = ?
        ORDER BY sort_order, pre_item_id
        """,
        (pre_project_id,),
    )


def save_pre_estimate_project(
    pre_project_id: int | None,
    project_name: str,
    customer_name: str,
    item_count: int,
    annual_sales_qty: float,
    notes: str,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.cursor()
        if pre_project_id is None:
            cur.execute(
                """
                INSERT INTO pre_estimate_projects (
                    project_name, customer_name, item_count, annual_sales_qty, notes, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_name.strip(),
                    customer_name.strip(),
                    max(1, int(item_count)),
                    max(0.0, safe_float(annual_sales_qty)),
                    notes.strip(),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        cur.execute(
            """
            UPDATE pre_estimate_projects
            SET project_name = ?, customer_name = ?, item_count = ?, annual_sales_qty = ?, notes = ?, updated_at = ?
            WHERE pre_project_id = ?
            """,
            (
                project_name.strip(),
                customer_name.strip(),
                max(1, int(item_count)),
                max(0.0, safe_float(annual_sales_qty)),
                notes.strip(),
                now,
                pre_project_id,
            ),
        )
        conn.commit()
        return pre_project_id


def ensure_pre_estimate_root_items(pre_project_id: int, item_count: int) -> None:
    item_count = max(1, int(item_count))
    items_df = get_pre_estimate_items_df(pre_project_id)
    root_df = items_df[items_df["parent_pre_item_id"].isna()] if not items_df.empty else pd.DataFrame()
    existing_root_count = len(root_df)
    for idx in range(existing_root_count + 1, item_count + 1):
        save_pre_estimate_item(
            None,
            pre_project_id,
            None,
            f"공정품 {idx}",
            "사출",
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            "{}",
            "",
        )


def ensure_pre_estimate_child_items(pre_project_id: int, parent_pre_item_id: int, target_count: int) -> None:
    target_count = max(0, int(target_count))
    items_df = get_pre_estimate_items_df(pre_project_id)
    direct_children = (
        items_df[items_df["parent_pre_item_id"] == parent_pre_item_id]
        .sort_values(["sort_order", "pre_item_id"])
        .reset_index(drop=True)
    )
    existing_count = len(direct_children)

    if target_count > existing_count:
        parent_row = items_df[items_df["pre_item_id"] == parent_pre_item_id].iloc[0]
        parent_name = str(parent_row["item_name"]).strip() or f"공정품 {parent_pre_item_id}"
        for idx in range(existing_count + 1, target_count + 1):
            save_pre_estimate_item(
                None,
                pre_project_id,
                parent_pre_item_id,
                f"{parent_name}-{idx}",
                "사출",
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                "{}",
                "",
            )
        return

    if target_count < existing_count:
        removable_children = direct_children.iloc[target_count:]
        for _, child_row in removable_children.sort_values(["sort_order", "pre_item_id"], ascending=False).iterrows():
            child_id = int(child_row["pre_item_id"])
            has_descendants = not items_df[items_df["parent_pre_item_id"] == child_id].empty
            if not has_descendants:
                delete_pre_estimate_item(child_id)


def save_pre_estimate_item(
    pre_item_id: int | None,
    pre_project_id: int,
    parent_pre_item_id: int | None,
    item_name: str,
    process_type: str,
    material_cost: float,
    process_cost: float,
    management_rate_pct: float,
    defect_rate_pct: float,
    packaging_cost: float,
    moving_cost: float,
    mold_cost: float,
    lead_days: float,
    detail_json: str,
    notes: str,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.cursor()
        if pre_item_id is None:
            sort_order_row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM pre_estimate_items WHERE pre_project_id = ?",
                (pre_project_id,),
            ).fetchone()
            sort_order = int(sort_order_row["next_order"]) if sort_order_row else 1
            cur.execute(
                """
                INSERT INTO pre_estimate_items (
                    pre_project_id, parent_pre_item_id, item_name, process_type, material_cost, process_cost,
                    management_rate_pct, defect_rate_pct, packaging_cost, moving_cost, mold_cost, lead_days, detail_json,
                    notes, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pre_project_id,
                    parent_pre_item_id,
                    item_name.strip(),
                    process_type,
                    material_cost,
                    process_cost,
                    management_rate_pct,
                    defect_rate_pct,
                    packaging_cost,
                    moving_cost,
                    mold_cost,
                    lead_days,
                    detail_json,
                    notes.strip(),
                    sort_order,
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        cur.execute(
            """
            UPDATE pre_estimate_items
            SET parent_pre_item_id = ?, item_name = ?, process_type = ?, material_cost = ?, process_cost = ?,
                management_rate_pct = ?, defect_rate_pct = ?, packaging_cost = ?, moving_cost = ?, mold_cost = ?,
                lead_days = ?, detail_json = ?, notes = ?, updated_at = ?
            WHERE pre_item_id = ?
            """,
            (
                parent_pre_item_id,
                item_name.strip(),
                process_type,
                material_cost,
                process_cost,
                management_rate_pct,
                defect_rate_pct,
                packaging_cost,
                moving_cost,
                mold_cost,
                lead_days,
                detail_json,
                notes.strip(),
                now,
                pre_item_id,
            ),
        )
        conn.commit()
        return pre_item_id


def parse_detail_json(value: object) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def delete_pre_estimate_item(pre_item_id: int) -> None:
    execute("DELETE FROM pre_estimate_items WHERE pre_item_id = ?", (pre_item_id,))


def build_pre_estimate_tree(pre_project_id: int) -> pd.DataFrame:
    items_df = get_pre_estimate_items_df(pre_project_id)
    if items_df.empty:
        return pd.DataFrame(columns=["node_id", "parent_node_id", "pre_item_id", "label", "process_type", "own_cost", "cumulative_cost", "lead_days", "cumulative_lead_days"])

    item_map = {int(row["pre_item_id"]): row.to_dict() for _, row in items_df.iterrows()}
    children: dict[int | None, list[int]] = {}
    for _, row in items_df.iterrows():
        parent_id = int(row["parent_pre_item_id"]) if row["parent_pre_item_id"] not in [None, ""] and not pd.isna(row["parent_pre_item_id"]) else None
        children.setdefault(parent_id, []).append(int(row["pre_item_id"]))

    tree_rows: list[dict] = []

    def process_unit_cost(row: dict, child_total: float) -> tuple[float, float]:
        process_type = str(row.get("process_type") or "")
        material_cost = safe_float(row["material_cost"])
        process_cost = safe_float(row["process_cost"])
        management_rate = safe_float(row["management_rate_pct"]) / 100.0
        defect_rate = safe_float(row["defect_rate_pct"]) / 100.0
        extras = safe_float(row["packaging_cost"]) + safe_float(row["moving_cost"])

        if process_type == "사출":
            own = material_cost + process_cost
            cumulative = own
            return own, cumulative

        if process_type == "조립":
            own = material_cost + process_cost
        elif process_type in {"인쇄", "후가공"}:
            own = process_cost
        else:
            own = process_cost

        management = own * management_rate
        defect = own * defect_rate
        cumulative = child_total + own + management + defect + extras
        return own, cumulative

    def walk(pre_item_id: int, node_id: str, parent_node_id: str | None, level: int) -> tuple[float, float]:
        row = item_map[pre_item_id]
        child_cost_total = 0.0
        child_lead_days: list[float] = []
        for idx, child_id in enumerate(children.get(pre_item_id, []), start=1):
            child_cumulative_cost, child_cumulative_lead = walk(child_id, f"{node_id}.{idx}", node_id, level + 1)
            child_cost_total += child_cumulative_cost
            child_lead_days.append(child_cumulative_lead)
        row_own_cost, row_cumulative_cost = process_unit_cost(row, child_cost_total)
        row_lead_days = safe_float(row["lead_days"])
        row_cumulative_lead = row_lead_days + (max(child_lead_days) if child_lead_days else 0.0)
        tree_rows.append(
            {
                "node_id": node_id,
                "parent_node_id": parent_node_id or "",
                "pre_item_id": pre_item_id,
                "label": f"{'    ' * level}{row['item_name']}",
                "process_type": row["process_type"],
                "own_cost": round(row_own_cost, 2),
                "cumulative_cost": round(row_cumulative_cost, 2),
                "mold_cost": round(safe_float(row["mold_cost"]), 2),
                "lead_days": row_lead_days,
                "cumulative_lead_days": round(row_cumulative_lead, 1),
            }
        )
        return row_cumulative_cost, row_cumulative_lead

    for idx, root_id in enumerate(children.get(None, []), start=1):
        walk(root_id, str(idx), None, 0)

    return pd.DataFrame(tree_rows)


def render_pre_estimate_basic_tab() -> None:
    projects_df = get_pre_estimate_projects_df()
    pending_project_label = st.session_state.pop("pre_basic_project_label_pending", None)
    if pending_project_label is not None:
        st.session_state["pre_basic_project_label"] = pending_project_label
    project_options = [""] + [f"{row['pre_project_id']} | {row['project_name']}" for _, row in projects_df.iterrows()]
    selected_label = st.sidebar.selectbox("사전견적 프로젝트", options=project_options, key="pre_basic_project_label")
    selected_row = None
    if selected_label:
        selected_id = int(selected_label.split(" | ")[0])
        selected_row = projects_df[projects_df["pre_project_id"] == selected_id].iloc[0]

    left_col, right_col = st.columns([1.2, 1], gap="large")
    with left_col:
        st.markdown("**프로젝트 / 공정품 트리 시작 정의**")
        top_c1, top_c2 = st.columns(2, gap="large")
        with top_c1:
            project_name = st.text_input("프로젝트명", value=selected_row["project_name"] if selected_row is not None else "")
            customer_name = st.text_input("고객", value=selected_row["customer_name"] if selected_row is not None else "")
        with top_c2:
            item_count = st.number_input("공정품수", min_value=1, max_value=5, value=int(selected_row["item_count"]) if selected_row is not None and not pd.isna(selected_row["item_count"]) else 1, step=1)
            annual_sales_qty = st.number_input("예상 연간판매량", min_value=0.0, value=safe_float(selected_row["annual_sales_qty"]) if selected_row is not None else 0.0, step=1000.0)
            notes = st.text_input("비고", value=selected_row["notes"] if selected_row is not None else "")

    save_label = "기본정보 수정 저장" if selected_row is not None else "기본정보 저장"
    if st.button(save_label, key="save_pre_basic"):
        if not project_name.strip():
            st.error("프로젝트명을 입력해 주세요.")
        else:
            saved_id = save_pre_estimate_project(
                int(selected_row["pre_project_id"]) if selected_row is not None else None,
                project_name,
                customer_name,
                int(item_count),
                annual_sales_qty,
                notes,
            )
            ensure_pre_estimate_root_items(saved_id, int(item_count))
            st.session_state["pre_basic_project_label_pending"] = f"{saved_id} | {project_name}"
            flash_success(f"저장했습니다. ID: {saved_id}")
            st.rerun()

    with right_col:
        st.markdown("**공정품 트리**")
        if selected_row is not None:
            tree_df = build_pre_estimate_tree(int(selected_row["pre_project_id"]))
            if not tree_df.empty:
                tree_preview_df = tree_df[["label", "process_type", "own_cost", "cumulative_cost"]].rename(
                    columns={"label": "공정품", "process_type": "공정", "own_cost": "공정단가", "cumulative_cost": "누적단가"}
                )
                render_dataframe(tree_preview_df)
            else:
                st.info("아직 공정품 트리가 없습니다.")
        else:
            st.info("프로젝트를 선택하면 공정품 트리를 같이 볼 수 있습니다.")

    if not projects_df.empty:
        with st.expander("기본정보 이력", expanded=False):
            render_dataframe(
                projects_df[["pre_project_id", "project_name", "customer_name", "item_count", "annual_sales_qty", "updated_at"]].rename(
                    columns={"item_count": "공정품수", "annual_sales_qty": "예상 연간판매량"}
                )
            )

    if selected_row is not None:
        tree_df = build_pre_estimate_tree(int(selected_row["pre_project_id"]))
        item_df = get_pre_estimate_items_df(int(selected_row["pre_project_id"]))
        if not item_df.empty and not tree_df.empty:
            st.markdown("**공정품 트리 입력 카드**")
            process_type_options = ["사출", "증착", "코팅", "인쇄", "조립", "사상", "기타", "포장", "이동"]

            def render_item_node(pre_item_id: int, depth: int = 0) -> None:
                current_item_row = item_df[item_df["pre_item_id"] == int(pre_item_id)].iloc[0]
                current_tree_row = tree_df[tree_df["pre_item_id"] == int(pre_item_id)].iloc[0]
                direct_children_df = (
                    item_df[item_df["parent_pre_item_id"] == int(pre_item_id)]
                    .sort_values(["sort_order", "pre_item_id"])
                    .reset_index(drop=True)
                )
                direct_child_count = len(direct_children_df)
                card_key = f"pre_basic_card_{int(pre_item_id)}"

                with st.container(border=True):
                    input_c1, input_c2, input_c3 = st.columns(3, gap="large")
                    with input_c1:
                        item_name_value = st.text_input("공정품명", value=current_item_row["item_name"], key=f"{card_key}_name")
                    with input_c2:
                        process_value = st.selectbox(
                            "공정",
                            options=process_type_options,
                            index=process_type_options.index(current_item_row["process_type"]) if current_item_row["process_type"] in process_type_options else 0,
                            key=f"{card_key}_process",
                        )
                    with input_c3:
                        child_count_value = st.number_input("하위 공정품 개수", min_value=0, max_value=8, value=int(direct_child_count), step=1, key=f"{card_key}_children")

                    if item_name_value != current_item_row["item_name"] or process_value != current_item_row["process_type"]:
                        save_pre_estimate_item(
                            int(current_item_row["pre_item_id"]),
                            int(current_item_row["pre_project_id"]),
                            int(current_item_row["parent_pre_item_id"]) if current_item_row["parent_pre_item_id"] not in [None, ""] and not pd.isna(current_item_row["parent_pre_item_id"]) else None,
                            item_name_value,
                            process_value,
                            safe_float(current_item_row["material_cost"]),
                            safe_float(current_item_row["process_cost"]),
                            safe_float(current_item_row["management_rate_pct"]),
                            safe_float(current_item_row["defect_rate_pct"]),
                            safe_float(current_item_row["packaging_cost"]),
                            safe_float(current_item_row["moving_cost"]),
                            safe_float(current_item_row["mold_cost"]),
                            safe_float(current_item_row["lead_days"]),
                            current_item_row["detail_json"] or "{}",
                            current_item_row["notes"] or "",
                        )
                        st.rerun()

                    if int(child_count_value) != int(direct_child_count):
                        ensure_pre_estimate_child_items(int(current_item_row["pre_project_id"]), int(current_item_row["pre_item_id"]), int(child_count_value))
                        st.rerun()

                if not direct_children_df.empty:
                    for _, child_row in direct_children_df.iterrows():
                        render_item_node(int(child_row["pre_item_id"]), depth + 1)

            root_rows = (
                item_df[item_df["parent_pre_item_id"].isna()]
                .sort_values(["sort_order", "pre_item_id"])
                .reset_index(drop=True)
            )
            root_columns = st.columns(max(1, len(root_rows)), gap="large")
            for idx, (_, root_row) in enumerate(root_rows.iterrows()):
                with root_columns[idx]:
                    render_item_node(int(root_row["pre_item_id"]), 0)


def render_pre_estimate_tree_tab() -> None:
    projects_df = get_pre_estimate_projects_df()
    if projects_df.empty:
        st.info("먼저 사전견적 기본정보를 등록하세요.")
        return

    project_options = [f"{row['pre_project_id']} | {row['project_name']}" for _, row in projects_df.iterrows()]
    selected_label = st.sidebar.selectbox("사전견적 프로젝트", options=project_options, key="pre_tree_project_label")
    selected_project_id = int(selected_label.split(" | ")[0])
    selected_project = projects_df[projects_df["pre_project_id"] == selected_project_id].iloc[0]

    item_df = get_pre_estimate_items_df(selected_project_id)
    tree_df = build_pre_estimate_tree(selected_project_id)
    annual_sales_qty = safe_float(selected_project["annual_sales_qty"])

    top_c1, top_c2, top_c3, top_c4, top_c5, top_c6, top_c7 = st.columns(7)
    with top_c6:
        depreciation_years = st.number_input("금형 감가상각 년수", min_value=1.0, value=float(st.session_state.get("pre_tree_depreciation_years", 3.0)), step=1.0, key="pre_tree_depreciation_years")

    total_cost = safe_float(tree_df.loc[tree_df["parent_node_id"] == "", "cumulative_cost"].sum()) if not tree_df.empty else 0.0
    total_days = safe_float(tree_df.loc[tree_df["parent_node_id"] == "", "cumulative_lead_days"].max()) if not tree_df.empty else 0.0
    total_mold_cost = safe_float(item_df["mold_cost"].sum()) if not item_df.empty else 0.0
    mold_count = int(len(item_df[(item_df["process_type"] == "사출") & (item_df["mold_cost"] > 0)])) if not item_df.empty else 0
    total_unit_mold_cost = (total_mold_cost / (annual_sales_qty * depreciation_years)) if annual_sales_qty > 0 and depreciation_years > 0 else 0.0
    total_expected_cost = total_cost + total_unit_mold_cost

    with top_c1:
        st.metric("총 예상 원가", f"{total_expected_cost:,.2f}")
    with top_c2:
        st.metric("누적단가", f"{total_cost:,.2f}")
    with top_c3:
        st.metric("총 개당금형비", f"{total_unit_mold_cost:,.2f}")
    with top_c4:
        st.metric("총 금형비", f"{total_mold_cost:,.0f}")
    with top_c5:
        st.metric("금형벌수", f"{mold_count}")
    with top_c7:
        st.metric("기간(일)", f"{total_days:,.1f}")

    add_expanded = st.expander("공정품 추가 / 수정", expanded=item_df.empty)
    with add_expanded:
        item_options = ["신규 공정품"] + [f"{row['pre_item_id']} | {row['item_name']}" for _, row in item_df.iterrows()]
        selected_item_label = st.selectbox("공정품 선택", options=item_options, key="pre_tree_item_label")
        selected_item_row = None
        if selected_item_label != "신규 공정품":
            selected_item_id = int(selected_item_label.split(" | ")[0])
            selected_item_row = item_df[item_df["pre_item_id"] == selected_item_id].iloc[0]

        parent_options = [("없음", None)] + [(f"{row['item_name']} ({int(row['pre_item_id'])})", int(row["pre_item_id"])) for _, row in item_df.iterrows() if selected_item_row is None or int(row["pre_item_id"]) != int(selected_item_row["pre_item_id"])]
        c1, c2 = st.columns(2, gap="large")
        with c1:
            item_name = st.text_input("공정품명", value=selected_item_row["item_name"] if selected_item_row is not None else "")
            process_type_options = ["사출", "증착", "코팅", "인쇄", "조립", "사상", "기타", "포장", "이동"]
            current_process = selected_item_row["process_type"] if selected_item_row is not None else "사출"
            process_type = st.selectbox("공정", options=process_type_options, index=process_type_options.index(current_process) if current_process in process_type_options else 0)
        with c2:
            parent_label = st.selectbox("상위 공정품", options=[label for label, _ in parent_options], index=0 if selected_item_row is None or pd.isna(selected_item_row["parent_pre_item_id"]) else next((idx for idx, (_, value) in enumerate(parent_options) if value == int(selected_item_row["parent_pre_item_id"])), 0))
            notes = st.text_input("비고", value=selected_item_row["notes"] if selected_item_row is not None else "")

        action_c1, action_c2 = st.columns(2)
        with action_c1:
            if st.button("공정품 저장", key="save_pre_tree_item"):
                if not item_name.strip():
                    st.error("공정품명을 입력해 주세요.")
                else:
                    parent_pre_item_id = dict(parent_options).get(parent_label)
                    saved_item_id = save_pre_estimate_item(
                        int(selected_item_row["pre_item_id"]) if selected_item_row is not None else None,
                        selected_project_id,
                        parent_pre_item_id,
                        item_name,
                        process_type,
                        safe_float(selected_item_row["material_cost"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["process_cost"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["management_rate_pct"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["defect_rate_pct"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["packaging_cost"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["moving_cost"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["mold_cost"]) if selected_item_row is not None else 0.0,
                        safe_float(selected_item_row["lead_days"]) if selected_item_row is not None else 0.0,
                        selected_item_row["detail_json"] if selected_item_row is not None and "detail_json" in selected_item_row else "{}",
                        notes,
                    )
                    flash_success(f"저장했습니다. ID: {saved_item_id}")
                    st.rerun()
        with action_c2:
            if selected_item_row is not None and st.button("공정품 삭제", key="delete_pre_tree_item"):
                delete_pre_estimate_item(int(selected_item_row["pre_item_id"]))
                flash_success("삭제했습니다.")
                st.rerun()

    if not tree_df.empty:
        st.markdown("**트리 순 카드 입력**")

        process_type_options = ["사출", "증착", "코팅", "인쇄", "조립", "사상", "기타", "포장", "이동"]

        def render_cost_node(pre_item_id: int) -> None:
            row = item_df[item_df["pre_item_id"] == int(pre_item_id)].iloc[0]
            tree_row = tree_df[tree_df["pre_item_id"] == int(pre_item_id)].iloc[0]
            detail = parse_detail_json(row["detail_json"])
            card_key = f"pre_cost_{int(pre_item_id)}"
            process_type = row["process_type"]

            with st.container(border=True):
                head1, head2, head3 = st.columns([1.4, 0.8, 0.8], gap="large")
                with head1:
                    st.markdown(f"**{str(tree_row['label']).strip()}**")
                    st.caption(f"공정: {process_type}")
                with head2:
                    st.metric("공정단가", f"{safe_float(tree_row['own_cost']):,.2f}")
                with head3:
                    st.metric("누적단가", f"{safe_float(tree_row['cumulative_cost']):,.2f}")

                common_c1, common_c2 = st.columns(2, gap="large")
                unit_mold_cost = (safe_float(row["mold_cost"]) / (annual_sales_qty * depreciation_years)) if process_type == "사출" and annual_sales_qty > 0 and depreciation_years > 0 else 0.0
                material_value = safe_float(row["material_cost"])
                process_value = safe_float(row["process_cost"])
                mold_cost_value = safe_float(row["mold_cost"])
                lead_days_value = safe_float(row["lead_days"])
                if process_type == "사출":
                    own_formula_text = f"재료비 {material_value:,.2f} + 가공비 {process_value:,.2f}"
                elif process_type == "조립":
                    own_formula_text = f"부재료비 {material_value:,.2f} + 가공비 {process_value:,.2f}"
                else:
                    own_formula_text = f"가공비 {process_value:,.2f}"
                with common_c1:
                    st.markdown("**공정공통**")
                    st.text_input("공정단가", value=own_formula_text, disabled=True, key=f"{card_key}_own")
                    st.text_input("누적단가", value=f"{safe_float(tree_row['cumulative_cost']):,.2f}", disabled=True, key=f"{card_key}_cum")
                    if process_type == "사출":
                        st.text_input("개당금형비", value=f"{unit_mold_cost:,.2f}", disabled=True, key=f"{card_key}_unit_mold")
                with common_c2:
                    management_value = st.number_input("관리비(%)", min_value=0.0, value=safe_float(row["management_rate_pct"]), step=0.5, key=f"{card_key}_management")
                    defect_value = st.number_input("불량률(%)", min_value=0.0, value=safe_float(row["defect_rate_pct"]), step=0.5, key=f"{card_key}_defect")
                    moving_value = st.number_input("이동비", min_value=0.0, value=safe_float(row["moving_cost"]), step=100.0, key=f"{card_key}_moving")
                    packaging_value = st.number_input("포장비", min_value=0.0, value=safe_float(row["packaging_cost"]), step=100.0, key=f"{card_key}_packaging")

                if process_type == "사출":
                    rates = get_resource_rates()
                    rate_options = [""] + rates["resource_code"].tolist() if not rates.empty else [""]
                    injection_c1, injection_c2, injection_c3 = st.columns(3, gap="large")
                    with injection_c1:
                        st.markdown("**금형**")
                        mold_cost_value = st.number_input("금형비", min_value=0.0, value=mold_cost_value, step=10000.0, key=f"{card_key}_mold")
                        lead_days_value = st.number_input("제작기간(일)", min_value=0.0, value=lead_days_value, step=1.0, key=f"{card_key}_lead")
                        mold_type_value = st.text_input("형식", value=str(detail.get("mold_type", "")), key=f"{card_key}_mold_type")
                        cavity_value = st.number_input("Cavity", min_value=1.0, value=max(1.0, safe_float(detail.get("cavity", 1.0))), step=1.0, key=f"{card_key}_cavity")
                    with injection_c2:
                        st.markdown("**재료비**")
                        weight_value = st.number_input("제품무게(g)", min_value=0.0, value=safe_float(detail.get("weight_g", 0.0)), step=0.1, key=f"{card_key}_weight")
                        scrap_value = st.number_input("스크랩무게(g)", min_value=0.0, value=safe_float(detail.get("scrap_weight_g", 0.0)), step=0.1, key=f"{card_key}_scrap")
                        raw_price_value = st.number_input("원료단가", min_value=0.0, value=safe_float(detail.get("raw_unit_price", 0.0)), step=100.0, key=f"{card_key}_raw_price")
                        mb_price_value = st.number_input("MB단가", min_value=0.0, value=safe_float(detail.get("mb_unit_price", 0.0)), step=100.0, key=f"{card_key}_mb_price")
                        mb_ratio_value = st.number_input("MB비율(%)", min_value=0.0, max_value=100.0, value=safe_float(detail.get("mb_ratio_pct", 0.0)), step=0.1, key=f"{card_key}_mb_ratio")
                        total_weight_kg = (weight_value + scrap_value) / 1000.0
                        material_value = (total_weight_kg * ((100.0 - mb_ratio_value) / 100.0) * raw_price_value) + (total_weight_kg * (mb_ratio_value / 100.0) * mb_price_value)
                        st.text_input("재료비 계산", value=f"{material_value:,.2f}", disabled=True, key=f"{card_key}_material_display")
                    with injection_c3:
                        st.markdown("**가공비**")
                        current_resource_code = str(detail.get("resource_code", ""))
                        tonnage_value = st.selectbox(
                            "톤수",
                            options=rate_options,
                            index=rate_options.index(current_resource_code) if current_resource_code in rate_options else 0,
                            key=f"{card_key}_tonnage",
                        )
                        process_hours_value = st.number_input("시간", min_value=0.0, value=safe_float(detail.get("daily_hours", DEFAULT_DAILY_HOURS)), step=0.5, key=f"{card_key}_process_hours")
                        ct_value = st.number_input("CT", min_value=0.0, value=safe_float(detail.get("ct_sec", 0.0)), step=0.1, key=f"{card_key}_ct")
                        daily_rate_value = 0.0
                        if tonnage_value and not rates.empty:
                            rate_match = rates[rates["resource_code"] == tonnage_value]
                            if not rate_match.empty:
                                daily_rate_value = safe_float(rate_match.iloc[0]["daily_rate"])
                        if daily_rate_value > 0 and process_hours_value > 0 and ct_value > 0 and cavity_value > 0:
                            process_value = daily_rate_value / ((process_hours_value * 3600.0 / ct_value) * cavity_value)
                        else:
                            process_value = 0.0
                        st.text_input("예상가공비", value=f"{process_value:,.2f}", disabled=True, key=f"{card_key}_process_cost")
                    detail = {
                        **detail,
                        "mold_type": mold_type_value,
                        "cavity": cavity_value,
                        "weight_g": weight_value,
                        "scrap_weight_g": scrap_value,
                        "raw_unit_price": raw_price_value,
                        "mb_unit_price": mb_price_value,
                        "mb_ratio_pct": mb_ratio_value,
                        "resource_code": tonnage_value,
                        "daily_hours": process_hours_value,
                        "ct_sec": ct_value,
                    }
                elif process_type == "조립":
                    assembly_c1, assembly_c2 = st.columns(2, gap="large")
                    with assembly_c1:
                        st.markdown("**부재료**")
                        asm1_name = st.text_input("종류1", value=str(detail.get("assembly_material_1_name", "")), key=f"{card_key}_asm1_name")
                        asm1_price = st.number_input("가격1", min_value=0.0, value=safe_float(detail.get("assembly_material_1_price", 0.0)), step=100.0, key=f"{card_key}_asm1_price")
                        asm2_name = st.text_input("종류2", value=str(detail.get("assembly_material_2_name", "")), key=f"{card_key}_asm2_name")
                        asm2_price = st.number_input("가격2", min_value=0.0, value=safe_float(detail.get("assembly_material_2_price", 0.0)), step=100.0, key=f"{card_key}_asm2_price")
                        asm3_name = st.text_input("종류3", value=str(detail.get("assembly_material_3_name", "")), key=f"{card_key}_asm3_name")
                        asm3_price = st.number_input("가격3", min_value=0.0, value=safe_float(detail.get("assembly_material_3_price", 0.0)), step=100.0, key=f"{card_key}_asm3_price")
                        material_value = asm1_price + asm2_price + asm3_price
                    with assembly_c2:
                        st.markdown("**가공비**")
                        units_per_hour = st.number_input("시간당생산량", min_value=0.0, value=safe_float(detail.get("units_per_hour", 0.0)), step=1.0, key=f"{card_key}_uph")
                        manpower = st.number_input("투입인원", min_value=0.0, value=safe_float(detail.get("manpower", 0.0)), step=1.0, key=f"{card_key}_manpower")
                        process_value = st.number_input("예상비용", min_value=0.0, value=process_value, step=100.0, key=f"{card_key}_process_cost")
                    detail = {
                        **detail,
                        "assembly_material_1_name": asm1_name,
                        "assembly_material_1_price": asm1_price,
                        "assembly_material_2_name": asm2_name,
                        "assembly_material_2_price": asm2_price,
                        "assembly_material_3_name": asm3_name,
                        "assembly_material_3_price": asm3_price,
                        "units_per_hour": units_per_hour,
                        "manpower": manpower,
                    }
                elif process_type == "인쇄":
                    print_c1 = st.columns(1)[0]
                    with print_c1:
                        st.markdown("**가공비**")
                        units_per_hour = st.number_input("시간당생산량", min_value=0.0, value=safe_float(detail.get("units_per_hour", 0.0)), step=1.0, key=f"{card_key}_uph")
                        manpower = st.number_input("투입인원", min_value=0.0, value=safe_float(detail.get("manpower", 0.0)), step=1.0, key=f"{card_key}_manpower")
                        process_value = st.number_input("예상비용", min_value=0.0, value=process_value, step=100.0, key=f"{card_key}_process_cost")
                    detail = {**detail, "units_per_hour": units_per_hour, "manpower": manpower}
                else:
                    generic_c1 = st.columns(1)[0]
                    with generic_c1:
                        st.markdown("**후가공**")
                        process_value = st.number_input("예상비용", min_value=0.0, value=process_value, step=100.0, key=f"{card_key}_process_cost")

                detail_json = json.dumps(detail, ensure_ascii=False)
                has_changes = (
                    material_value != safe_float(row["material_cost"])
                    or process_value != safe_float(row["process_cost"])
                    or management_value != safe_float(row["management_rate_pct"])
                    or defect_value != safe_float(row["defect_rate_pct"])
                    or packaging_value != safe_float(row["packaging_cost"])
                    or moving_value != safe_float(row["moving_cost"])
                    or mold_cost_value != safe_float(row["mold_cost"])
                    or lead_days_value != safe_float(row["lead_days"])
                    or detail_json != (row["detail_json"] or "{}")
                )

                save_col, state_col = st.columns([0.8, 1.2])
                with save_col:
                    if st.button("카드 저장", key=f"{card_key}_save"):
                        save_pre_estimate_item(
                            int(row["pre_item_id"]),
                            selected_project_id,
                            int(row["parent_pre_item_id"]) if row["parent_pre_item_id"] not in [None, ""] and not pd.isna(row["parent_pre_item_id"]) else None,
                            row["item_name"],
                            row["process_type"],
                            material_value,
                            process_value,
                            management_value,
                            defect_value,
                            packaging_value,
                            moving_value,
                            mold_cost_value,
                            lead_days_value,
                            detail_json,
                            row["notes"] or "",
                        )
                        flash_success("저장했습니다.")
                        st.rerun()
                with state_col:
                    if has_changes:
                        st.caption("변경값이 있습니다. 카드 저장을 누르면 반영됩니다.")

                child_rows = (
                    item_df[item_df["parent_pre_item_id"] == int(pre_item_id)]
                    .sort_values(["sort_order", "pre_item_id"])
                    .reset_index(drop=True)
                )
                for _, child_row in child_rows.iterrows():
                    render_cost_node(int(child_row["pre_item_id"]))

        root_rows = (
            item_df[item_df["parent_pre_item_id"].isna()]
            .sort_values(["sort_order", "pre_item_id"])
            .reset_index(drop=True)
        )
        root_columns = st.columns(max(1, len(root_rows)), gap="large")
        for idx, (_, root_row) in enumerate(root_rows.iterrows()):
            with root_columns[idx]:
                render_cost_node(int(root_row["pre_item_id"]))


def render_pre_estimate_tab() -> None:
    submenu = st.sidebar.radio("사전견적 시뮬레이션", ["기본정보", "트리 원가/기간"], key="pre_estimate_submenu")
    if submenu == "기본정보":
        render_pre_estimate_basic_tab()
    else:
        render_pre_estimate_tree_tab()


def main() -> None:
    init_db()
    render_app_header()
    main_menu = st.sidebar.radio("메인 메뉴", ["기초정보", "사전견적 시뮬레이션", "시뮬레이션", "History"], key="main_menu")
    if main_menu == "기초정보":
        render_master_tab()
    elif main_menu == "사전견적 시뮬레이션":
        render_pre_estimate_tab()
    elif main_menu == "시뮬레이션":
        render_simulation_tab()
    else:
        render_history_tab()


if __name__ == "__main__":
    main()
