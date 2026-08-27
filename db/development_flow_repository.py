from __future__ import annotations

from datetime import datetime
import json
from typing import Any

import pandas as pd

from db.runtime import execute, execute_insert, get_connection, try_delete
from domain.schemas import (
    ExperimentInstructionPayload,
    ExperimentOrderPayload,
    ExperimentSamplePayload,
    FinalReviewPayload,
    OpReviewPayload,
    QualityReviewPayload,
    RequirementDetailPayload,
)
from services.development_runtime_service import (
    get_current_product_drawing_for_item as get_current_product_drawing_for_item_runtime,
    make_order_code,
    parse_json_text,
    sync_document_revision_order_for_order,
    upsert_mb_request_for_order,
    upsert_mold_dispatch_for_order,
)
from services.inspection_plan_service import (
    apply_plan_defaults_to_instruction,
    ensure_instruction_plan,
    inspection_plan_from_details,
    parse_dict as parse_inspection_dict,
    requirement_plan,
)
from services.reference_data_service import get_document_revision_orders, get_items, get_mb_requests, get_mold_dispatch_orders
from services.reference_data_service import (
    film_options_for_project,
    get_item_bom,
    get_experiment_orders,
    get_experiment_samples,
    get_item_row as get_item_row_ref,
    get_project_by_code as get_project_by_code_ref,
    get_sample_workflow,
    item_options_for_project,
    mold_options_for_project,
    order_options_for_project,
    project_item_tree_options,
    project_options,
    raw_material_options_for_project,
    reset_cache,
)


def list_project_options() -> list[tuple[str, int]]:
    return project_options()


def get_project_by_code(project_code: str):
    return get_project_by_code_ref(project_code)


def list_item_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return item_options_for_project(project_code)


def list_project_item_tree_options(project_code: str, product_id: int | None = None) -> list[tuple[str, int]]:
    return project_item_tree_options(project_code, product_id)


def get_item_row(item_id: int | None):
    return get_item_row_ref(item_id)


def get_meta_requirement_row(meta_requirement_id: int | None):
    if not meta_requirement_id:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT meta_requirement_id, meta_code, project_id, product_id, root_item_id, tree_mode, title, status
            FROM meta_requirements
            WHERE meta_requirement_id = ?
            """,
            (int(meta_requirement_id),),
        ).fetchone()
    return row


def list_meta_requirements_for_context(project_id: int | None, product_id: int | None, tree_mode: str | None):
    if not project_id:
        return []
    with get_connection() as conn:
        if product_id:
            rows = conn.execute(
                """
                SELECT meta_requirement_id, meta_code, title, tree_mode, status
                FROM meta_requirements
                WHERE project_id = ? AND product_id = ? AND tree_mode = ?
                ORDER BY meta_requirement_id DESC
                """,
                (int(project_id), int(product_id), str(tree_mode or "기본")),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT meta_requirement_id, meta_code, title, tree_mode, status
                FROM meta_requirements
                WHERE project_id = ? AND tree_mode = ?
                ORDER BY meta_requirement_id DESC
                """,
                (int(project_id), str(tree_mode or "기본")),
            ).fetchall()
    return rows


def list_meta_requirement_lines(meta_requirement_id: int | None) -> list:
    if not meta_requirement_id:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ml.meta_line_id, ml.meta_requirement_id, ml.item_id, ml.parent_meta_line_id, ml.parent_item_id,
                   ml.line_order, ml.level_no, ml.role, ml.source_type, ml.is_virtual_root, ml.display_name,
                   ml.linked_experiment_order_id, ml.linked_required_sample_qty,
                   i.item_code, i.item_name, i.process_type
            FROM meta_requirement_lines ml
            LEFT JOIN items i ON i.item_id = ml.item_id
            WHERE ml.meta_requirement_id = ?
            ORDER BY ml.line_order, ml.meta_line_id
            """,
            (int(meta_requirement_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def list_meta_requirement_line_links() -> pd.DataFrame:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT meta_line_id, meta_requirement_id, item_id,
                   linked_experiment_order_id, linked_required_sample_qty
            FROM meta_requirement_lines
            WHERE linked_experiment_order_id IS NOT NULL
            ORDER BY meta_line_id
            """
        ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def list_requirement_ledger_rows() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT
                ml.meta_line_id AS requirement_row_id,
                ml.meta_line_id,
                ml.meta_requirement_id,
                mr.meta_code,
                mr.tree_mode,
                mr.title AS meta_title,
                mr.status AS meta_status,
                mr.project_id,
                dp.project_code,
                mr.product_id,
                pr.product_code,
                pr.product_name,
                ml.item_id,
                i.item_code,
                i.item_name,
                i.process_type,
                ml.parent_meta_line_id,
                ml.parent_item_id,
                ml.line_order,
                ml.level_no,
                ml.role,
                ml.source_type,
                ml.is_virtual_root,
                ml.display_name,
                ml.linked_experiment_order_id,
                ml.linked_required_sample_qty,
                ml.linked_injection_instruction_id,
                ml.linked_process_instruction_id,
                ml.linked_assembly_instruction_id,
                ml.linked_print_instruction_id,
                ml.linked_postprocess_instruction_id
            FROM meta_requirement_lines ml
            JOIN meta_requirements mr ON mr.meta_requirement_id = ml.meta_requirement_id
            JOIN development_projects dp ON dp.project_id = mr.project_id
            LEFT JOIN products pr ON pr.product_id = mr.product_id
            LEFT JOIN items i ON i.item_id = ml.item_id
            ORDER BY dp.project_code, pr.product_code, mr.meta_requirement_id, ml.line_order, ml.meta_line_id
            """,
            conn,
        )


def get_requirement_line_context(requirement_row_id: int | None):
    if not requirement_row_id:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                ml.meta_line_id AS requirement_row_id,
                ml.meta_line_id,
                ml.meta_requirement_id,
                mr.meta_code,
                mr.tree_mode,
                mr.project_id,
                dp.project_code,
                mr.product_id,
                pr.product_code,
                pr.product_name,
                ml.item_id,
                i.item_code,
                i.item_name,
                i.process_type,
                ml.parent_meta_line_id,
                ml.line_order,
                ml.level_no,
                ml.linked_experiment_order_id,
                ml.linked_injection_instruction_id,
                ml.linked_process_instruction_id,
                ml.linked_assembly_instruction_id,
                ml.linked_print_instruction_id,
                ml.linked_postprocess_instruction_id
            FROM meta_requirement_lines ml
            JOIN meta_requirements mr ON mr.meta_requirement_id = ml.meta_requirement_id
            JOIN development_projects dp ON dp.project_id = mr.project_id
            LEFT JOIN products pr ON pr.product_id = mr.product_id
            LEFT JOIN items i ON i.item_id = ml.item_id
            WHERE ml.meta_line_id = ?
            """,
            (int(requirement_row_id),),
        ).fetchone()
    return row


