from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime

import pandas as pd

from db.runtime import execute, get_connection, try_delete
from services.reference_data_service import (
    get_experiment_samples,
    get_mb_receipts,
    get_mb_requests,
    get_mold_dispatch_orders,
    get_molds,
    get_postprocess_item_moves,
    get_sample_inventory,
    project_options,
    reset_cache,
)


def _wms_log(step: str, **payload) -> None:
    print(f"[WMS] {step}", payload)


def list_mold_dispatch_orders() -> pd.DataFrame:
    return get_mold_dispatch_orders()


def list_molds() -> pd.DataFrame:
    return get_molds()


def execute_mold_dispatch(
    mold_dispatch_order_id: int,
    *,
    mold_id: int | None,
    sample_request_date: str | None,
    dispatch_date: str | None,
    modification_note: str,
) -> None:
    execute(
        """
        UPDATE mold_dispatch_orders
        SET mold_id = ?, sample_request_date = ?, dispatch_date = ?, modification_note = ?, status = '출고완료'
        WHERE mold_dispatch_order_id = ?
        """,
        (
            mold_id,
            sample_request_date,
            dispatch_date,
            modification_note,
            mold_dispatch_order_id,
        ),
    )
    reset_cache()


def complete_mold_dispatch_receipt(
    mold_dispatch_order_id: int,
    *,
    receipt_date: str,
    modification_note: str,
) -> None:
    execute(
        """
        UPDATE mold_dispatch_orders
        SET receipt_date = ?, modification_note = ?, status = '입고완료'
        WHERE mold_dispatch_order_id = ?
        """,
        (
            receipt_date,
            modification_note,
            mold_dispatch_order_id,
        ),
    )
    reset_cache()


def list_mb_requests() -> pd.DataFrame:
    return get_mb_requests()


def sync_mb_request_receipt_statuses() -> None:
    execute(
        """
        UPDATE mb_requests
        SET status = '입고완료'
        WHERE purchase_requested = 1
          AND EXISTS (
              SELECT 1
              FROM mb_receipts rc
              WHERE rc.mb_request_id = mb_requests.mb_request_id
          )
        """
    )
    execute(
        """
        UPDATE mb_requests
        SET status = '구매지시생성'
        WHERE purchase_requested = 1
          AND NOT EXISTS (
              SELECT 1
              FROM mb_receipts rc
              WHERE rc.mb_request_id = mb_requests.mb_request_id
          )
          AND COALESCE(status, '') = '입고완료'
        """
    )
    reset_cache()


def save_mb_request_consultation(
    mb_request_id: int,
    *,
    sample_sent: bool,
    supplier_name: str,
    consultation_note: str,
    expected_receipt_date: str | None,
) -> None:
    execute(
        """
        UPDATE mb_requests
        SET sample_sent = ?, supplier_name = ?, consultation_note = ?, expected_receipt_date = ?,
            status = ?
        WHERE mb_request_id = ?
        """,
        (
            1 if sample_sent else 0,
            supplier_name,
            consultation_note,
            expected_receipt_date,
            "업체협의",
            mb_request_id,
        ),
    )
    reset_cache()


def create_mb_purchase_request(
    mb_request_id: int,
    *,
    sample_sent: bool,
    supplier_name: str,
    consultation_note: str,
    expected_receipt_date: str,
) -> None:
    execute(
        """
        UPDATE mb_requests
        SET sample_sent = ?, supplier_name = ?, consultation_note = ?, expected_receipt_date = ?,
            purchase_requested = 1, status = '구매지시생성'
        WHERE mb_request_id = ?
        """,
        (
            1 if sample_sent else 0,
            supplier_name,
            consultation_note,
            expected_receipt_date,
            mb_request_id,
        ),
    )
    reset_cache()


def delete_mb_request(mb_request_id: int) -> tuple[bool, str]:
    ok, message = try_delete(
        "DELETE FROM mb_requests WHERE mb_request_id = ?",
        (mb_request_id,),
    )
    if ok:
        reset_cache()
    return ok, message


def list_mb_receipts() -> pd.DataFrame:
    return get_mb_receipts()


