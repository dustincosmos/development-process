from __future__ import annotations

from datetime import datetime
from itertools import zip_longest
import json

import streamlit as st

from db.runtime import execute, execute_insert, get_connection
from domain.constants import (
    INJECTION_EXTRA_GROUPS,
    INJECTION_STAGE_GROUPS,
    MEASUREMENT_REPEAT_COUNT,
    MEASUREMENT_SLOT_KEYS,
)


def parse_json_text(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _coerce_dict(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return parse_json_text(raw)
    return {}


def make_order_code(item_code: str, prefix_code: str = "RQ", revision_variant_no: str = "", material_variant_no: str = "") -> str:
    date_part = datetime.now().strftime("%Y%m%d")
    revision_variant = str(revision_variant_no or "").strip()
    material_variant = str(material_variant_no or "").strip()
    variant_text = ""
    if revision_variant:
        variant_text += f"R{revision_variant}"
    if material_variant:
        variant_text += "M"
    prefix = f"{prefix_code}-{item_code}"
    if variant_text:
        prefix += f"-{variant_text}"
    prefix += f"-{date_part}-"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT order_code FROM experiment_orders WHERE order_code LIKE ? ORDER BY order_code",
            (f"{prefix}%",),
        ).fetchall()
    max_seq = 0
    for row in rows:
        code = row["order_code"]
        try:
            seq = int(code.rsplit("-", 1)[-1])
        except ValueError:
            continue
        max_seq = max(max_seq, seq)
    return f"{prefix}{max_seq + 1:02d}"


def make_mb_request_code(item_code: str) -> str:
    date_part = datetime.now().strftime("%Y%m%d")
    prefix = f"MB-{item_code}-{date_part}-"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT request_code FROM mb_requests WHERE request_code LIKE ? ORDER BY request_code",
            (f"{prefix}%",),
        ).fetchall()
    max_seq = 0
    for row in rows:
        code = row["request_code"]
        try:
            seq = int(code.rsplit("-", 1)[-1])
        except ValueError:
            continue
        max_seq = max(max_seq, seq)
    return f"{prefix}{max_seq + 1:02d}"


def make_mold_dispatch_code(item_code: str) -> str:
    date_part = datetime.now().strftime("%Y%m%d")
    prefix = f"MD-{item_code}-{date_part}-"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT dispatch_code FROM mold_dispatch_orders WHERE dispatch_code LIKE ? ORDER BY dispatch_code",
            (f"{prefix}%",),
        ).fetchall()
    max_seq = 0
    for row in rows:
        code = row["dispatch_code"]
        try:
            seq = int(code.rsplit("-", 1)[-1])
        except ValueError:
            continue
        max_seq = max(max_seq, seq)
    return f"{prefix}{max_seq + 1:02d}"


def make_document_revision_code(item_code: str, document_type: str) -> str:
    date_part = datetime.now().strftime("%Y%m%d")
    type_code = "DWG" if str(document_type or "").strip() == "도면" else "ART"
    prefix = f"{type_code}-{item_code}-{date_part}-"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT request_code FROM document_revision_orders WHERE request_code LIKE ? ORDER BY request_code",
            (f"{prefix}%",),
        ).fetchall()
    max_seq = 0
    for row in rows:
        code = row["request_code"]
        try:
            seq = int(code.rsplit("-", 1)[-1])
        except ValueError:
            continue
        max_seq = max(max_seq, seq)
    return f"{prefix}{max_seq + 1:02d}"


def make_sample_code(
    order_code: str,
    seq: int,
    ratio: float | None = None,
    existing_codes: set[str] | None = None,
) -> str:
    if ratio is None:
        base_code = f"{order_code}-{seq:02d}"
    else:
        base_code = f"{order_code}-{float(ratio):.1f}"
    if not existing_codes:
        return base_code
    if base_code not in existing_codes:
        return base_code
    suffix = 2
    while f"{base_code}-{suffix}" in existing_codes:
        suffix += 1
    return f"{base_code}-{suffix}"