def update_requirement_line_instruction_link(
    *,
    meta_requirement_id: int | None,
    meta_line_id: int | None,
    process_type: str | None,
    experiment_instruction_id: int | None,
) -> None:
    if not meta_requirement_id or not meta_line_id or not process_type:
        return
    normalized_process = str(process_type).strip()
    if normalized_process == "사출":
        target_column = "linked_injection_instruction_id"
    elif normalized_process == "조립":
        target_column = "linked_assembly_instruction_id"
    elif normalized_process == "인쇄":
        target_column = "linked_print_instruction_id"
    elif normalized_process in {"후가공", "사상"}:
        target_column = "linked_postprocess_instruction_id"
    else:
        target_column = "linked_process_instruction_id"
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE meta_requirement_lines
            SET {target_column} = ?
            WHERE meta_requirement_id = ? AND meta_line_id = ?
            """,
            (
                int(experiment_instruction_id) if experiment_instruction_id else None,
                int(meta_requirement_id),
                int(meta_line_id),
            ),
        )
        conn.commit()
    reset_cache()


def save_meta_requirement_lines(
    *,
    meta_requirement_id: int,
    root_item_id: int,
    tree_mode: str,
    selected_item_ids: list[int],
) -> None:
    if not meta_requirement_id or not root_item_id:
        return
    with get_connection() as conn:
        if tree_mode == "조합":
            specs = _build_combo_meta_line_specs(int(root_item_id), tree_mode, [int(item_id) for item_id in selected_item_ids if item_id])
        else:
            specs = _build_basic_meta_line_specs(int(root_item_id), tree_mode)
        if not specs:
            return
        conn.execute("DELETE FROM meta_requirement_lines WHERE meta_requirement_id = ?", (int(meta_requirement_id),))
        parent_meta_line_by_item: dict[int, int] = {}
        for spec in specs:
            parent_meta_line_id = None
            parent_item_id = spec.get("parent_item_id")
            if parent_item_id:
                parent_meta_line_id = parent_meta_line_by_item.get(int(parent_item_id))
            cur = conn.execute(
                """
                INSERT INTO meta_requirement_lines (
                    meta_requirement_id, item_id, parent_meta_line_id, parent_item_id, line_order, level_no,
                    role, source_type, is_virtual_root, display_name, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(meta_requirement_id),
                    int(spec["item_id"]) if spec.get("item_id") else None,
                    parent_meta_line_id,
                    int(parent_item_id) if parent_item_id else None,
                    int(spec.get("line_order") or 0),
                    int(spec.get("level_no") or 0),
                    str(spec.get("role") or "part"),
                    str(spec.get("source_type") or tree_mode),
                    1 if spec.get("is_virtual_root") else 0,
                    spec.get("display_name"),
                    None,
                ),
            )
            if spec.get("item_id"):
                parent_meta_line_by_item[int(spec["item_id"])] = int(cur.lastrowid)
        conn.commit()
    reset_cache()


def save_meta_requirement_line_link(
    *,
    meta_requirement_id: int,
    meta_line_id: int,
    linked_experiment_order_id: int | None,
    linked_required_sample_qty: int | None,
) -> None:
    normalized_qty = (
        _normalize_positive_int(linked_required_sample_qty, field_name="추가 필요 샘플 수")
        if linked_experiment_order_id
        else None
    )
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE meta_requirement_lines
            SET linked_experiment_order_id = ?, linked_required_sample_qty = ?
            WHERE meta_requirement_id = ? AND meta_line_id = ?
            """,
            (
                int(linked_experiment_order_id) if linked_experiment_order_id else None,
                normalized_qty,
                int(meta_requirement_id),
                int(meta_line_id),
            ),
        )
        conn.commit()
    reset_cache()


def list_order_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return order_options_for_project(project_code)


def list_mold_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return mold_options_for_project(project_code)


def list_film_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return film_options_for_project(project_code)


def list_raw_material_options_for_project(project_code: str) -> list[tuple[str, int]]:
    return raw_material_options_for_project(project_code)


def list_items() -> pd.DataFrame:
    return get_items()


def get_current_product_drawing_for_item(item_id: int) -> dict | None:
    return get_current_product_drawing_for_item_runtime(item_id)


def list_experiment_orders() -> pd.DataFrame:
    return get_experiment_orders()


def list_experiment_instructions() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT ei.*, eo.order_code, eo.product_id, eo.target_due_date, eo.milestone_name,
                   it.item_code, it.item_name, dp.project_code, dp.product_name AS project_product_name
            FROM experiment_instructions ei
            JOIN experiment_orders eo ON eo.experiment_order_id = ei.experiment_order_id
            JOIN items it ON it.item_id = ei.item_id
            JOIN development_projects dp ON dp.project_id = ei.project_id
            ORDER BY ei.experiment_instruction_id DESC
            """,
            conn,
        )


def list_experiment_samples() -> pd.DataFrame:
    return get_experiment_samples()


def list_sample_workflow() -> pd.DataFrame:
    return get_sample_workflow()


def list_mb_requests() -> pd.DataFrame:
    return get_mb_requests()


def list_mold_dispatch_orders() -> pd.DataFrame:
    return get_mold_dispatch_orders()


def list_document_revision_orders() -> pd.DataFrame:
    return get_document_revision_orders()