def save_mb_receipt(
    *,
    mb_request_id: int,
    receipt_date: str | None,
    receipt_qty: float,
    lot_no: str,
    receipt_note: str,
    current_user_name: str,
    existing_receipt_id: int | None = None,
) -> dict[str, str | float | int | None]:
    if existing_receipt_id is None:
        execute(
            """
            INSERT INTO mb_receipts (
                mb_request_id, receipt_date, receipt_qty, lot_no, receipt_note, status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, '입고완료', ?, ?)
            """,
            (
                mb_request_id,
                receipt_date,
                receipt_qty,
                lot_no,
                receipt_note,
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE mb_receipts
            SET receipt_date = ?, receipt_qty = ?, lot_no = ?, receipt_note = ?, status = '입고완료'
            WHERE mb_receipt_id = ?
            """,
            (
                receipt_date,
                receipt_qty,
                lot_no,
                receipt_note,
                existing_receipt_id,
            ),
        )
    execute(
        "UPDATE mb_requests SET status = '입고완료' WHERE mb_request_id = ?",
        (mb_request_id,),
    )
    with get_connection() as conn:
        request_row = conn.execute(
            """
            SELECT mr.request_code, i.item_code, i.item_id
            FROM mb_requests mr
            JOIN items i ON i.item_id = mr.item_id
            WHERE mr.mb_request_id = ?
            """,
            (mb_request_id,),
        ).fetchone()
        current_stock = conn.execute(
            """
            SELECT COALESCE(SUM(rc.receipt_qty), 0) AS current_stock
            FROM mb_receipts rc
            JOIN mb_requests mr ON mr.mb_request_id = rc.mb_request_id
            WHERE mr.item_id = (
                SELECT item_id
                FROM mb_requests
                WHERE mb_request_id = ?
            )
              AND COALESCE(rc.status, '입고완료') = '입고완료'
            """,
            (mb_request_id,),
        ).fetchone()
    reset_cache()
    return {
        "mb_request_id": mb_request_id,
        "request_code": str(request_row["request_code"]) if request_row is not None and request_row["request_code"] is not None else "",
        "item_code": str(request_row["item_code"]) if request_row is not None and request_row["item_code"] is not None else "",
        "current_stock": float(current_stock["current_stock"] or 0) if current_stock is not None else 0.0,
    }


def delete_mb_receipt(mb_receipt_id: int, *, mb_request_id: int) -> tuple[bool, str]:
    ok, message = try_delete(
        "DELETE FROM mb_receipts WHERE mb_receipt_id = ?",
        (mb_receipt_id,),
    )
    if ok:
        execute(
            "UPDATE mb_requests SET status = CASE WHEN purchase_requested = 1 THEN '구매지시생성' ELSE status END WHERE mb_request_id = ?",
            (mb_request_id,),
        )
        reset_cache()
    return ok, message


def list_project_options() -> list[tuple[str, int]]:
    return project_options()


def list_experiment_samples() -> pd.DataFrame:
    return get_experiment_samples()


def list_postprocess_item_moves() -> pd.DataFrame:
    return get_postprocess_item_moves()


def list_sample_inventory() -> pd.DataFrame:
    return get_sample_inventory()


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _make_wms_move_code(move_id: int) -> str:
    return f"WMS-{move_id:06d}"


def _normalize_execution_mode(value: str | None) -> str:
    return "외주" if str(value or "").strip() in {"외주", "외부"} else "내부"


def _default_process_location(process_type: str | None) -> str:
    process = str(process_type or "").strip()
    if process == "조립":
        return "조립"
    if process == "인쇄":
        return "인쇄"
    if process == "사출":
        return "사출"
    if process == "사상":
        return "사상"
    return "개발실"


def _instruction_destination(process_type: str | None, execution_mode: str | None, partner_name: str | None) -> str:
    normalized_mode = _normalize_execution_mode(execution_mode)
    partner = str(partner_name or "").strip()
    if normalized_mode == "외주" and partner and partner != "내부":
        return partner
    return _default_process_location(process_type)


def _latest_instruction_context(conn: sqlite3.Connection, experiment_order_id: int, process_type: str | None) -> tuple[str, str, str]:
    row = conn.execute(
        """
        SELECT instruction_detail_json
        FROM experiment_instructions
        WHERE experiment_order_id = ?
        ORDER BY experiment_instruction_id DESC
        LIMIT 1
        """,
        (int(experiment_order_id),),
    ).fetchone()
    detail = {}
    if row is not None and row["instruction_detail_json"]:
        try:
            detail = json.loads(row["instruction_detail_json"])
        except json.JSONDecodeError:
            detail = {}
    execution_mode = _normalize_execution_mode(detail.get("execution_mode"))
    partner_name = str(detail.get("vendor_name") or detail.get("supplier_name") or "").strip()
    if not partner_name:
        partner_name = "내부" if execution_mode == "내부" else "외주"
    destination = _instruction_destination(process_type, execution_mode, partner_name)
    return execution_mode, partner_name, destination


def _infer_initial_sample_qty(sample_row: sqlite3.Row) -> float:
    detail = {}
    raw_text = sample_row["instruction_detail_json"] if "instruction_detail_json" in sample_row.keys() else None
    if raw_text:
        try:
            detail = json.loads(raw_text)
        except json.JSONDecodeError:
            detail = {}
    planned_qty = detail.get("planned_sample_qty") or detail.get("produced_sample_qty") or 1
    try:
        return float(planned_qty)
    except (TypeError, ValueError):
        return 1.0


def _infer_sample_qty_with_fallback(conn: sqlite3.Connection, sample_row: sqlite3.Row) -> float:
    inferred_qty = _infer_initial_sample_qty(sample_row)
    if inferred_qty > 1:
        return inferred_qty
    op_row = conn.execute(
        """
        SELECT op_detail_json
        FROM sample_op_reviews
        WHERE sample_id = ?
        """,
        (int(sample_row["sample_id"]),),
    ).fetchone()
    if op_row is None or not op_row["op_detail_json"]:
        return inferred_qty
    try:
        op_detail = json.loads(op_row["op_detail_json"])
    except json.JSONDecodeError:
        return inferred_qty
    fallback_qty = op_detail.get("produced_sample_qty") or op_detail.get("planned_sample_qty") or inferred_qty
    try:
        fallback_qty = float(fallback_qty)
    except (TypeError, ValueError):
        fallback_qty = inferred_qty
    return fallback_qty if fallback_qty > 0 else inferred_qty


def sync_sample_inventory(*, current_user_name: str = "system") -> None:
    started = time.perf_counter()
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    with get_connection() as conn:
        sample_rows = conn.execute(
            """
            SELECT s.sample_id, eo.project_id, eo.item_id, s.instruction_detail_json
            FROM experiment_samples s
            JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
            """
        ).fetchall()
        _wms_log("sync_sample_inventory_db_query", rows=len(sample_rows))
        for row in sample_rows:
            existing = conn.execute(
                "SELECT sample_id, qty_on_hand FROM sample_inventory WHERE sample_id = ?",
                (int(row["sample_id"]),),
            ).fetchone()
            inferred_qty = _infer_sample_qty_with_fallback(conn, row)
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO sample_inventory (
                        sample_id, project_id, item_id, qty_on_hand, qty_reserved,
                        current_location, partner_name, status, updated_by, updated_at
                    ) VALUES (?, ?, ?, ?, 0, '샘플창고', '내부', '가용', ?, ?)
                    """,
                    (
                        int(row["sample_id"]),
                        int(row["project_id"]),
                        int(row["item_id"]),
                        inferred_qty,
                        current_user_name,
                        _now_text(),
                    ),
                )
                inserted_count += 1
                continue

            current_qty_on_hand = float(existing["qty_on_hand"] or 0)
            if current_qty_on_hand >= inferred_qty or inferred_qty <= 1:
                skipped_count += 1
                continue

            completed_move_cnt = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM postprocess_item_moves
                WHERE sample_id = ?
                  AND status IN ('출고완료', '입고완료')
                """,
                (int(row["sample_id"]),),
            ).fetchone()
            adjustment_cnt = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM sample_inventory_adjustments
                WHERE sample_id = ?
                """,
                (int(row["sample_id"]),),
            ).fetchone()
            if int(completed_move_cnt["cnt"] or 0) > 0 or int(adjustment_cnt["cnt"] or 0) > 0:
                skipped_count += 1
                continue

            conn.execute(
                """
                UPDATE sample_inventory
                SET qty_on_hand = ?, updated_by = ?, updated_at = ?
                WHERE sample_id = ?
                """,
                (
                    inferred_qty,
                    current_user_name,
                    _now_text(),
                    int(row["sample_id"]),
                ),
            )
            updated_count += 1
        conn.commit()
    _wms_log(
        "sync_sample_inventory_commit",
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
        elapsed=f"{time.perf_counter() - started:.3f}s",
    )
    recalculate_inventory_reservations(current_user_name=current_user_name)
    reset_cache()


