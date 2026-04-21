from __future__ import annotations

from statistics import mean

from db.runtime import query_df
from services.development_page_service import parse_json_text


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_ct_seconds(*detail_dicts: dict) -> float:
    for detail in detail_dicts:
        if not isinstance(detail, dict):
            continue
        primary_value = _as_float(detail.get("C/T_1차"), 0.0)
        if primary_value > 0:
            return primary_value
        for key in ("ct_sec", "ct", "c_t", "cycle_time", "cycle_time_sec", "condition_ct"):
            value = _as_float(detail.get(key), 0.0)
            if value > 0:
                return value
        condition_input = str(detail.get("condition_input") or "")
        if condition_input:
            import re
            match = re.search(r"(?:c/?t|ct)\s*[:=]?\s*(\d+(?:\.\d+)?)", condition_input, re.IGNORECASE)
            if match:
                return _as_float(match.group(1), 0.0)
    return 0.0


def resolve_cost_simulation_defaults(project_id: int, item_id: int) -> dict:
    projects_df = query_df(
        """
        SELECT project_id, project_code, product_name
        FROM development_projects
        """
    )
    items_df = query_df(
        """
        SELECT item_id, project_id, item_code, item_name, process_type
        FROM items
        """
    )
    bom_df = query_df(
        """
        SELECT project_id, parent_item_id, child_item_id, qty, qty_unit, notes
        FROM item_bom
        """
    )
    samples_df = query_df(
        """
        SELECT s.sample_id, s.sample_code, s.instruction_detail_json, s.mb_request_id, mr.request_code AS mb_request_code, eo.item_id
        FROM experiment_samples s
        JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
        LEFT JOIN mb_requests mr ON mr.mb_request_id = s.mb_request_id
        WHERE eo.item_id = ?
        ORDER BY s.sample_id DESC
        """,
        (item_id,),
    )
    op_df = query_df(
        """
        SELECT opr.op_detail_json
        FROM sample_op_reviews opr
        JOIN experiment_samples s ON s.sample_id = opr.sample_id
        JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
        WHERE eo.item_id = ? AND opr.op_detail_json IS NOT NULL
        ORDER BY opr.sample_id DESC
        LIMIT 1
        """,
        (item_id,),
    )
    mold_df = query_df(
        """
        SELECT COALESCE(m.cavity, 1) AS cavity
        FROM items i
        LEFT JOIN molds m ON m.mold_id = i.primary_mold_id
        WHERE i.item_id = ?
        """,
        (item_id,),
    )

    project_row = projects_df[projects_df["project_id"] == project_id].iloc[0] if not projects_df.empty and (projects_df["project_id"] == project_id).any() else None
    item_row = items_df[items_df["item_id"] == item_id].iloc[0] if not items_df.empty and (items_df["item_id"] == item_id).any() else None

    latest_instruction_detail = {}
    latest_mb_request_code = ""
    if not samples_df.empty:
        latest_instruction_detail = parse_json_text(samples_df.iloc[0]["instruction_detail_json"])
        latest_mb_request_code = str(samples_df.iloc[0].get("mb_request_code") or "")
    latest_op_detail = parse_json_text(op_df.iloc[0]["op_detail_json"]) if not op_df.empty else {}

    product_weight_values: list[float] = []
    weight_source = latest_op_detail or latest_instruction_detail
    for sample_row in samples_df.itertuples():
        instruction_detail = latest_op_detail if latest_op_detail else parse_json_text(getattr(sample_row, "instruction_detail_json", None))
        for idx in range(1, 9):
            raw_value = instruction_detail.get(f"product_weight_{idx}")
            try:
                if raw_value not in [None, ""]:
                    product_weight_values.append(float(raw_value))
            except (TypeError, ValueError):
                continue

    mb_ratio_pct = latest_op_detail.get("mb_ratio_pct")
    try:
        mb_ratio_pct = float(mb_ratio_pct)
    except (TypeError, ValueError):
        mb_ratio_pct = 0.0
    if mb_ratio_pct <= 0:
        try:
            mb_ratio_pct = float(latest_instruction_detail.get("mb_ratio", 0.0) or 0.0)
        except (TypeError, ValueError):
            mb_ratio_pct = 0.0

    return {
        "project_code": str(project_row["project_code"]) if project_row is not None else "",
        "item_code": str(item_row["item_code"]) if item_row is not None else "",
        "item_name": str(item_row["item_name"]) if item_row is not None else "",
        "process_type": str(item_row["process_type"] or "") if item_row is not None else "",
        "bom_df": bom_df[bom_df["project_id"] == project_id].copy() if not bom_df.empty else bom_df,
        "instruction_detail": latest_instruction_detail,
        "op_detail": latest_op_detail,
        "op_defaults": {
            "raw_material_id": latest_instruction_detail.get("raw_material_id"),
            "mb_request_code": latest_mb_request_code,
            "mb_ratio_pct": mb_ratio_pct,
            "ct_sec": _resolve_ct_seconds(latest_op_detail, latest_instruction_detail),
            "raw_material_used_g": weight_source.get("raw_material_used_g", 0.0),
            "mb_used_g": weight_source.get("mb_used_g", 0.0),
            "runner_weight": weight_source.get("runner_weight", 0.0),
            "avg_product_weight": round(mean(product_weight_values), 3) if product_weight_values else 0.0,
            "cavity": float(mold_df.iloc[0]["cavity"]) if not mold_df.empty and mold_df.iloc[0]["cavity"] not in [None, ""] else 1.0,
        },
    }