def delete_experiment_order(experiment_order_id: int) -> tuple[bool, str]:
    with get_connection() as conn:
        order_row = conn.execute(
            """
            SELECT experiment_order_id, meta_requirement_id, meta_line_id
            FROM experiment_orders
            WHERE experiment_order_id = ?
            """,
            (int(experiment_order_id),),
        ).fetchone()
        if order_row is None:
            return False, "이미 삭제되었거나 없는 요구입니다."
        if (
            ("meta_requirement_id" in order_row.keys() and order_row["meta_requirement_id"] is not None)
            or ("meta_line_id" in order_row.keys() and order_row["meta_line_id"] is not None)
        ):
            return False, "메타에 연결된 요구는 삭제할 수 없습니다. 수정 또는 취소로 처리해 주세요."
        linked_sample = conn.execute(
            "SELECT sample_id FROM experiment_samples WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone()
        if linked_sample is not None:
            return False, "연결된 샘플이 있어 삭제할 수 없습니다. 수정 또는 취소로 처리해 주세요."
        linked_mb = conn.execute(
            "SELECT mb_request_id FROM mb_requests WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone()
        if linked_mb is not None:
            return False, "연결된 MB 의뢰가 있어 삭제할 수 없습니다. 수정 또는 취소로 처리해 주세요."
        linked_dispatch = conn.execute(
            "SELECT mold_dispatch_order_id FROM mold_dispatch_orders WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone()
        if linked_dispatch is not None:
            return False, "연결된 금형 출고 의뢰가 있어 삭제할 수 없습니다. 수정 또는 취소로 처리해 주세요."
        linked_document_order = conn.execute(
            "SELECT document_revision_order_id FROM document_revision_orders WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone()
        if linked_document_order is not None:
            return False, "연결된 도면/원화 수정 의뢰가 있어 삭제할 수 없습니다. 수정 또는 취소로 처리해 주세요."
        linked_meta_line = conn.execute(
            "SELECT meta_line_id FROM meta_requirement_lines WHERE linked_experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone()
        if linked_meta_line is not None:
            return False, "다른 조립 요구에서 재사용 중인 요구입니다. 연결을 해제한 뒤 다시 처리해 주세요."

    ok, message = try_delete(
        "DELETE FROM experiment_orders WHERE experiment_order_id = ?",
        (experiment_order_id,),
    )
    if ok:
        reset_cache()
    return ok, message


def update_experiment_order_status(experiment_order_id: int, status: str) -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE experiment_orders SET status = ? WHERE experiment_order_id = ?",
                (str(status), int(experiment_order_id)),
            )
            conn.commit()
        reset_cache()
        return True, "상태를 변경했습니다."
    except Exception:
        return False, "상태 변경 중 오류가 발생했습니다."


def _normalize_positive_int(value: Any, *, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name}이(가) 비어 있습니다.")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name}이(가) 비어 있습니다.")
        value = stripped
    try:
        normalized = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name}은(는) 1 이상의 숫자여야 합니다.") from None
    if normalized < 1:
        raise ValueError(f"{field_name}은(는) 1 이상이어야 합니다.")
    return normalized


def _normalize_dict_payload(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 형식이 올바르지 않습니다. 다시 입력해 주세요.")
    return value


def save_experiment_instruction(
    selected_row: pd.Series | None,
    *,
    payload: ExperimentInstructionPayload,
    current_user_name: str,
) -> tuple[int, str, str | None]:
    mb_request_code: str | None = None
    detail_payload = _normalize_dict_payload(payload["detail_payload"], field_name="지시 세부정보")
    required_sample_qty = _normalize_positive_int(payload["required_sample_qty"], field_name="필요 샘플 수")
    today_text = datetime.now().date().isoformat()
    order_meta_requirement_id = None
    order_meta_line_id = None
    with get_connection() as conn:
        order_row = conn.execute(
            """
            SELECT eo.order_code, eo.requirement_detail_json, eo.project_id, eo.item_id, eo.meta_requirement_id, eo.meta_line_id, i.item_code
            FROM experiment_orders eo
            LEFT JOIN items i ON i.item_id = eo.item_id
            WHERE eo.experiment_order_id = ?
            """,
            (int(payload["experiment_order_id"]),),
        ).fetchone()
        if order_row is None:
            raise ValueError("연결된 고객요구를 찾을 수 없습니다.")
        if selected_row is not None:
            linked_sample = conn.execute(
                "SELECT sample_id FROM experiment_samples WHERE experiment_instruction_id = ? LIMIT 1",
                (int(selected_row["experiment_instruction_id"]),),
            ).fetchone()
            if linked_sample is not None:
                raise ValueError("이미 샘플이 생성된 지시는 수정할 수 없습니다. 새 지시 버전을 등록해 주세요.")
        existing_detail = parse_inspection_dict(selected_row["instruction_detail_json"]) if selected_row is not None else {}
        if selected_row is not None:
            plan_version = int(existing_detail.get("plan_version") or 1)
            if existing_detail.get("inspection_plan") and not detail_payload.get("inspection_plan"):
                detail_payload["inspection_plan"] = existing_detail["inspection_plan"]
            if existing_detail.get("inspection_plan_source"):
                detail_payload["_inspection_plan_default_source"] = existing_detail["inspection_plan_source"]
        else:
            previous_instruction_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM experiment_instructions WHERE experiment_order_id = ?",
                (int(payload["experiment_order_id"]),),
            ).fetchone()
            plan_version = int(previous_instruction_count["cnt"] or 0) + 1
        requirement_detail = parse_inspection_dict(order_row["requirement_detail_json"])
        if selected_row is None and not requirement_plan(requirement_detail):
            previous_instruction = conn.execute(
                """
                SELECT experiment_instruction_id, instruction_code, instruction_detail_json
                FROM experiment_instructions
                WHERE item_id = ?
                ORDER BY experiment_instruction_id DESC
                LIMIT 1
                """,
                (int(payload["item_id"]),),
            ).fetchone()
            if previous_instruction is not None:
                previous_detail = parse_inspection_dict(previous_instruction["instruction_detail_json"])
                previous_plan = inspection_plan_from_details(previous_detail)
                detail_payload = apply_plan_defaults_to_instruction(
                    detail_payload,
                    previous_plan,
                    source_instruction_id=int(previous_instruction["experiment_instruction_id"]),
                    source_instruction_code=str(previous_instruction["instruction_code"] or ""),
                )
        detail_payload = ensure_instruction_plan(
            detail_payload,
            requirement_detail,
            plan_version=plan_version,
            source_order_id=int(payload["experiment_order_id"]),
            source_order_code=str(order_row["order_code"] or ""),
        )
        detail_json = json.dumps(detail_payload, ensure_ascii=False)
        if selected_row is None:
            base_code = str(order_row["order_code"]) if order_row is not None and order_row["order_code"] else "RQ-UNKNOWN"
            instruction_code = base_code.replace("RQ-", "IN-", 1) if base_code.startswith("RQ-") else f"IN-{base_code}"
            similar_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM experiment_instructions WHERE experiment_order_id = ?",
                (int(payload["experiment_order_id"]),),
            ).fetchone()
            next_seq = int(similar_count["cnt"]) + 1 if similar_count is not None else 1
            instruction_code = f"{instruction_code}-{next_seq:02d}"
            cur = conn.execute(
                """
                INSERT INTO experiment_instructions (
                    instruction_code, experiment_order_id, project_id, item_id, process_type, instruction_date,
                    required_sample_qty, requested_finish_date, machine_no, machine_ton,
                    instruction_detail_json, requirement_completed, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '진행중', ?, ?)
                """,
                (
                    instruction_code,
                    int(payload["experiment_order_id"]),
                    int(payload["project_id"]),
                    int(payload["item_id"]),
                    str(payload["process_type"]),
                    today_text,
                    required_sample_qty,
                    payload["requested_finish_date"],
                    str(payload["machine_no"] or ""),
                    str(payload["machine_ton"] or ""),
                    detail_json,
                    1 if payload["requirement_completed"] else 0,
                    current_user_name,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            instruction_id = int(cur.lastrowid)
        else:
            instruction_id = int(selected_row["experiment_instruction_id"])
            instruction_code = str(selected_row["instruction_code"])
            conn.execute(
                """
                UPDATE experiment_instructions
                SET required_sample_qty = ?, requested_finish_date = ?, machine_no = ?, machine_ton = ?,
                    instruction_detail_json = ?, requirement_completed = ?, status = '진행중',
                    instruction_date = COALESCE(instruction_date, ?)
                WHERE experiment_instruction_id = ?
                """,
                (
                    required_sample_qty,
                    payload["requested_finish_date"],
                    str(payload["machine_no"] or ""),
                    str(payload["machine_ton"] or ""),
                    detail_json,
                    1 if payload["requirement_completed"] else 0,
                    today_text,
                    instruction_id,
                ),
            )
        conn.execute(
            "UPDATE experiment_orders SET status = ?, requirement_date = COALESCE(requirement_date, ?) WHERE experiment_order_id = ?",
            ("완료" if payload["requirement_completed"] else "생성중", today_text, int(payload["experiment_order_id"])),
        )
        if order_row is not None:
            order_meta_requirement_id = int(order_row["meta_requirement_id"]) if "meta_requirement_id" in order_row.keys() and order_row["meta_requirement_id"] is not None else None
            order_meta_line_id = int(order_row["meta_line_id"]) if "meta_line_id" in order_row.keys() and order_row["meta_line_id"] is not None else None
        conn.commit()
    order_detail = parse_json_text(order_row["requirement_detail_json"]) if order_row is not None else {}
    if (
        str(payload["process_type"]) == "사출"
        and order_detail.get("color_required")
        and str(detail_payload.get("mb_nuance", "")).strip()
        and str(detail_payload.get("mb_supplier_name", "")).strip()
        and detail_payload.get("mb_expected_receipt_date")
        and order_row is not None
        and order_row["project_id"] is not None
        and order_row["item_id"] is not None
        and order_row["item_code"]
    ):
        upsert_mb_request_for_order(
            int(payload["experiment_order_id"]),
            int(order_row["project_id"]),
            int(order_row["item_id"]),
            str(order_row["item_code"]),
            str(detail_payload.get("mb_nuance", "")).strip(),
            order_detail.get("color_sample_exists") == "있음",
            current_user_name,
            supplier_name=str(detail_payload.get("mb_supplier_name", "")).strip(),
            expected_receipt_date=str(detail_payload.get("mb_expected_receipt_date") or ""),
            sample_received=bool(detail_payload.get("mb_sample_received", False)),
            purchase_requested=False,
        )
        with get_connection() as conn:
            mb_request_row = conn.execute(
                """
                SELECT mb_request_id
                FROM mb_requests
                WHERE experiment_order_id = ?
                ORDER BY mb_request_id DESC
                LIMIT 1
                """,
                (int(payload["experiment_order_id"]),),
            ).fetchone()
            if mb_request_row is not None and mb_request_row["mb_request_id"] is not None:
                detail_payload["mb_request_id"] = int(mb_request_row["mb_request_id"])
                detail_json = json.dumps(detail_payload, ensure_ascii=False)
                conn.execute(
                    """
                    UPDATE experiment_instructions
                    SET instruction_detail_json = ?
                    WHERE experiment_instruction_id = ?
                    """,
                    (detail_json, instruction_id),
                )
                mb_code_row = conn.execute(
                    """
                    SELECT request_code
                    FROM mb_requests
                    WHERE mb_request_id = ?
                    """,
                    (int(mb_request_row["mb_request_id"]),),
                ).fetchone()
                if mb_code_row is not None and mb_code_row["request_code"]:
                    mb_request_code = str(mb_code_row["request_code"])
                conn.commit()
    update_requirement_line_instruction_link(
        meta_requirement_id=order_meta_requirement_id,
        meta_line_id=order_meta_line_id,
        process_type=str(payload["process_type"]),
        experiment_instruction_id=instruction_id,
    )
    reset_cache()
    return instruction_id, instruction_code, mb_request_code


def delete_experiment_instruction(experiment_instruction_id: int) -> tuple[bool, str]:
    with get_connection() as conn:
        instruction_row = conn.execute(
            """
            SELECT ei.process_type, eo.meta_requirement_id, eo.meta_line_id
            FROM experiment_instructions ei
            JOIN experiment_orders eo ON eo.experiment_order_id = ei.experiment_order_id
            WHERE ei.experiment_instruction_id = ?
            """,
            (int(experiment_instruction_id),),
        ).fetchone()
    with get_connection() as conn:
        linked_sample = conn.execute(
            "SELECT sample_id FROM experiment_samples WHERE experiment_instruction_id = ? LIMIT 1",
            (int(experiment_instruction_id),),
        ).fetchone()
        if linked_sample is not None:
            return False, "연결된 실험이 있어 삭제할 수 없습니다."
    ok, message = try_delete(
        "DELETE FROM experiment_instructions WHERE experiment_instruction_id = ?",
        (int(experiment_instruction_id),),
    )
    if ok:
        if instruction_row is not None:
            update_requirement_line_instruction_link(
                meta_requirement_id=int(instruction_row["meta_requirement_id"]) if instruction_row["meta_requirement_id"] is not None else None,
                meta_line_id=int(instruction_row["meta_line_id"]) if instruction_row["meta_line_id"] is not None else None,
                process_type=str(instruction_row["process_type"] or ""),
                experiment_instruction_id=None,
            )
        reset_cache()
    return ok, message


def get_experiment_order_usage(experiment_order_id: int) -> dict[str, bool]:
    with get_connection() as conn:
        order_row = conn.execute(
            """
            SELECT meta_requirement_id, meta_line_id
            FROM experiment_orders
            WHERE experiment_order_id = ?
            """,
            (int(experiment_order_id),),
        ).fetchone()
        if order_row is None:
            return {
                "has_meta": False,
                "has_meta_line": False,
                "has_sample": False,
                "has_mb_request": False,
                "has_mold_dispatch": False,
                "has_document_revision": False,
            }
        has_sample = conn.execute(
            "SELECT 1 FROM experiment_samples WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone() is not None
        has_mb_request = conn.execute(
            "SELECT 1 FROM mb_requests WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone() is not None
        has_mold_dispatch = conn.execute(
            "SELECT 1 FROM mold_dispatch_orders WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone() is not None
        has_document_revision = conn.execute(
            "SELECT 1 FROM document_revision_orders WHERE experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone() is not None
        has_linked_meta_line = conn.execute(
            "SELECT 1 FROM meta_requirement_lines WHERE linked_experiment_order_id = ? LIMIT 1",
            (int(experiment_order_id),),
        ).fetchone() is not None
    return {
        "has_meta": bool(order_row["meta_requirement_id"]) if "meta_requirement_id" in order_row.keys() else False,
        "has_meta_line": bool(order_row["meta_line_id"]) if "meta_line_id" in order_row.keys() else False,
        "has_sample": has_sample,
        "has_mb_request": has_mb_request,
        "has_mold_dispatch": has_mold_dispatch,
        "has_document_revision": has_document_revision,
        "has_linked_meta_line": has_linked_meta_line,
    }


def _make_meta_requirement_code(conn) -> str:
    row = conn.execute(
        "SELECT meta_code FROM meta_requirements WHERE meta_code LIKE 'META-%' ORDER BY meta_requirement_id DESC LIMIT 1"
    ).fetchone()
    last_no = 0
    if row is not None and row["meta_code"]:
        try:
            last_no = int(str(row["meta_code"]).split("-")[-1])
        except ValueError:
            last_no = 0
    return f"META-{last_no + 1:04d}"


def _ensure_meta_requirement_id(
    conn,
    *,
    selected_row: pd.Series | None,
    payload: ExperimentOrderPayload,
    current_user_name: str,
) -> int | None:
    detail_payload: RequirementDetailPayload = payload["detail_payload"]
    meta_scope = str(detail_payload.get("_meta_scope") or "")
    if meta_scope == "공정품":
        if selected_row is not None and "meta_requirement_id" in selected_row.index and pd.notna(selected_row["meta_requirement_id"]):
            return int(selected_row["meta_requirement_id"])
        return None
    requested_meta_id = detail_payload.get("_meta_requirement_id")
    if requested_meta_id:
        return int(requested_meta_id)
    if selected_row is not None and "meta_requirement_id" in selected_row.index and pd.notna(selected_row["meta_requirement_id"]):
        return int(selected_row["meta_requirement_id"])
    force_new_meta = bool(detail_payload.get("_meta_force_new"))

    project_id = payload["project_id"]
    product_id = detail_payload.get("_meta_product_id")
    tree_mode = str(detail_payload.get("_meta_tree_mode") or "기본")
    root_item_id = detail_payload.get("_meta_root_item_id") or payload["item_id"]
    title = str(detail_payload.get("_meta_title") or payload["experiment_goal"] or "").strip()
    if not title:
        title = f"{payload['item_code']} {meta_scope or tree_mode}".strip()

    if not project_id:
        return None

    if not force_new_meta:
        if product_id:
            existing = conn.execute(
                """
                SELECT meta_requirement_id
                FROM meta_requirements
                WHERE project_id = ? AND product_id = ? AND tree_mode = ?
                ORDER BY meta_requirement_id DESC
                LIMIT 1
                """,
                (project_id, int(product_id), tree_mode),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT meta_requirement_id
                FROM meta_requirements
                WHERE project_id = ? AND tree_mode = ?
                ORDER BY meta_requirement_id DESC
                LIMIT 1
                """,
                (project_id, tree_mode),
            ).fetchone()
        if existing is not None and pd.notna(existing["meta_requirement_id"]):
            return int(existing["meta_requirement_id"])

    meta_code = _make_meta_requirement_code(conn)
    cur = conn.execute(
        """
        INSERT INTO meta_requirements (
            meta_code, project_id, product_id, root_item_id, tree_mode, title, status, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, '요구등록', ?, ?)
        """,
        (
            meta_code,
            project_id,
            int(product_id) if product_id else None,
            int(root_item_id) if root_item_id else None,
            tree_mode,
            title,
            current_user_name,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return int(cur.lastrowid)


def _build_basic_meta_line_specs(root_item_id: int, tree_mode: str) -> list[dict[str, Any]]:
    items_df = get_items()
    bom_df = get_item_bom()
    if items_df.empty:
        return []
    item_rows = items_df[items_df["item_id"] == int(root_item_id)]
    if item_rows.empty:
        return []
    specs: list[dict[str, Any]] = []
    order_no = 1
    root_row = item_rows.iloc[0]
    specs.append(
        {
            "item_id": int(root_item_id),
            "parent_item_id": None,
            "level_no": 0,
            "role": "root",
            "source_type": tree_mode,
            "is_virtual_root": 0,
            "display_name": f"{root_row['item_code']} | {root_row['item_name']}",
            "line_order": order_no,
        }
    )
    order_no += 1
    project_bom = bom_df[bom_df["project_id"] == int(root_row["project_id"])] if not bom_df.empty and "project_id" in bom_df.columns and pd.notna(root_row.get("project_id")) else bom_df

    def walk(parent_item_id: int, level_no: int) -> None:
        nonlocal order_no
        child_rows = project_bom[project_bom["parent_item_id"] == int(parent_item_id)] if not project_bom.empty else project_bom
        for _, child_row in child_rows.iterrows():
            child_item_id = int(child_row["child_item_id"])
            child_item_rows = items_df[items_df["item_id"] == child_item_id]
            if child_item_rows.empty:
                continue
            child_item = child_item_rows.iloc[0]
            specs.append(
                {
                    "item_id": child_item_id,
                    "parent_item_id": int(parent_item_id),
                    "level_no": level_no,
                    "role": "part",
                    "source_type": tree_mode,
                    "is_virtual_root": 0,
                    "display_name": f"{child_item['item_code']} | {child_item['item_name']}",
                    "line_order": order_no,
                }
            )
            order_no += 1
            walk(child_item_id, level_no + 1)

    walk(int(root_item_id), 1)
    return specs


def _build_combo_meta_line_specs(root_item_id: int, tree_mode: str, selected_item_ids: list[int]) -> list[dict[str, Any]]:
    items_df = get_items()
    if items_df.empty:
        return []
    root_rows = items_df[items_df["item_id"] == int(root_item_id)]
    if root_rows.empty:
        return []
    specs: list[dict[str, Any]] = []
    order_no = 1
    root_row = root_rows.iloc[0]
    specs.append(
        {
            "item_id": int(root_item_id),
            "parent_item_id": None,
            "level_no": 0,
            "role": "root",
            "source_type": tree_mode,
            "is_virtual_root": 1,
            "display_name": f"{root_row['item_code']} | {root_row['item_name']}",
            "line_order": order_no,
        }
    )
    order_no += 1
    seen: set[int] = set()
    for item_id in selected_item_ids:
        if int(item_id) == int(root_item_id) or int(item_id) in seen:
            continue
        seen.add(int(item_id))
        item_rows = items_df[items_df["item_id"] == int(item_id)]
        if item_rows.empty:
            continue
        item_row = item_rows.iloc[0]
        specs.append(
            {
                "item_id": int(item_id),
                "parent_item_id": int(root_item_id),
                "level_no": 1,
                "role": "part",
                "source_type": tree_mode,
                "is_virtual_root": 0,
                "display_name": f"{item_row['item_code']} | {item_row['item_name']}",
                "line_order": order_no,
            }
        )
        order_no += 1
    return specs


def _replace_meta_requirement_lines(conn, *, meta_requirement_id: int, payload: ExperimentOrderPayload) -> None:
    detail_payload: RequirementDetailPayload = payload["detail_payload"]
    root_item_id = int(detail_payload.get("_meta_root_item_id") or payload["item_id"] or 0)
    if not root_item_id:
        return
    tree_mode = str(detail_payload.get("_meta_tree_mode") or "기본")
    selected_item_ids = [
        int(item_id)
        for item_id in (detail_payload.get("_meta_selected_item_ids") or [])
        if item_id
    ]
    if tree_mode == "조합":
        specs = _build_combo_meta_line_specs(root_item_id, tree_mode, selected_item_ids)
    else:
        specs = _build_basic_meta_line_specs(root_item_id, tree_mode)
    if not specs:
        return
    existing_rows = conn.execute(
        """
        SELECT meta_line_id, item_id
        FROM meta_requirement_lines
        WHERE meta_requirement_id = ?
        ORDER BY line_order, meta_line_id
        """,
        (int(meta_requirement_id),),
    ).fetchall()
    existing_line_id_by_item: dict[int, int] = {}
    for row in existing_rows:
        if row["item_id"] is None:
            continue
        item_key = int(row["item_id"])
        existing_line_id_by_item.setdefault(item_key, int(row["meta_line_id"]))

    parent_meta_line_by_item: dict[int, int] = {}
    used_line_ids: set[int] = set()
    for spec in specs:
        parent_meta_line_id = None
        parent_item_id = spec.get("parent_item_id")
        if parent_item_id:
            parent_meta_line_id = parent_meta_line_by_item.get(int(parent_item_id))
        item_key = int(spec["item_id"]) if spec.get("item_id") else None
        existing_line_id = existing_line_id_by_item.get(item_key) if item_key else None
        if existing_line_id:
            conn.execute(
                """
                UPDATE meta_requirement_lines
                SET parent_meta_line_id = ?, parent_item_id = ?, line_order = ?, level_no = ?,
                    role = ?, source_type = ?, is_virtual_root = ?, display_name = ?, notes = ?
                WHERE meta_line_id = ?
                """,
                (
                    parent_meta_line_id,
                    int(parent_item_id) if parent_item_id else None,
                    int(spec.get("line_order") or 0),
                    int(spec.get("level_no") or 0),
                    str(spec.get("role") or "part"),
                    str(spec.get("source_type") or tree_mode),
                    1 if spec.get("is_virtual_root") else 0,
                    spec.get("display_name"),
                    None,
                    int(existing_line_id),
                ),
            )
            current_meta_line_id = int(existing_line_id)
        else:
            cur = conn.execute(
                """
                INSERT INTO meta_requirement_lines (
                    meta_requirement_id, item_id, parent_meta_line_id, parent_item_id, line_order, level_no,
                    role, source_type, is_virtual_root, display_name, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(meta_requirement_id),
                    item_key,
                    parent_meta_line_id,
                    int(parent_item_id) if parent_item_id else None,
                    int(spec.get("line_order") or 0),
                    int(spec.get("level_no") or 0),
                    str(spec.get("role") or "part"),
                    str(spec.get("source_type") or tree_mode),
                    1 if spec.get("is_virtual_root") else 0,
                    spec.get("display_name"),
                    None,
                ),
            )
            current_meta_line_id = int(cur.lastrowid)
        if spec.get("item_id"):
            parent_meta_line_by_item[int(spec["item_id"])] = current_meta_line_id
        used_line_ids.add(current_meta_line_id)

    obsolete_line_ids = [
        int(row["meta_line_id"])
        for row in existing_rows
        if int(row["meta_line_id"]) not in used_line_ids
    ]
    if obsolete_line_ids:
        placeholders = ",".join("?" for _ in obsolete_line_ids)
        conn.execute(
            f"""
            UPDATE experiment_orders
            SET meta_line_id = NULL
            WHERE meta_requirement_id = ? AND meta_line_id IN ({placeholders})
            """,
            (int(meta_requirement_id), *obsolete_line_ids),
        )
        conn.execute(
            f"DELETE FROM meta_requirement_lines WHERE meta_line_id IN ({placeholders})",
            tuple(obsolete_line_ids),
        )


def _ensure_meta_line_id(
    conn,
    *,
    selected_row: pd.Series | None,
    payload: ExperimentOrderPayload,
    meta_requirement_id: int | None,
) -> int | None:
    if not meta_requirement_id:
        return None
    detail_payload: RequirementDetailPayload = payload["detail_payload"]
    requested_meta_line_id = detail_payload.get("_meta_line_id")
    if requested_meta_line_id:
        return int(requested_meta_line_id)
    row = conn.execute(
        """
        SELECT meta_line_id
        FROM meta_requirement_lines
        WHERE meta_requirement_id = ? AND item_id = ?
        ORDER BY line_order, meta_line_id
        LIMIT 1
        """,
        (int(meta_requirement_id), int(payload["item_id"])),
    ).fetchone()
    if row is not None and pd.notna(row["meta_line_id"]):
        return int(row["meta_line_id"])
    if selected_row is not None and "meta_line_id" in selected_row.index and pd.notna(selected_row["meta_line_id"]):
        return int(selected_row["meta_line_id"])
    return None


def save_experiment_order(
    selected_row: pd.Series | None,
    *,
    payload: ExperimentOrderPayload,
    current_user_name: str,
) -> tuple[int, str, int | None]:
    project_id = payload["project_id"]
    product_id = payload.get("product_id")
    item_id = payload["item_id"]
    item_code = payload["item_code"]
    process_type = payload["process_type"]
    mold_dispatch_required = payload["mold_dispatch_required"]
    detail_payload: RequirementDetailPayload = _normalize_dict_payload(
        payload["detail_payload"],
        field_name="요구 세부정보",
    )
    required_sample_qty = _normalize_positive_int(payload["required_sample_qty"], field_name="필요 샘플 수")
    payload["detail_payload"] = detail_payload
    payload["required_sample_qty"] = required_sample_qty
    today_text = datetime.now().date().isoformat()
    with get_connection() as conn:
        meta_requirement_id = _ensure_meta_requirement_id(
            conn,
            selected_row=selected_row,
            payload=payload,
            current_user_name=current_user_name,
        )
        if meta_requirement_id:
            meta_scope = str(detail_payload.get("_meta_scope") or "")
            meta_tree_mode = str(detail_payload.get("_meta_tree_mode") or "기본")
            is_root_save = bool(
                payload["process_type"] == "조립"
                and payload["item_id"] == (detail_payload.get("_meta_root_item_id") or payload["item_id"])
            )
            should_refresh_meta_lines = bool(
                meta_scope == "조립품"
                and is_root_save
            )
            if should_refresh_meta_lines:
                _replace_meta_requirement_lines(
                    conn,
                    meta_requirement_id=int(meta_requirement_id),
                    payload=payload,
                )
        meta_line_id = _ensure_meta_line_id(
            conn,
            selected_row=selected_row,
            payload=payload,
            meta_requirement_id=meta_requirement_id,
        )
        if meta_requirement_id and meta_line_id:
            conn.execute(
                """
                UPDATE meta_requirement_lines
                SET linked_experiment_order_id = NULL, linked_required_sample_qty = NULL
                WHERE meta_requirement_id = ? AND meta_line_id = ?
                """,
                (int(meta_requirement_id), int(meta_line_id)),
            )
        requirement_checks_json = json.dumps(payload["requirement_checks"], ensure_ascii=False)
        detail_json = json.dumps(detail_payload, ensure_ascii=False)
        requested_by = str(payload["requested_by"] or current_user_name).strip() or current_user_name
        if selected_row is None:
            order_item_code = item_code
            if (
                process_type == "조립"
                and str(detail_payload.get("_meta_scope") or "") == "조립품"
                and str(detail_payload.get("_meta_tree_mode") or "") == "조합"
                and int(payload["item_id"]) == int(detail_payload.get("_meta_root_item_id") or payload["item_id"])
            ):
                order_item_code = "META"
            order_code = make_order_code(
                order_item_code,
                "RQ",
                str(detail_payload.get("revision_variant_no") or ""),
                str(detail_payload.get("material_variant_no") or ""),
            )
            cur = conn.execute(
                """
                INSERT INTO experiment_orders (
                    order_code, meta_requirement_id, meta_line_id, project_id, product_id, item_id, process_type, milestone_name, base_drawing_revision,
                    drawing_receipt_status, mold_pre_update, mold_dispatch_required, target_due_date, requirement_date,
                    milestone_due_date, required_sample_qty, experiment_goal, success_criteria,
                    request_notes, requirement_checks_json, requirement_detail_json,
                    requested_by, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '진행중', ?, ?)
                """,
                (
                    order_code,
                    meta_requirement_id,
                    meta_line_id,
                    project_id,
                    int(product_id) if product_id else None,
                    item_id,
                    process_type,
                    payload["milestone_name"],
                    payload["base_drawing_revision"],
                    payload["drawing_receipt_status"],
                    1 if payload["mold_pre_update"] else 0,
                    1 if mold_dispatch_required else 0,
                    payload["target_due_date"],
                    today_text,
                    payload["milestone_due_date"],
                    required_sample_qty,
                    payload["experiment_goal"],
                    payload["success_criteria"],
                    payload["request_notes"],
                    requirement_checks_json,
                    detail_json,
                    requested_by,
                    current_user_name,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            order_id = int(cur.lastrowid)
            conn.commit()
        else:
            order_code = str(selected_row["order_code"])
            order_id = int(selected_row["experiment_order_id"])
            conn.execute(
                """
                UPDATE experiment_orders
                SET meta_requirement_id = ?, meta_line_id = ?, project_id = ?, product_id = ?, item_id = ?, process_type = ?, milestone_name = ?, base_drawing_revision = ?,
                    drawing_receipt_status = ?, mold_pre_update = ?, mold_dispatch_required = ?, target_due_date = ?,
                    milestone_due_date = ?, required_sample_qty = ?, experiment_goal = ?, success_criteria = ?,
                    request_notes = ?, requirement_checks_json = ?, requirement_detail_json = ?, requested_by = ?, status = '진행중',
                    requirement_date = COALESCE(requirement_date, ?)
                WHERE experiment_order_id = ?
                """,
                (
                    meta_requirement_id,
                    meta_line_id,
                    project_id,
                    int(product_id) if product_id else None,
                    item_id,
                    process_type,
                    payload["milestone_name"],
                    payload["base_drawing_revision"],
                    payload["drawing_receipt_status"],
                    1 if payload["mold_pre_update"] else 0,
                    1 if mold_dispatch_required else 0,
                    payload["target_due_date"],
                    payload["milestone_due_date"],
                    required_sample_qty,
                    payload["experiment_goal"],
                    payload["success_criteria"],
                    payload["request_notes"],
                    requirement_checks_json,
                    detail_json,
                    requested_by,
                    today_text,
                    order_id,
                ),
            )
            conn.commit()
        if meta_requirement_id and meta_line_id:
            conn.execute(
                """
                UPDATE meta_requirement_lines
                SET linked_experiment_order_id = ?, linked_required_sample_qty = ?
                WHERE meta_requirement_id = ? AND meta_line_id = ?
                """,
                (
                    int(order_id),
                    int(required_sample_qty),
                    int(meta_requirement_id),
                    int(meta_line_id),
                ),
            )
            conn.commit()

    if process_type == "사출" and mold_dispatch_required:
        items_df = get_items()
        item_rows = items_df[items_df["item_id"] == item_id] if not items_df.empty else items_df
        item_row = item_rows.iloc[0] if not item_rows.empty else None
        upsert_mold_dispatch_for_order(
            order_id,
            project_id,
            item_id,
            item_code,
            int(item_row["primary_mold_id"]) if item_row is not None and pd.notna(item_row["primary_mold_id"]) else None,
            current_user_name,
        )
    items_df = get_items()
    item_rows = items_df[items_df["item_id"] == item_id] if not items_df.empty else items_df
    item_row = item_rows.iloc[0] if not item_rows.empty else None
    drawing_required = bool(process_type == "사출" and detail_payload.get("product_drawing_change_required"))
    film_required = bool(process_type == "인쇄" and detail_payload.get("film_revision_required"))
    if drawing_required or film_required:
        sync_document_revision_order_for_order(
            order_id,
            project_id=project_id,
            item_id=item_id,
            item_code=item_code,
            document_type="도면" if drawing_required else "원화",
            base_document_id=(
                int(item_row["product_drawing_id"])
                if drawing_required and item_row is not None and "product_drawing_id" in item_row.index and pd.notna(item_row["product_drawing_id"])
                else int(item_row["base_print_film_id"])
                if film_required and item_row is not None and "base_print_film_id" in item_row.index and pd.notna(item_row["base_print_film_id"])
                else None
            ),
            required=True,
            created_by=current_user_name,
        )
    else:
        sync_document_revision_order_for_order(
            order_id,
            project_id=project_id,
            item_id=item_id,
            item_code=item_code,
            document_type="도면" if process_type == "사출" else "원화",
            base_document_id=None,
            required=False,
            created_by=current_user_name,
        )
    reset_cache()
    return order_id, order_code, meta_requirement_id


def delete_experiment_sample(sample_id: int) -> tuple[bool, str]:
    ok, message = try_delete(
        "DELETE FROM experiment_samples WHERE sample_id = ?",
        (sample_id,),
    )
    if ok:
        reset_cache()
    return ok, message


def save_experiment_sample(
    selected_row: pd.Series | None,
    *,
    payload: ExperimentSamplePayload,
    linked_mb_request_row: pd.Series | None,
    linked_mold_dispatch_row: pd.Series | None,
    project_molds: list[tuple[str, int]],
    project_films: list[tuple[str, int]],
    current_user_name: str,
) -> int:
    process_type = payload["process_type"]
    order_detail = payload["order_detail"]
    sample_detail = _normalize_dict_payload(payload["detail_payload"], field_name="샘플 지시 스냅샷")
    sample_detail["inspection_plan_snapshot"] = inspection_plan_from_details(sample_detail, order_detail)
    if process_type == "사출" and order_detail.get("mold_dispatch_required") and linked_mold_dispatch_row is not None:
        execute(
            """
            UPDATE mold_dispatch_orders
            SET dispatch_reason = ?, sample_request_date = ?, status = ?
            WHERE mold_dispatch_order_id = ?
            """,
            (
                payload["mold_dispatch_note"].strip(),
                payload["mold_sample_request_date"],
                "출고지시",
                int(linked_mold_dispatch_row["mold_dispatch_order_id"]),
            ),
        )
    if process_type == "사출" and order_detail.get("product_drawing_change_required"):
        execute(
            """
            UPDATE experiment_orders
            SET base_drawing_revision = ?, drawing_receipt_status = ?
            WHERE experiment_order_id = ?
            """,
            (
                payload["base_drawing_revision"].strip(),
                payload["drawing_receipt_status"],
                payload["order_id"],
            ),
        )

    db_payload = (
        payload["order_id"],
        payload["experiment_instruction_id"],
        payload["sample_seq"],
        payload["sample_name"],
        payload["variation_note"],
        int(linked_mb_request_row["mb_request_id"]) if linked_mb_request_row is not None else None,
        dict(project_molds).get(payload["mold_label"]) if payload["mold_label"] else None,
        dict(project_films).get(payload["film_label"]) if payload["film_label"] else None,
        payload["customer_delivery_date"],
        payload["customer_result_date"],
        payload["customer_result"],
        payload["customer_result_notes"],
        json.dumps(payload["instruction_checks"], ensure_ascii=False),
        json.dumps(sample_detail, ensure_ascii=False),
    )
    if selected_row is None:
        existing_sample_row = None
        if payload["sample_code"]:
            with get_connection() as conn:
                existing_sample_row = conn.execute(
                    """
                    SELECT sample_id
                    FROM experiment_samples
                    WHERE sample_code = ?
                    LIMIT 1
                    """,
                    (str(payload["sample_code"]),),
                ).fetchone()
        if existing_sample_row is not None:
            execute(
                """
                UPDATE experiment_samples
                SET experiment_order_id = ?, experiment_instruction_id = ?, sample_seq = ?, sample_name = ?, variation_note = ?,
                    mb_request_id = ?, used_mold_id = ?, used_film_id = ?, customer_delivery_date = ?, customer_result_date = ?,
                    customer_result = ?, customer_result_notes = ?, instruction_checks_json = ?, instruction_detail_json = ?
                WHERE sample_id = ?
                """,
                (*db_payload, int(existing_sample_row["sample_id"])),
            )
            sample_id = int(existing_sample_row["sample_id"])
        else:
            with get_connection() as conn:
                cur = conn.execute(
                """
                INSERT INTO experiment_samples (
                    experiment_order_id, experiment_instruction_id, sample_code, sample_seq, sample_name, variation_note,
                    mb_request_id, used_mold_id, used_film_id, customer_delivery_date, customer_result_date,
                    customer_result, customer_result_notes, instruction_checks_json, instruction_detail_json,
                    status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '실험지시등록', ?, ?)
                """,
                    (
                        payload["order_id"],
                        payload["experiment_instruction_id"],
                        payload["sample_code"],
                        payload["sample_seq"],
                        payload["sample_name"],
                        payload["variation_note"],
                        int(linked_mb_request_row["mb_request_id"]) if linked_mb_request_row is not None else None,
                        dict(project_molds).get(payload["mold_label"]) if payload["mold_label"] else None,
                        dict(project_films).get(payload["film_label"]) if payload["film_label"] else None,
                        payload["customer_delivery_date"],
                        payload["customer_result_date"],
                        payload["customer_result"],
                        payload["customer_result_notes"],
                        json.dumps(payload["instruction_checks"], ensure_ascii=False),
                        json.dumps(sample_detail, ensure_ascii=False),
                        current_user_name,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                conn.commit()
                sample_id = int(cur.lastrowid)
    else:
        execute(
            """
            UPDATE experiment_samples
            SET experiment_order_id = ?, experiment_instruction_id = ?, sample_seq = ?, sample_name = ?, variation_note = ?,
                mb_request_id = ?, used_mold_id = ?, used_film_id = ?, customer_delivery_date = ?, customer_result_date = ?,
                customer_result = ?, customer_result_notes = ?, instruction_checks_json = ?, instruction_detail_json = ?
            WHERE sample_id = ?
            """,
            (*db_payload, int(selected_row["sample_id"])),
    )
        sample_id = int(selected_row["sample_id"])
    reset_cache()
    return sample_id


def save_op_review(
    *,
    payload: OpReviewPayload,
    current_user_name: str,
) -> None:
    op_detail_json = json.dumps(
        {**payload["detail_payload"], "condition_input": payload["condition_input"], "first_measurement": payload["first_measurement"]},
        ensure_ascii=False,
    )
    today_text = datetime.now().date().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sample_op_reviews (
                sample_id, mold_ready, material_ready, film_ready, drawing_ready,
                condition_input, first_measurement, op_detail_json, first_action, checked_by, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sample_id) DO UPDATE SET
                mold_ready=excluded.mold_ready,
                material_ready=excluded.material_ready,
                film_ready=excluded.film_ready,
                drawing_ready=excluded.drawing_ready,
                condition_input=excluded.condition_input,
                first_measurement=excluded.first_measurement,
                op_detail_json=excluded.op_detail_json,
                first_action=excluded.first_action,
                checked_by=excluded.checked_by,
                checked_at=excluded.checked_at
            """,
            (
                payload["sample_id"],
                1 if payload["mold_ready"] else 0,
                1 if payload["material_ready"] else 0,
                1 if payload["film_ready"] else 0,
                1 if payload["drawing_ready"] else 0,
                payload["condition_input"],
                payload["first_measurement"],
                op_detail_json,
                payload["first_action"],
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.execute(
            "UPDATE experiment_samples SET status = '실험완료', experiment_date = COALESCE(experiment_date, ?) WHERE sample_id = ?",
            (today_text, payload["sample_id"]),
        )

        produced_qty = payload["detail_payload"].get("produced_sample_qty")
        try:
            produced_qty_value = float(produced_qty) if produced_qty is not None else 0.0
        except (TypeError, ValueError):
            produced_qty_value = 0.0
        if produced_qty_value > 0:
            completed_move_cnt = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM postprocess_item_moves
                WHERE sample_id = ?
                  AND status IN ('출고완료', '입고완료')
                """,
                (payload["sample_id"],),
            ).fetchone()
            adjustment_cnt = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM sample_inventory_adjustments
                WHERE sample_id = ?
                """,
                (payload["sample_id"],),
            ).fetchone()
            if int(completed_move_cnt["cnt"] or 0) == 0 and int(adjustment_cnt["cnt"] or 0) == 0:
                conn.execute(
                    """
                    UPDATE sample_inventory
                    SET qty_on_hand = ?, updated_by = ?, updated_at = ?
                    WHERE sample_id = ?
                    """,
                    (
                        produced_qty_value,
                        current_user_name,
                        datetime.now().isoformat(timespec="seconds"),
                        payload["sample_id"],
                    ),
                )
        conn.commit()
    reset_cache()


def save_quality_review(
    *,
    payload: QualityReviewPayload,
    current_user_name: str,
) -> None:
    today_text = datetime.now().date().isoformat()
    execute(
        """
        INSERT INTO sample_quality_reviews (
            sample_id, quality_review_date, second_measurement, after_24h_measurement,
            post_process_review, assembly_review, quality_comment,
            reviewed_by, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sample_id) DO UPDATE SET
            quality_review_date=COALESCE(sample_quality_reviews.quality_review_date, excluded.quality_review_date),
            second_measurement=excluded.second_measurement,
            after_24h_measurement=excluded.after_24h_measurement,
            post_process_review=excluded.post_process_review,
            assembly_review=excluded.assembly_review,
            quality_comment=excluded.quality_comment,
            reviewed_by=excluded.reviewed_by,
            reviewed_at=excluded.reviewed_at
        """,
        (
            payload["sample_id"],
            today_text,
            payload["second_measurement"],
            payload["after_24h_measurement"],
            payload["post_process_review"],
            payload["assembly_review"],
            payload["quality_comment"],
            current_user_name,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    execute("UPDATE experiment_samples SET status = '품질검토완료' WHERE sample_id = ?", (payload["sample_id"],))
    reset_cache()


def save_final_review(
    *,
    payload: FinalReviewPayload,
    current_user_name: str,
) -> None:
    today_text = datetime.now().date().isoformat()
    execute(
        """
        INSERT INTO sample_final_reviews (
            sample_id, final_review_date, final_comment, final_action, approval_status, reviewed_by, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sample_id) DO UPDATE SET
            final_review_date=COALESCE(sample_final_reviews.final_review_date, excluded.final_review_date),
            final_comment=excluded.final_comment,
            final_action=excluded.final_action,
            approval_status=excluded.approval_status,
            reviewed_by=excluded.reviewed_by,
            reviewed_at=excluded.reviewed_at
        """,
        (
            payload["sample_id"],
            today_text,
            payload["final_comment"],
            payload["final_action"],
            payload["approval_status"],
            current_user_name,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    execute("UPDATE experiment_samples SET status = ? WHERE sample_id = ?", (payload["approval_status"], payload["sample_id"]))
    reset_cache()