def recalculate_inventory_reservations(*, current_user_name: str = "system") -> None:
    with get_connection() as conn:
        reservation_rows = conn.execute(
            """
            SELECT sample_id, COALESCE(SUM(requested_qty), 0) AS reserved_qty
            FROM postprocess_item_moves
            WHERE sample_id IS NOT NULL AND status = '출고대기'
            GROUP BY sample_id
            """
        ).fetchall()
        reserved_map = {int(row["sample_id"]): float(row["reserved_qty"] or 0) for row in reservation_rows}
        inventory_rows = conn.execute("SELECT sample_id, qty_on_hand FROM sample_inventory").fetchall()
        for row in inventory_rows:
            sample_id = int(row["sample_id"])
            qty_on_hand = float(row["qty_on_hand"] or 0)
            qty_reserved = float(reserved_map.get(sample_id, 0))
            if qty_on_hand <= 0:
                status = "소진"
            elif qty_reserved > 0:
                status = "예약"
            else:
                status = "가용"
            conn.execute(
                """
                UPDATE sample_inventory
                SET qty_reserved = ?, status = ?, updated_by = ?, updated_at = ?
                WHERE sample_id = ?
                """,
                (qty_reserved, status, current_user_name, _now_text(), sample_id),
            )
        conn.commit()