def upsert_mb_request_for_order(
    experiment_order_id: int,
    project_id: int,
    item_id: int,
    item_code: str,
    color_nuance: str,
    color_sample_exists: bool,
    created_by: str,
    supplier_name: str = "",
    expected_receipt_date: str | None = None,
    sample_received: bool = False,
    purchase_requested: bool = False,
) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT mb_request_id FROM mb_requests WHERE experiment_order_id = ?",
            (experiment_order_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE mb_requests
                SET project_id = ?, item_id = ?, color_nuance = ?, color_sample_exists = ?,
                    supplier_name = ?, expected_receipt_date = ?, sample_received = ?, purchase_requested = ?, status = ?
                WHERE experiment_order_id = ?
                """,
                (
                    project_id,
                    item_id,
                    color_nuance,
                    1 if color_sample_exists else 0,
                    supplier_name.strip(),
                    expected_receipt_date,
                    1 if sample_received else 0,
                    1 if purchase_requested else 0,
                    "구매지시생성" if purchase_requested else "업체협의",
                    experiment_order_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO mb_requests (
                    experiment_order_id, project_id, item_id, request_code, color_nuance, color_sample_exists,
                    supplier_name, expected_receipt_date, sample_received, purchase_requested, status,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_order_id,
                    project_id,
                    item_id,
                    make_mb_request_code(item_code),
                    color_nuance,
                    1 if color_sample_exists else 0,
                    supplier_name.strip(),
                    expected_receipt_date,
                    1 if sample_received else 0,
                    1 if purchase_requested else 0,
                    "구매지시생성" if purchase_requested else "업체협의",
                    created_by,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        conn.commit()


def upsert_mold_dispatch_for_order(
    experiment_order_id: int,
    project_id: int,
    item_id: int,
    item_code: str,
    mold_id: int | None,
    created_by: str,
) -> None:
    with get_connection() as conn:
        order_row = conn.execute(
            """
            SELECT target_due_date
            FROM experiment_orders
            WHERE experiment_order_id = ?
            """,
            (experiment_order_id,),
        ).fetchone()
        sample_request_date = str(order_row["target_due_date"] or "") if order_row is not None and order_row["target_due_date"] is not None else None
        existing = conn.execute(
            """
            SELECT mold_dispatch_order_id
            FROM mold_dispatch_orders
            WHERE experiment_order_id = ? AND status IN ('출고지시', '출고완료')
            ORDER BY mold_dispatch_order_id DESC
            LIMIT 1
            """,
            (experiment_order_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE mold_dispatch_orders
                SET project_id = ?, item_id = ?, mold_id = ?, sample_request_date = ?, dispatch_reason = '사출 수정 후 실험'
                WHERE mold_dispatch_order_id = ?
                """,
                (project_id, item_id, mold_id, sample_request_date, int(existing["mold_dispatch_order_id"])),
            )
        else:
            conn.execute(
                """
                INSERT INTO mold_dispatch_orders (
                    experiment_order_id, project_id, item_id, mold_id, dispatch_code, sample_request_date,
                    dispatch_reason, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, '사출 수정 후 실험', '출고지시', ?, ?)
                """,
                (
                    experiment_order_id,
                    project_id,
                    item_id,
                    mold_id,
                    make_mold_dispatch_code(item_code),
                    sample_request_date,
                    created_by,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        conn.commit()


def sync_document_revision_order_for_order(
    experiment_order_id: int,
    *,
    project_id: int,
    item_id: int,
    item_code: str,
    document_type: str,
    base_document_id: int | None,
    required: bool,
    created_by: str,
) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT document_revision_order_id, status
            FROM document_revision_orders
            WHERE experiment_order_id = ?
            ORDER BY document_revision_order_id DESC
            LIMIT 1
            """,
            (experiment_order_id,),
        ).fetchone()
        if not required:
            if existing is not None and str(existing["status"] or "") not in ("입수완료", "취소"):
                conn.execute(
                    """
                    UPDATE document_revision_orders
                    SET status = '취소'
                    WHERE document_revision_order_id = ?
                    """,
                    (int(existing["document_revision_order_id"]),),
                )
            conn.commit()
            return

        request_reason = "사출 도면 수정본 요청" if document_type == "도면" else "인쇄/라벨 원화 수정본 요청"
        if existing is not None and str(existing["status"] or "") != "취소":
            conn.execute(
                """
                UPDATE document_revision_orders
                SET project_id = ?, item_id = ?, document_type = ?, base_document_id = ?, request_reason = ?
                WHERE document_revision_order_id = ?
                """,
                (
                    project_id,
                    item_id,
                    document_type,
                    base_document_id,
                    request_reason,
                    int(existing["document_revision_order_id"]),
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO document_revision_orders (
                    experiment_order_id, project_id, item_id, document_type, base_document_id,
                    request_code, request_reason, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '수정요청', ?, ?)
                """,
                (
                    experiment_order_id,
                    project_id,
                    item_id,
                    document_type,
                    base_document_id,
                    make_document_revision_code(item_code, document_type),
                    request_reason,
                    created_by,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        conn.commit()


def latest_op_payload(item_id: int, process_type: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT opr.op_detail_json
            FROM sample_op_reviews opr
            JOIN experiment_samples s ON s.sample_id = opr.sample_id
            JOIN experiment_orders eo ON eo.experiment_order_id = s.experiment_order_id
            WHERE eo.item_id = ? AND eo.process_type = ? AND opr.op_detail_json IS NOT NULL
            ORDER BY opr.checked_at DESC
            LIMIT 1
            """,
            (item_id, process_type),
        ).fetchone()
    return parse_json_text(row["op_detail_json"]) if row and row["op_detail_json"] else {}


def get_current_product_drawing_for_item(item_id: int) -> dict | None:
    with get_connection() as conn:
        item_row = conn.execute(
            """
            SELECT i.project_id, pd.drawing_no
            FROM items i
            LEFT JOIN product_drawings pd ON pd.product_drawing_id = i.product_drawing_id
            WHERE i.item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if item_row and item_row["drawing_no"]:
            latest_row = conn.execute(
                """
                SELECT drawing_no, drawing_name, revision_no, file_note, file_path, 0 AS used_fallback
                FROM product_drawings
                WHERE project_id = ? AND drawing_no = ?
                ORDER BY is_current DESC, product_drawing_id DESC
                LIMIT 1
                """,
                (item_row["project_id"], item_row["drawing_no"]),
            ).fetchone()
            if latest_row:
                return dict(latest_row)
        fallback = conn.execute(
            """
            SELECT pd.drawing_no, pd.drawing_name, pd.revision_no, pd.file_note, pd.file_path, 1 AS used_fallback
            FROM items i
            JOIN product_drawings pd ON pd.project_id = i.project_id
            WHERE i.item_id = ?
            ORDER BY pd.is_current DESC, pd.product_drawing_id DESC
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
    return dict(fallback) if fallback and fallback["drawing_no"] else None


def shorten_condition_label(field_name: str, group_name: str) -> str:
    if field_name.startswith("사출_속도"):
        return field_name.replace("사출_속도", "속도")
    if field_name.startswith("사출_압력"):
        return field_name.replace("사출_압력", "압력")
    if field_name.startswith("사출_거리"):
        return field_name.replace("사출_거리", "거리")
    if field_name.startswith("보압_속도"):
        return field_name.replace("보압_속도", "속도")
    if field_name.startswith("보압_압력"):
        return field_name.replace("보압_압력", "압력")
    if field_name.startswith("보압_시간"):
        return field_name.replace("보압_시간", "시간")
    if field_name.startswith("계량_RPM"):
        return field_name.replace("계량_RPM", "RPM")
    if field_name.startswith("계량_거리"):
        return field_name.replace("계량_거리", "거리")
    if field_name.startswith("계량_배압"):
        return field_name.replace("계량_배압", "배압")
    if field_name.startswith("실린더_"):
        return field_name.replace("실린더_", "")
    if field_name.startswith("금형온도_"):
        return field_name.replace("금형온도_", "")
    if field_name.startswith("H/R_번호"):
        return field_name.replace("H/R_번호", "번호")
    if field_name.startswith("H/R_온도"):
        return field_name.replace("H/R_온도", "온도")
    if field_name.endswith("_1차"):
        base = field_name.replace("_1차", "")
        return f"{base} 1차" if group_name == "Cycle Time" else base
    if field_name.endswith("_2차"):
        base = field_name.replace("_2차", "")
        return f"{base} 2차" if group_name == "Cycle Time" else base
    return field_name


def render_injection_condition_inputs(defaults: dict) -> dict:
    result: dict[str, object] = {}
    def render_stage_card(card_title: str, group_name: str, count: int, rows: list[tuple[str, str]]) -> None:
        with st.container(border=True):
            st.markdown(f"**{card_title}**")
            header_cols = st.columns([1.2] + [1] * count)
            with header_cols[0]:
                st.caption("항목")
            for idx in range(1, count + 1):
                with header_cols[idx]:
                    st.caption(str(idx))
            for row_label, field_prefix in rows:
                row_cols = st.columns([1.2] + [1] * count)
                with row_cols[0]:
                    st.markdown(f"`{row_label}`")
                for idx in range(1, count + 1):
                    field_name = f"{field_prefix}{idx}"
                    with row_cols[idx]:
                        default_value = defaults.get(field_name, "")
                        result[field_name] = st.text_input(
                            f"{group_name}_{row_label}_{idx}",
                            value=str(default_value),
                            label_visibility="collapsed",
                            key=f"condition_matrix_{field_name}",
                        )

    def render_extra_card(card_title: str, group_name: str, fields: list[str], col_count: int) -> None:
        with st.container(border=True):
            st.markdown(f"**{card_title}**")
            field_cols = st.columns(col_count)
            for idx, field in enumerate(fields):
                with field_cols[idx % col_count]:
                    default_value = defaults.get(field, "")
                    if field == "금형온도_특이사항" and not default_value:
                        default_value = defaults.get("금형이동_특이사항", "")
                    result[field] = st.text_input(
                        shorten_condition_label(field, group_name),
                        value=str(default_value),
                        key=f"condition_{group_name}_{field}",
                    )

    # 사출 조건변화는 단독 카드로 둔다.
    render_stage_card("사출조건변화", INJECTION_STAGE_GROUPS[0][0], INJECTION_STAGE_GROUPS[0][1], INJECTION_STAGE_GROUPS[0][2])

    row1_c1, row1_c2 = st.columns(2)
    with row1_c1:
        render_stage_card("보압조건변화", INJECTION_STAGE_GROUPS[1][0], INJECTION_STAGE_GROUPS[1][1], INJECTION_STAGE_GROUPS[1][2])
    with row1_c2:
        render_stage_card("계량조건변화", INJECTION_STAGE_GROUPS[2][0], INJECTION_STAGE_GROUPS[2][1], INJECTION_STAGE_GROUPS[2][2])

    row2_c1, row2_c2, row2_c3 = st.columns(3)
    with row2_c1:
        render_extra_card("보압보조", INJECTION_EXTRA_GROUPS[0][0], INJECTION_EXTRA_GROUPS[0][1], INJECTION_EXTRA_GROUPS[0][2])
    with row2_c2:
        render_extra_card("계량보조", INJECTION_EXTRA_GROUPS[1][0], INJECTION_EXTRA_GROUPS[1][1], INJECTION_EXTRA_GROUPS[1][2])
    with row2_c3:
        render_extra_card("실린더온도", INJECTION_EXTRA_GROUPS[2][0], INJECTION_EXTRA_GROUPS[2][1], INJECTION_EXTRA_GROUPS[2][2])

    row3_c1, row3_c2, row3_c3 = st.columns(3)
    with row3_c1:
        render_extra_card("HR", INJECTION_EXTRA_GROUPS[4][0], INJECTION_EXTRA_GROUPS[4][1], INJECTION_EXTRA_GROUPS[4][2])
    with row3_c2:
        render_extra_card("금형온도", INJECTION_EXTRA_GROUPS[3][0], INJECTION_EXTRA_GROUPS[3][1], INJECTION_EXTRA_GROUPS[3][2])
    with row3_c3:
        render_extra_card("온도특이", INJECTION_EXTRA_GROUPS[5][0], INJECTION_EXTRA_GROUPS[5][1], INJECTION_EXTRA_GROUPS[5][2])

    row4_c1, row4_c2 = st.columns(2)
    with row4_c1:
        render_extra_card("Cycle Time", INJECTION_EXTRA_GROUPS[6][0], INJECTION_EXTRA_GROUPS[6][1], INJECTION_EXTRA_GROUPS[6][2])
    with row4_c2:
        render_extra_card("작업 메모", INJECTION_EXTRA_GROUPS[7][0], INJECTION_EXTRA_GROUPS[7][1], INJECTION_EXTRA_GROUPS[7][2])
    return result


def render_measurement_inputs(
    defaults: dict,
    prefix: str,
    locked_titles: dict[str, str] | None = None,
    locked_specs: dict[str, str] | None = None,
    *,
    single_card: bool = False,
    card_title: str | None = None,
) -> dict:
    defaults = defaults if isinstance(defaults, dict) else {}
    result: dict[str, object] = {}
    slots = MEASUREMENT_SLOT_KEYS
    if single_card:
        with st.container(border=True):
            st.markdown(f"**{card_title or f'{prefix} 측정값'}**")
            for slot in slots:
                locked_title = str((locked_titles or {}).get(slot, "") or "")
                locked_spec = str((locked_specs or {}).get(slot, "") or "")
                part_value = locked_title or str(defaults.get(f"{prefix}_{slot}_측정부위", ""))
                row_cols = st.columns([0.7, 2, 2, 6])
                with row_cols[0]:
                    st.caption(slot)
                with row_cols[1]:
                    result[f"{prefix}_{slot}_측정부위"] = st.text_input(
                        f"{slot} 측정부위",
                        value=part_value,
                        key=f"measure_part_{prefix}_{slot}",
                        disabled=bool(locked_title),
                    )
                with row_cols[2]:
                    st.text_input(
                        f"{slot} 도면규격",
                        value=locked_spec,
                        key=f"measure_spec_{prefix}_{slot}",
                        disabled=True,
                    )
                with row_cols[3]:
                    cols = st.columns(MEASUREMENT_REPEAT_COUNT)
                    for i in range(1, MEASUREMENT_REPEAT_COUNT + 1):
                        with cols[i - 1]:
                            result[f"{prefix}_{slot}_{i}"] = st.text_input(
                                str(i),
                                value=str(defaults.get(f"{prefix}_{slot}_{i}", "")),
                                key=f"measure_value_{prefix}_{slot}_{i}",
                            )
    else:
        for slot in slots:
            locked_title = str((locked_titles or {}).get(slot, "") or "")
            locked_spec = str((locked_specs or {}).get(slot, "") or "")
            part_value = locked_title or str(defaults.get(f"{prefix}_{slot}_측정부위", ""))
            with st.container(border=True):
                st.markdown(f"**{slot} 측정**")
                header_cols = st.columns([2, 2, 6])
                with header_cols[0]:
                    result[f"{prefix}_{slot}_측정부위"] = st.text_input(
                        f"{slot} 측정부위",
                        value=part_value,
                        key=f"measure_part_{prefix}_{slot}",
                        disabled=bool(locked_title),
                    )
                with header_cols[1]:
                    st.text_input(
                        f"{slot} 도면규격",
                        value=locked_spec,
                        key=f"measure_spec_{prefix}_{slot}",
                        disabled=True,
                    )
                with header_cols[2]:
                    cols = st.columns(MEASUREMENT_REPEAT_COUNT)
                    for i in range(1, MEASUREMENT_REPEAT_COUNT + 1):
                        with cols[i - 1]:
                            result[f"{prefix}_{slot}_{i}"] = st.text_input(
                                str(i),
                                value=str(defaults.get(f"{prefix}_{slot}_{i}", "")),
                                key=f"measure_value_{prefix}_{slot}_{i}",
                            )
    return result


def render_injection_op_review_inputs(defaults: dict) -> dict:
    result: dict[str, object] = {}
    left_col, right_col = st.columns(2)
    with left_col:
        with st.container(border=True):
            st.markdown("**제품/치수 검토**")
            dimension_options = ["도면치수 근접", "조건조정 필요", "금형수정 필요"]
            result["dimension_review_result"] = st.selectbox(
                "판정",
                dimension_options,
                index=dimension_options.index(defaults.get("dimension_review_result", "도면치수 근접"))
                if defaults.get("dimension_review_result", "도면치수 근접") in dimension_options
                else 0,
                key="dimension_review_result",
            )
            result["dimension_issue_area"] = st.text_input("문제부위", value=str(defaults.get("dimension_issue_area", "")), key="dimension_issue_area")
            result["dimension_change_direction"] = st.multiselect(
                "수정방향",
                ["조건으로 가능", "코어 수정", "캐비티 수정", "게이트 수정", "취출/냉각 수정"],
                default=defaults.get("dimension_change_direction", []),
                key="dimension_change_direction",
            )
    with right_col:
        with st.container(border=True):
            st.markdown("**금형 동작/상태 검토**")
            mold_options = ["생산 적합", "조건 보완 필요", "금형수정 필요"]
            result["mold_review_result"] = st.selectbox(
                "판정 ",
                mold_options,
                index=mold_options.index(defaults.get("mold_review_result", "생산 적합"))
                if defaults.get("mold_review_result", "생산 적합") in mold_options
                else 0,
                key="mold_review_result",
            )
            result["mold_review_checks"] = st.multiselect(
                "체크항목",
                ["취출 상태", "이형 상태", "슬라이드/코어 동작", "게이트 절단 상태", "냉각 상태", "반복생산 안정성"],
                default=defaults.get("mold_review_checks", []),
                key="mold_review_checks",
            )
            result["mold_change_direction"] = st.multiselect(
                "수정방향",
                ["동작 보완", "마모/간섭 수정", "냉각 보완", "취출 보완"],
                default=defaults.get("mold_change_direction", []),
                key="mold_change_direction",
            )
    with st.container(border=True):
        st.markdown("**기타 의견**")
        c1, c2 = st.columns(2)
        with c1:
            result["other_review_tags"] = st.multiselect(
                "의견 분류",
                ["외관 이슈", "작업성 이슈", "안전/설비 이슈", "변형", "색상", "생산성", "기타"],
                default=defaults.get("other_review_tags", []),
                key="other_review_tags",
            )
        with c2:
            overall_options = ["양호", "조건조정 후 재확인", "금형수정 후 재실험"]
            result["overall_op_result"] = st.selectbox(
                "종합판정",
                overall_options,
                index=overall_options.index(defaults.get("overall_op_result", "양호"))
                if defaults.get("overall_op_result", "양호") in overall_options
                else 0,
                key="overall_op_result",
            )
    return result


def render_injection_quality_review_inputs(defaults: dict) -> tuple[str, str, str]:
    st.markdown("**사출 품질 검토**")
    after_defaults = _coerce_dict(defaults.get("after_24h_measurement", ""))
    measurement_titles = {
        slot: str(defaults.get(f"instruction_measure_title_{slot}", "") or defaults.get(f"instruction_measurement_title_{slot}", "") or "")
        for slot in MEASUREMENT_SLOT_KEYS
    }
    measurement_specs = {
        slot: str(defaults.get(f"instruction_measure_spec_{slot}", "") or defaults.get(f"instruction_measurement_spec_{slot}", "") or "")
        for slot in MEASUREMENT_SLOT_KEYS
    }
    for slot in MEASUREMENT_SLOT_KEYS:
        base_part = measurement_titles.get(slot, "")
        if base_part:
            after_defaults[f"24H_{slot}_측정부위"] = base_part
    review_defaults = _coerce_dict(defaults.get("quality_comment", ""))
    tabs = st.tabs(["24시간 후 측정", "품질 체크", "품질 의견"])
    with tabs[0]:
        after_measurement_values = render_measurement_inputs(
            after_defaults,
            "24H",
            measurement_titles,
            measurement_specs,
            single_card=True,
            card_title="24시간 후 측정",
        )
    with tabs[1]:
        c1, c2 = st.columns(2)
        with c1:
            dimension_checks = st.multiselect("치수/중량 체크", ["A부 치수", "B부 치수", "C부 치수", "제품중량", "런너중량", "치수 안정성"], default=review_defaults.get("dimension_checks", []), key="quality_dimension_checks")
            appearance_checks = st.multiselect("외관 체크", ["흑점", "변형", "웰드라인", "플로우마크", "게이트 자국", "스크래치"], default=review_defaults.get("appearance_checks", []), key="quality_appearance_checks")
        with c2:
            process_checks = st.multiselect("공정 안정성 체크", ["취출 안정성", "이형 상태", "사이클 안정성", "조건 재현성", "금형상태 이상 없음"], default=review_defaults.get("process_checks", []), key="quality_process_checks")
            quality_values = ["합격", "조건부합격", "불합격"]
            quality_result = st.selectbox("품질 판정", quality_values, index=quality_values.index(review_defaults.get("quality_result", "합격")) if review_defaults.get("quality_result", "합격") in quality_values else 0, key="quality_result")
    with tabs[2]:
        action_checks = st.multiselect("후속조치", ["조건조정", "금형수정 검토", "재측정", "재실험", "고객 확인 필요"], default=review_defaults.get("action_checks", []), key="quality_action_checks")
        issue_summary = st.text_input("주요 문제부위", value=str(review_defaults.get("issue_summary", "")), key="quality_issue_summary")
    second_measurement = json.dumps({"dimension_checks": dimension_checks, "appearance_checks": appearance_checks, "process_checks": process_checks, "quality_result": quality_result}, ensure_ascii=False)
    after_24h_measurement = json.dumps(after_measurement_values, ensure_ascii=False)
    quality_comment = json.dumps({"action_checks": action_checks, "issue_summary": issue_summary}, ensure_ascii=False)
    return second_measurement, after_24h_measurement, quality_comment


def render_assembly_quality_review_inputs(defaults: dict) -> tuple[str, str, str]:
    st.markdown("**조립 품질 검토**")
    review_defaults = _coerce_dict(defaults.get("quality_comment", ""))
    c1, c2 = st.columns(2)
    with c1:
        measurement_checks = st.multiselect("측정/시험 체크", ["분리력", "기능규격", "간섭", "체결력", "외관손상", "조립성"], default=review_defaults.get("measurement_checks", []), key="assembly_measurement_checks")
        measurement_values = st.text_area("측정값/시험값", value=str(review_defaults.get("measurement_values", "")), height=100, key="assembly_measurement_values")
    with c2:
        quality_values = ["합격", "조건부합격", "불합격"]
        quality_result = st.selectbox("품질 판정", quality_values, index=quality_values.index(review_defaults.get("quality_result", "합격")) if review_defaults.get("quality_result", "합격") in quality_values else 0, key="assembly_quality_result")
        action_checks = st.multiselect("의견/후속조치", ["재조립", "조건조정", "도면확인", "부품수정 검토", "재실험"], default=review_defaults.get("action_checks", []), key="assembly_action_checks")
        issue_summary = st.text_input("주요 문제부위", value=str(review_defaults.get("issue_summary", "")), key="assembly_issue_summary")
    payload = {"measurement_checks": measurement_checks, "measurement_values": measurement_values, "quality_result": quality_result, "action_checks": action_checks, "issue_summary": issue_summary}
    return json.dumps(payload, ensure_ascii=False), "", json.dumps(payload, ensure_ascii=False)


def render_print_quality_review_inputs(defaults: dict) -> tuple[str, str, str]:
    st.markdown("**인쇄/후가공/사상 품질 검토**")
    review_defaults = _coerce_dict(defaults.get("quality_comment", ""))
    c1, c2 = st.columns(2)
    with c1:
        measurement_checks = st.multiselect("측정/시험 체크", ["색상", "인쇄 위치", "내스크래치", "밀착성", "번짐/이염", "외관"], default=review_defaults.get("measurement_checks", []), key="print_measurement_checks")
        measurement_values = st.text_area("측정값/시험값", value=str(review_defaults.get("measurement_values", "")), height=100, key="print_measurement_values")
    with c2:
        quality_values = ["합격", "조건부합격", "불합격"]
        quality_result = st.selectbox("품질 판정", quality_values, index=quality_values.index(review_defaults.get("quality_result", "합격")) if review_defaults.get("quality_result", "합격") in quality_values else 0, key="print_quality_result")
        action_checks = st.multiselect("의견/후속조치", ["색상 보정", "필름 수정 검토", "조건조정", "재실험", "고객 확인 필요"], default=review_defaults.get("action_checks", []), key="print_action_checks")
        issue_summary = st.text_input("주요 문제부위", value=str(review_defaults.get("issue_summary", "")), key="print_issue_summary")
    payload = {"measurement_checks": measurement_checks, "measurement_values": measurement_values, "quality_result": quality_result, "action_checks": action_checks, "issue_summary": issue_summary}
    return json.dumps(payload, ensure_ascii=False), "", json.dumps(payload, ensure_ascii=False)