def sync_wms_orders_from_stock_requirements(*, current_user_name: str = "system") -> None:
    started = time.perf_counter()
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT eo.experiment_order_id, eo.order_code, eo.project_id, eo.item_id, eo.process_type,
                   eo.required_sample_qty, eo.requirement_detail_json, eo.status, i.product_id
            FROM experiment_orders eo
            JOIN items i ON i.item_id = eo.item_id
            """
        ).fetchall()
        _wms_log("sync_wms_orders_from_stock_requirements_db_query", rows=len(rows))
        for row in rows:
            detail_text = row["requirement_detail_json"] or ""
            try:
                detail = json.loads(detail_text) if detail_text else {}
            except json.JSONDecodeError:
                detail = {}
            if str(detail.get("execution_mode") or "") != "재고사용":
                skipped_count += 1
                continue
            sample_id = int(detail.get("stock_sample_id")) if detail.get("stock_sample_id") else None
            if not sample_id:
                skipped_count += 1
                continue
            execution_mode, partner_name, destination = _latest_instruction_context(
                conn,
                int(row["experiment_order_id"]),
                str(row["process_type"] or ""),
            )
            existing = conn.execute(
                """
                SELECT postprocess_move_id, status
                FROM postprocess_item_moves
                WHERE source_type = '요구' AND source_order_id = ?
                ORDER BY postprocess_move_id DESC
                LIMIT 1
                """,
                (int(row["experiment_order_id"]),),
            ).fetchone()
            if str(row["status"] or "") == "취소" or str(detail.get("execution_mode") or "") != "재고사용" or not sample_id:
                if existing is not None and str(existing["status"] or "") not in ("출고완료", "취소"):
                    conn.execute(
                        """
                        UPDATE postprocess_item_moves
                        SET status = '취소', inventory_status = '취소'
                        WHERE postprocess_move_id = ?
                        """,
                        (int(existing["postprocess_move_id"]),),
                    )
                skipped_count += 1
                continue
            if existing:
                conn.execute(
                    """
                    UPDATE postprocess_item_moves
                    SET sample_id = ?, project_id = ?, product_id = ?, item_id = ?, process_type = ?,
                        actual_item_id = ?, wms_kind = '공정품출고지시',
                        execution_mode = ?, partner_name = ?, vendor_name = ?, to_location = ?,
                        requested_qty = ?, inventory_status = '예약'
                    WHERE postprocess_move_id = ?
                    """,
                    (
                        sample_id,
                        int(row["project_id"]),
                        int(row["product_id"]) if row["product_id"] is not None else None,
                        int(row["item_id"]),
                        str(row["process_type"] or ""),
                        int(row["item_id"]),
                        execution_mode,
                        partner_name,
                        partner_name,
                        destination,
                        float(row["required_sample_qty"] or 0),
                        int(existing["postprocess_move_id"]),
                    ),
                )
                updated_count += 1
                continue
            cur = conn.execute(
                """
                INSERT INTO postprocess_item_moves (
                    sample_id, project_id, product_id, item_id, actual_item_id, process_type, wms_kind, execution_mode,
                    partner_name, vendor_name, source_type, source_order_id,
                    requested_qty, to_location, inventory_status, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, '공정품출고지시', ?, ?, ?, '요구', ?, ?, ?, '예약', '출고대기', ?, ?)
                """,
                (
                    sample_id,
                    int(row["project_id"]),
                    int(row["product_id"]) if row["product_id"] is not None else None,
                    int(row["item_id"]),
                    int(row["item_id"]),
                    str(row["process_type"] or ""),
                    execution_mode,
                    partner_name,
                    partner_name,
                    int(row["experiment_order_id"]),
                    float(row["required_sample_qty"] or 0),
                    destination,
                    current_user_name,
                    _now_text(),
                ),
            )
            move_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE postprocess_item_moves SET move_code = ? WHERE postprocess_move_id = ?",
                (_make_wms_move_code(move_id), move_id),
            )
            inserted_count += 1
            continue
        for row in rows:
            detail_text = row["requirement_detail_json"] or ""
            try:
                detail = json.loads(detail_text) if detail_text else {}
            except json.JSONDecodeError:
                detail = {}
            predecessor_links = [link for link in (detail.get("predecessor_links", []) or []) if isinstance(link, dict)]
            for link in predecessor_links:
                source_mode = str(link.get("source_mode") or "")
                predecessor_item_id = int(link.get("item_id")) if link.get("item_id") else None
                sample_id = int(link.get("source_sample_id")) if link.get("source_sample_id") else None
                if source_mode != "재고품" or not predecessor_item_id or not sample_id:
                    skipped_count += 1
                    continue
                predecessor_item_row = conn.execute(
                    "SELECT product_id, process_type FROM items WHERE item_id = ?",
                    (predecessor_item_id,),
                ).fetchone()
                if predecessor_item_row is None:
                    continue
                execution_mode, partner_name, destination = _latest_instruction_context(
                    conn,
                    int(row["experiment_order_id"]),
                    str(row["process_type"] or ""),
                )
                existing = conn.execute(
                    """
                    SELECT postprocess_move_id, status
                    FROM postprocess_item_moves
                    WHERE source_type = '전공정요구' AND source_order_id = ? AND item_id = ? AND actual_item_id = ? AND sample_id = ?
                    ORDER BY postprocess_move_id DESC
                    LIMIT 1
                    """,
                    (int(row["experiment_order_id"]), int(row["item_id"]), predecessor_item_id, sample_id),
                ).fetchone()
                if str(row["status"] or "") == "취소":
                    if existing is not None and str(existing["status"] or "") not in ("출고완료", "취소"):
                        conn.execute(
                        """
                        UPDATE postprocess_item_moves
                        SET status = '취소', inventory_status = '취소'
                        WHERE postprocess_move_id = ?
                            """,
                            (int(existing["postprocess_move_id"]),),
                        )
                    skipped_count += 1
                    continue
                if existing:
                    conn.execute(
                        """
                        UPDATE postprocess_item_moves
                        SET sample_id = ?, project_id = ?, product_id = ?, item_id = ?, actual_item_id = ?, process_type = ?,
                            wms_kind = '전공정품출고지시',
                            execution_mode = ?, partner_name = ?, vendor_name = ?,
                            requested_qty = ?, to_location = ?, inventory_status = '예약'
                        WHERE postprocess_move_id = ?
                        """,
                        (
                            sample_id,
                            int(row["project_id"]),
                            int(row["product_id"]) if row["product_id"] is not None else None,
                            int(row["item_id"]),
                            predecessor_item_id,
                            str(row["process_type"] or ""),
                            execution_mode,
                            partner_name,
                            partner_name,
                            float(row["required_sample_qty"] or 0),
                            destination,
                            int(existing["postprocess_move_id"]),
                        ),
                    )
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO postprocess_item_moves (
                        sample_id, project_id, product_id, item_id, actual_item_id, process_type, wms_kind, execution_mode,
                        partner_name, vendor_name, source_type, source_order_id,
                        requested_qty, to_location, inventory_status, status, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '전공정품출고지시', ?, ?, ?, '전공정요구', ?, ?, ?, '예약', '출고대기', ?, ?)
                    """,
                    (
                        sample_id,
                        int(row["project_id"]),
                        int(row["product_id"]) if row["product_id"] is not None else None,
                        int(row["item_id"]),
                        predecessor_item_id,
                        str(row["process_type"] or ""),
                        execution_mode,
                        partner_name,
                        partner_name,
                        int(row["experiment_order_id"]),
                        float(row["required_sample_qty"] or 0),
                        destination,
                        current_user_name,
                        _now_text(),
                    ),
                )
                move_id = int(cur.lastrowid)
                conn.execute(
                    "UPDATE postprocess_item_moves SET move_code = ? WHERE postprocess_move_id = ?",
                    (_make_wms_move_code(move_id), move_id),
                )
        conn.commit()
    recalculate_inventory_reservations(current_user_name=current_user_name)
    reset_cache()


def sync_wms_inbound_plans_from_instructions(*, current_user_name: str = "system") -> None:
    started = time.perf_counter()
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ei.experiment_instruction_id, ei.instruction_code, ei.experiment_order_id, ei.project_id,
                   ei.item_id, ei.process_type, ei.required_sample_qty, ei.requested_finish_date, ei.status,
                   ei.instruction_detail_json, eo.status AS order_status, i.product_id
            FROM experiment_instructions ei
            JOIN experiment_orders eo ON eo.experiment_order_id = ei.experiment_order_id
            JOIN items i ON i.item_id = ei.item_id
            """
        ).fetchall()
        _wms_log("sync_wms_inbound_plans_from_instructions_db_query", rows=len(rows))
        for row in rows:
            detail_text = row["instruction_detail_json"] or ""
            try:
                detail = json.loads(detail_text) if detail_text else {}
            except json.JSONDecodeError:
                detail = {}
            execution_mode = str(detail.get("execution_mode") or "")
            execution_mode = _normalize_execution_mode(execution_mode)
            partner_name = str(detail.get("vendor_name") or detail.get("supplier_name") or "").strip()
            if not partner_name:
                partner_name = "내부" if execution_mode != "외주" else "외주"
            destination = _instruction_destination(str(row["process_type"] or ""), execution_mode, partner_name)
            sample_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM experiment_samples WHERE experiment_instruction_id = ?",
                (int(row["experiment_instruction_id"]),),
            ).fetchone()
            sample_count = int(sample_count_row["cnt"] or 0) if sample_count_row is not None else 0
            existing = conn.execute(
                """
                SELECT postprocess_move_id, status
                FROM postprocess_item_moves
                WHERE wms_kind = '입고예정' AND source_instruction_id = ?
                ORDER BY postprocess_move_id DESC
                LIMIT 1
                """,
                (int(row["experiment_instruction_id"]),),
            ).fetchone()
            if str(row["status"] or "") == "취소" or str(row["order_status"] or "") == "취소":
                if existing is not None and str(existing["status"] or "") not in ("입고완료", "취소"):
                    conn.execute(
                        """
                        UPDATE postprocess_item_moves
                        SET status = '취소', inventory_status = '취소'
                        WHERE postprocess_move_id = ?
                        """,
                        (int(existing["postprocess_move_id"]),),
                    )
                    updated_count += 1
                skipped_count += 1
                continue
            next_status = "입고완료" if sample_count > 0 else "입고예정"
            next_inventory_status = "보관" if sample_count > 0 else "대기"
            if existing is not None:
                if str(existing["status"] or "") == "출고완료":
                    skipped_count += 1
                    continue
                conn.execute(
                    """
                    UPDATE postprocess_item_moves
                    SET project_id = ?, product_id = ?, item_id = ?, actual_item_id = ?, process_type = ?,
                        execution_mode = ?, partner_name = ?, vendor_name = ?, source_type = '지시',
                        source_order_id = ?, requested_qty = ?, expected_receipt_date = ?, to_location = ?,
                        status = ?, inventory_status = ?
                    WHERE postprocess_move_id = ?
                    """,
                    (
                        int(row["project_id"]),
                        int(row["product_id"]) if row["product_id"] is not None else None,
                        int(row["item_id"]),
                        int(row["item_id"]),
                        str(row["process_type"] or ""),
                        execution_mode or ("외주" if partner_name != "내부" else "내부"),
                        partner_name,
                        partner_name,
                        int(row["experiment_order_id"]),
                        float(row["required_sample_qty"] or 0),
                        str(row["requested_finish_date"] or "") or None,
                        destination,
                        next_status,
                        next_inventory_status,
                        int(existing["postprocess_move_id"]),
                    ),
                )
                updated_count += 1
                continue
            cur = conn.execute(
                """
                INSERT INTO postprocess_item_moves (
                    project_id, product_id, item_id, actual_item_id, process_type, execution_mode, wms_kind,
                    partner_name, vendor_name, source_type, source_order_id, source_instruction_id,
                    requested_qty, expected_receipt_date, to_location, inventory_status, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, '입고예정', ?, ?, '지시', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(row["project_id"]),
                    int(row["product_id"]) if row["product_id"] is not None else None,
                    int(row["item_id"]),
                    int(row["item_id"]),
                    str(row["process_type"] or ""),
                    execution_mode or ("외주" if partner_name != "내부" else "내부"),
                    partner_name,
                    partner_name,
                    int(row["experiment_order_id"]),
                    int(row["experiment_instruction_id"]),
                    float(row["required_sample_qty"] or 0),
                    str(row["requested_finish_date"] or "") or None,
                    destination,
                    next_inventory_status,
                    next_status,
                    current_user_name,
                    _now_text(),
                ),
            )
            move_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE postprocess_item_moves SET move_code = ? WHERE postprocess_move_id = ?",
                (_make_wms_move_code(move_id), move_id),
            )
            inserted_count += 1
        conn.commit()
    _wms_log(
        "sync_wms_inbound_plans_from_instructions_commit",
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
        elapsed=f"{time.perf_counter() - started:.3f}s",
    )
    reset_cache()


def sync_wms_orders_from_customer_requirements(*, current_user_name: str = "system") -> None:
    started = time.perf_counter()
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT eo.experiment_order_id, eo.order_code, eo.project_id, eo.item_id, eo.process_type,
                   eo.required_sample_qty, eo.target_due_date, eo.status, eo.requirement_detail_json, i.product_id
            FROM experiment_orders eo
            JOIN items i ON i.item_id = eo.item_id
            """
        ).fetchall()
        _wms_log("sync_wms_orders_from_customer_requirements_db_query", rows=len(rows))
        for row in rows:
            detail_text = row["requirement_detail_json"] or ""
            try:
                requirement_detail = json.loads(detail_text) if detail_text else {}
            except json.JSONDecodeError:
                requirement_detail = {}
            existing = conn.execute(
                """
                SELECT postprocess_move_id, status
                FROM postprocess_item_moves
                WHERE source_type = '고객요구' AND source_order_id = ?
                ORDER BY postprocess_move_id DESC
                LIMIT 1
                """,
                (int(row["experiment_order_id"]),),
            ).fetchone()
            order_status = str(row["status"] or "")
            execution_mode = str(requirement_detail.get("execution_mode") or "")
            customer_dispatch_required = execution_mode != "재고사용"
            requested_qty = float(row["required_sample_qty"] or 0)
            due_date = str(row["target_due_date"] or "") or None
            if existing is not None:
                existing_status = str(existing["status"] or "")
                if (order_status == "취소" or not customer_dispatch_required) and existing_status not in ("출고완료", "취소"):
                    conn.execute(
                        """
                        UPDATE postprocess_item_moves
                        SET requested_qty = ?, expected_receipt_date = ?, actual_item_id = ?, wms_kind = '고객출고지시',
                            status = '취소', inventory_status = '취소',
                            partner_name = '고객', vendor_name = '고객', execution_mode = '고객출고',
                            to_location = '고객', process_type = ?, product_id = ?, item_id = ?
                        WHERE postprocess_move_id = ?
                        """,
                        (
                            requested_qty,
                            due_date,
                            int(row["item_id"]),
                            str(row["process_type"] or ""),
                            int(row["product_id"]) if row["product_id"] is not None else None,
                            int(row["item_id"]),
                            int(existing["postprocess_move_id"]),
                        ),
                    )
                    updated_count += 1
                else:
                    next_status = existing_status if existing_status in ("최종검토대기", "출고대기", "출고완료", "취소") else "최종검토대기"
                    if existing_status == "출고대기":
                        next_inventory_status = "예약"
                    elif existing_status == "출고완료":
                        next_inventory_status = "출고완료"
                    elif existing_status == "취소":
                        next_inventory_status = "취소"
                    else:
                        next_inventory_status = "대기"
                    conn.execute(
                        """
                        UPDATE postprocess_item_moves
                        SET project_id = ?, product_id = ?, item_id = ?, actual_item_id = ?, process_type = ?, wms_kind = '고객출고지시',
                            partner_name = '고객', vendor_name = '고객', execution_mode = '고객출고',
                            requested_qty = ?, expected_receipt_date = ?, to_location = '고객',
                            status = ?, inventory_status = ?
                        WHERE postprocess_move_id = ?
                        """,
                        (
                            int(row["project_id"]),
                            int(row["product_id"]) if row["product_id"] is not None else None,
                            int(row["item_id"]),
                            int(row["item_id"]),
                            str(row["process_type"] or ""),
                            requested_qty,
                            due_date,
                            next_status,
                            next_inventory_status,
                            int(existing["postprocess_move_id"]),
                        ),
                    )
                    updated_count += 1
                continue
            if order_status == "취소" or not customer_dispatch_required:
                skipped_count += 1
                continue
            cur = conn.execute(
                """
                INSERT INTO postprocess_item_moves (
                    project_id, product_id, item_id, actual_item_id, process_type, wms_kind, execution_mode,
                    partner_name, vendor_name, source_type, source_order_id,
                    requested_qty, expected_receipt_date, to_location,
                    inventory_status, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, '고객출고지시', '고객출고', '고객', '고객', '고객요구', ?, ?, ?, '고객', '대기', '최종검토대기', ?, ?)
                """,
                (
                    int(row["project_id"]),
                    int(row["product_id"]) if row["product_id"] is not None else None,
                    int(row["item_id"]),
                    int(row["item_id"]),
                    str(row["process_type"] or ""),
                    int(row["experiment_order_id"]),
                    requested_qty,
                    due_date,
                    current_user_name,
                    _now_text(),
                ),
            )
            move_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE postprocess_item_moves SET move_code = ? WHERE postprocess_move_id = ?",
                (_make_wms_move_code(move_id), move_id),
            )
            inserted_count += 1
        conn.commit()
    _wms_log(
        "sync_wms_orders_from_customer_requirements_commit",
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
        elapsed=f"{time.perf_counter() - started:.3f}s",
    )
    reset_cache()


def sync_customer_dispatch_for_sample(*, sample_id: int, current_user_name: str = "system") -> None:
    with get_connection() as conn:
        sample_row = conn.execute(
            """
            SELECT s.sample_id, s.experiment_instruction_id, s.status AS sample_status,
                   eo.experiment_order_id, eo.project_id, eo.item_id, eo.process_type, eo.required_sample_qty, eo.target_due_date,
                   i.product_id,
                   fr.approval_status
            FROM experiment_samples s
            JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
            JOIN items i ON i.item_id = eo.item_id
            LEFT JOIN sample_final_reviews fr ON fr.sample_id = s.sample_id
            WHERE s.sample_id = ?
            """,
            (int(sample_id),),
        ).fetchone()
        if sample_row is None:
            return
        move_row = conn.execute(
            """
            SELECT postprocess_move_id, status
            FROM postprocess_item_moves
            WHERE source_type = '고객요구' AND source_order_id = ?
            ORDER BY postprocess_move_id DESC
            LIMIT 1
            """,
            (int(sample_row["experiment_order_id"]),),
        ).fetchone()
        if move_row is None:
            return
        approval_status = str(sample_row["approval_status"] or "")
        existing_status = str(move_row["status"] or "")
        if existing_status == "출고완료":
            return
        next_status = "출고대기" if approval_status == "확정" else "최종검토대기"
        next_inventory_status = "예약" if approval_status == "확정" else "대기"
        conn.execute(
            """
            UPDATE postprocess_item_moves
            SET sample_id = ?, source_instruction_id = ?, project_id = ?, product_id = ?, item_id = ?, actual_item_id = ?, process_type = ?,
                wms_kind = '고객출고지시',
                partner_name = '고객', vendor_name = '고객', execution_mode = '고객출고',
                requested_qty = ?, expected_receipt_date = ?, to_location = '고객',
                status = ?, inventory_status = ?
            WHERE postprocess_move_id = ?
            """,
            (
                int(sample_row["sample_id"]),
                int(sample_row["experiment_instruction_id"]) if sample_row["experiment_instruction_id"] is not None else None,
                int(sample_row["project_id"]),
                int(sample_row["product_id"]) if sample_row["product_id"] is not None else None,
                int(sample_row["item_id"]),
                int(sample_row["item_id"]),
                str(sample_row["process_type"] or ""),
                float(sample_row["required_sample_qty"] or 0),
                str(sample_row["target_due_date"] or "") or None,
                next_status,
                next_inventory_status,
                int(move_row["postprocess_move_id"]),
            ),
        )
        conn.commit()
    recalculate_inventory_reservations(current_user_name=current_user_name)
    reset_cache()


def save_postprocess_dispatch(
    *,
    sample_id: int,
    project_id: int,
    item_id: int,
    vendor_name: str,
    child_dispatch_note: str,
    dispatch_date: str,
    expected_receipt_date: str | None,
    current_user_name: str,
    postprocess_move_id: int | None = None,
) -> None:
    if postprocess_move_id is None:
        execute(
            """
            INSERT INTO postprocess_item_moves (
                sample_id, project_id, item_id, vendor_name, child_dispatch_note,
                dispatch_date, expected_receipt_date, status, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '출고완료', ?, ?)
            """,
            (
                sample_id,
                project_id,
                item_id,
                vendor_name,
                child_dispatch_note,
                dispatch_date,
                expected_receipt_date,
                current_user_name,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    else:
        execute(
            """
            UPDATE postprocess_item_moves
            SET vendor_name = ?, child_dispatch_note = ?, dispatch_date = ?, expected_receipt_date = ?, status = '출고완료'
            WHERE postprocess_move_id = ?
            """,
            (
                vendor_name,
                child_dispatch_note,
                dispatch_date,
                expected_receipt_date,
                postprocess_move_id,
            ),
        )
    reset_cache()


def execute_wms_dispatch(
    *,
    postprocess_move_id: int,
    sample_id: int,
    dispatch_qty: float,
    dispatch_date: str,
    from_location: str,
    to_location: str,
    partner_name: str,
    current_user_name: str,
) -> None:
    with get_connection() as conn:
        move_row = conn.execute(
            """
            SELECT source_type, partner_name, to_location
            FROM postprocess_item_moves
            WHERE postprocess_move_id = ?
            """,
            (postprocess_move_id,),
        ).fetchone()
        is_customer_dispatch = (
            move_row is not None
            and (
                str(move_row["source_type"] or "") == "고객요구"
                or str(move_row["partner_name"] or "") == "고객"
                or str(move_row["to_location"] or "") == "고객"
            )
        )
        inventory_row = conn.execute(
            "SELECT qty_on_hand FROM sample_inventory WHERE sample_id = ?",
            (sample_id,),
        ).fetchone()
        qty_on_hand = float(inventory_row["qty_on_hand"] or 0) if inventory_row is not None else 0
        qty_reserved = float(
            conn.execute(
                """
                SELECT COALESCE(SUM(requested_qty), 0) AS reserved_qty
                FROM postprocess_item_moves
                WHERE sample_id = ? AND status = '출고대기'
                """,
                (sample_id,),
            ).fetchone()["reserved_qty"]
            or 0
        )
        qty_available = qty_on_hand - qty_reserved
        if dispatch_qty > qty_on_hand + 1e-9:
            raise ValueError("현재재고보다 큰 수량은 출고할 수 없습니다.")
        conn.execute(
            """
            UPDATE postprocess_item_moves
            SET partner_name = ?, vendor_name = ?, dispatch_qty = ?, dispatch_date = ?,
                from_location = ?, to_location = ?, status = ?, inventory_status = ?
            WHERE postprocess_move_id = ?
            """,
            (
                partner_name,
                partner_name,
                dispatch_qty,
                dispatch_date,
                from_location,
                to_location,
                "출고완료" if is_customer_dispatch else "입고예정",
                "출고완료" if is_customer_dispatch else "출고중",
                postprocess_move_id,
            ),
        )
        conn.execute(
            """
            UPDATE sample_inventory
            SET qty_on_hand = MAX(qty_on_hand - ?, 0),
                current_location = ?, partner_name = ?, status = ?,
                updated_by = ?, updated_at = ?
            WHERE sample_id = ?
            """,
            (
                dispatch_qty,
                to_location,
                partner_name,
                "소진" if is_customer_dispatch and dispatch_qty >= qty_on_hand - 1e-9 else ("가용" if is_customer_dispatch else "출고중"),
                current_user_name,
                _now_text(),
                sample_id,
            ),
        )
        conn.commit()
    recalculate_inventory_reservations(current_user_name=current_user_name)
    reset_cache()


def complete_wms_receipt(
    *,
    postprocess_move_id: int,
    receipt_date: str,
    receipt_qty: float,
    to_location: str,
    partner_name: str,
    receipt_note: str,
    unit_cost: float | None,
    uph: float | None,
    defect_rate: float | None,
    moq: float | None,
    current_user_name: str,
) -> None:
    execute(
        """
        UPDATE postprocess_item_moves
        SET receipt_date = ?, receipt_qty = ?, to_location = ?, partner_name = ?, vendor_name = ?,
            receipt_note = ?, unit_cost = ?, uph = ?, defect_rate = ?, moq = ?,
            status = '입고완료', inventory_status = '보관'
        WHERE postprocess_move_id = ?
        """,
        (
            receipt_date,
            receipt_qty,
            to_location,
            partner_name,
            partner_name,
            receipt_note,
            unit_cost,
            uph,
            defect_rate,
            moq,
            postprocess_move_id,
        ),
    )
    reset_cache()


def adjust_sample_inventory(
    *,
    sample_id: int,
    project_id: int,
    item_id: int,
    qty_delta: float,
    reason: str,
    note: str,
    current_user_name: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sample_inventory_adjustments (
                sample_id, project_id, item_id, qty_delta, reason, note, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                project_id,
                item_id,
                qty_delta,
                reason,
                note,
                current_user_name,
                _now_text(),
            ),
        )
        conn.execute(
            """
            UPDATE sample_inventory
            SET qty_on_hand = MAX(qty_on_hand + ?, 0),
                updated_by = ?, updated_at = ?
            WHERE sample_id = ?
            """,
            (qty_delta, current_user_name, _now_text(), sample_id),
        )
        conn.commit()
    recalculate_inventory_reservations(current_user_name=current_user_name)
    reset_cache()


def complete_postprocess_receipt(postprocess_move_id: int, *, receipt_date: str) -> None:
    execute(
        """
        UPDATE postprocess_item_moves
        SET receipt_date = ?, status = '입고완료'
        WHERE postprocess_move_id = ?
        """,
        (receipt_date, postprocess_move_id),
    )
    reset_cache()


def delete_postprocess_move(postprocess_move_id: int) -> tuple[bool, str]:
    ok, message = try_delete(
        "DELETE FROM postprocess_item_moves WHERE postprocess_move_id = ?",
        (postprocess_move_id,),
    )
    if ok:
        reset_cache()
    return ok, message
