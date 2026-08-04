from __future__ import annotations

import json
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from domain.constants import (
    ASSEMBLY_FUNCTION_OPTIONS,
    COLOR_NUANCE_OPTIONS,
    INJECTION_EXTRA_GROUPS,
    INJECTION_STAGE_GROUPS,
    MOLD_UPDATE_TYPE_OPTIONS,
    SUB_MATERIAL_ISSUE_OPTIONS,
    VENDOR_RESELECTION_OPTIONS,
)
from domain.schemas import (
    ExperimentInstructionPayload,
    ExperimentOrderPayload,
    ExperimentSamplePayload,
    FinalReviewPayload,
    OpReviewPayload,
    QualityReviewPayload,
)
from services.development_service import (
    delete_experiment_instruction,
    delete_experiment_order,
    delete_experiment_sample,
    get_current_product_drawing_for_item,
    get_experiment_order_usage,
    get_item_row,
    get_requirement_jump_context,
    list_meta_requirement_lines,
    list_meta_requirement_line_links,
    list_integrated_board_rows,
    get_meta_requirement_row,
    get_project_by_code,
    list_meta_requirements_for_context,
    list_product_options_for_project,
    list_experiment_instructions,
    list_experiment_orders,
    list_experiment_samples,
    list_film_options_for_project,
    list_item_options_for_project,
    list_items,
    list_mb_requests,
    list_mold_dispatch_orders,
    list_mold_options_for_project,
    list_order_options_for_project,
    list_project_item_tree_options,
    list_project_options,
    list_raw_material_options_for_project,
    list_sample_workflow,
    save_experiment_instruction,
    save_experiment_order,
    save_experiment_sample,
    save_meta_requirement_lines,
    save_meta_requirement_line_link,
    save_final_review,
    save_op_review,
    save_quality_review,
    update_experiment_order_status,
)
from services.development_page_service import (
    derive_requirement_checks,
    parse_json_text,
    render_product_drawing_reference,
)
from services.inspection_plan_service import (
    add_check_id_results,
    apply_previous_quality_defaults,
    inspection_plan_from_details,
    parse_dict as parse_inspection_dict,
    required_result_issues,
)
from services.reference_data_service import get_item_bom, get_mold_drawings, get_molds, get_print_films, get_products
from services.customer_report_service import (
    build_injection_customer_report_filename,
    build_injection_customer_report_pdf_filename,
    create_injection_customer_report,
    create_injection_customer_report_pdf,
    create_injection_customer_report_pdf_from_preview_html,
)
from services import operations_service
from services.development_ui_service import (
    DRAWING_RECEIPT_STATUS_OPTIONS,
    EXPERIMENT_PROCESS_OPTIONS,
    MILESTONE_OPTIONS,
    SAMPLE_RESULT_OPTIONS,
    build_instruction_summary_labels,
    can_edit,
    current_user,
    filter_instruction_samples,
    infer_process_type_from_item,
    latest_op_payload,
    make_sample_code,
    render_assembly_quality_review_inputs,
    render_dataframe,
    render_injection_condition_inputs,
    render_injection_op_review_inputs,
    render_injection_quality_review_inputs,
    render_measurement_inputs,
    render_print_quality_review_inputs,
    show_permission_hint,
    validate_instruction_save,
    validate_requirement_save,
)
from services.shell_service import flash_success, render_history_panel, render_page_actions, render_section_title


def _select_index(options: list[str], value: str) -> int:
    return options.index(value) if value in options else 0


def _save_instruction_safely(selected_row, *, payload, current_user_name):
    try:
        return save_experiment_instruction(
            selected_row,
            payload=payload,
            current_user_name=current_user_name,
        )
    except ValueError as exc:
        st.error(str(exc))
        return None


def _compact_tree_item_label(label: str, product_name: str = "") -> None:
    parts = str(label or "").split(" | ")
    first = parts[0] if parts else ""
    leading_spaces = len(first) - len(first.lstrip())
    item_code = first.strip()
    item_name = parts[1].strip() if len(parts) > 1 else ""
    process_type = parts[2].strip() if len(parts) > 2 else ""
    compact_name = item_name
    normalized_product_name = str(product_name or "").strip()
    if normalized_product_name and compact_name.startswith(normalized_product_name):
        compact_name = compact_name[len(normalized_product_name):].strip(" -_|/")
    if process_type and compact_name.endswith(process_type):
        compact_name = compact_name[: -len(process_type)].strip(" -_|/")
    compact_name = compact_name or item_name or "-"
    padding_left = min((leading_spaces // 3) * 8, 24)
    tooltip = escape(" | ".join(value for value in (item_code, item_name, process_type) if value), quote=True)
    process_badge = (
        f'<span style="flex:0 0 auto;margin-left:5px;padding:1px 5px;border-radius:8px;background:#eef2f7;color:#4b5563;font-size:0.68rem;">{escape(process_type)}</span>'
        if process_type else ""
    )
    st.markdown(
        f"""
        <div title="{tooltip}" style="height:42px;min-width:0;padding-left:{padding_left}px;overflow:hidden;line-height:1.2;">
            <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{escape(item_code)}</div>
            <div style="display:flex;align-items:center;min-width:0;font-size:0.76rem;color:#374151;">
                <span style="min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{escape(compact_name)}</span>
                {process_badge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _safe_date_value(value) -> object | None:
    if value in (None, "", "None"):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.date()


def _safe_int_value(value, default: int = 0) -> int:
    if value in (None, "", "None"):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _candidate_mold_options_for_item(
    selected_item_row: pd.Series | None,
    project_molds: list[tuple[str, int]],
    *,
    preferred_mold_id: int | None = None,
) -> tuple[list[tuple[str, int]], str]:
    if selected_item_row is None or not project_molds:
        return project_molds, ""
    molds_df = get_molds()
    mold_drawings_df = get_mold_drawings()
    if molds_df.empty:
        return project_molds, ""
    linked_product_drawing_id = (
        int(selected_item_row["product_drawing_id"])
        if "product_drawing_id" in selected_item_row.index and pd.notna(selected_item_row["product_drawing_id"])
        else None
    )
    primary_mold_id = (
        int(selected_item_row["primary_mold_id"])
        if "primary_mold_id" in selected_item_row.index and pd.notna(selected_item_row["primary_mold_id"])
        else None
    )
    linked_mold_ids: set[int] = set()
    if linked_product_drawing_id is not None and not mold_drawings_df.empty:
        linked_drawing_nos = set(
            mold_drawings_df[
                pd.to_numeric(mold_drawings_df["product_drawing_id"], errors="coerce") == linked_product_drawing_id
            ]["mold_drawing_no"].dropna().astype(str).tolist()
        )
        if linked_drawing_nos:
            linked_mold_ids.update(
                molds_df[molds_df["mold_drawing_no"].fillna("").astype(str).isin(linked_drawing_nos)]["mold_id"]
                .dropna()
                .astype(int)
                .tolist()
            )
    if primary_mold_id is not None:
        linked_mold_ids.add(primary_mold_id)
    if preferred_mold_id is not None:
        linked_mold_ids.add(int(preferred_mold_id))
    if linked_mold_ids:
        filtered_options = [(label, mold_id) for label, mold_id in project_molds if int(mold_id) in linked_mold_ids]
        if filtered_options:
            return filtered_options, "사출품 연계 도면/기본금형 기준으로 금형 후보를 좁혔습니다."
    return project_molds, "연계 금형이 없어 프로젝트 전체 금형 목록을 표시합니다."


def _has_instruction_for_order(instructions_df: pd.DataFrame, order_id: int | None) -> bool:
    if not order_id or instructions_df.empty or "experiment_order_id" not in instructions_df.columns:
        return False
    matched = instructions_df[
        pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == int(order_id)
    ]
    return not matched.empty


def _linked_requirement_extra_qty_map(meta_line_links_df: pd.DataFrame) -> dict[int, int]:
    if meta_line_links_df.empty:
        return {}
    working = meta_line_links_df.copy()
    if "linked_experiment_order_id" not in working.columns:
        return {}
    working = working[pd.to_numeric(working["linked_experiment_order_id"], errors="coerce").notna()].copy()
    if working.empty:
        return {}
    working["linked_experiment_order_id"] = pd.to_numeric(working["linked_experiment_order_id"], errors="coerce").astype(int)
    working["linked_required_sample_qty"] = pd.to_numeric(
        working.get("linked_required_sample_qty"), errors="coerce"
    ).fillna(0).astype(int)
    grouped = working.groupby("linked_experiment_order_id", as_index=False)["linked_required_sample_qty"].sum()
    return {
        int(row["linked_experiment_order_id"]): int(row["linked_required_sample_qty"])
        for _, row in grouped.iterrows()
    }


def _row_field_value(row, field_name: str, default=None):
    if row is None:
        return default
    if isinstance(row, pd.Series):
        return row.get(field_name, default)
    if isinstance(row, dict):
        return row.get(field_name, default)
    try:
        if hasattr(row, "keys") and field_name in row.keys():
            return row[field_name]
    except Exception:
        pass
    try:
        return row[field_name]
    except Exception:
        return default


def clear_injection_ui_state() -> None:
    for key in [
        "inject_entry_mode",
        "inject_view_only",
        "inject_locked",
        "inject_editing_id",
        "inject_selected_order_id",
        "inject_selected_item_id",
        "inject_selected_requirement_id",
        "inject_form_data",
        "inject_project_label",
        "inject_product_label",
        "inject_item_tree_label",
        "inject_order_label",
        "inject_existing_pick",
        "inject_active_project_code",
        "inject_active_product_id",
        "inject_active_item_id",
        "inject_active_order_id",
        "inject_active_instruction_id",
        "inject_mode",
        "inject_mode_locked",
    ]:
        st.session_state.pop(key, None)


def clear_process_ui_state() -> None:
    for key in [
        "process_entry_mode",
        "process_view_only",
        "process_locked",
        "process_editing_id",
        "process_selected_order_id",
        "process_selected_item_id",
        "process_selected_requirement_id",
        "process_form_data",
        "process_project_label",
        "process_product_label",
        "process_item_tree_label",
        "process_order_label",
        "process_existing_pick",
        "process_active_project_code",
        "process_active_product_id",
        "process_active_item_id",
        "process_active_order_id",
        "process_active_instruction_id",
        "process_mode",
        "process_mode_locked",
    ]:
        st.session_state.pop(key, None)


def clear_assembly_ui_state() -> None:
    for key in [
        "assembly_instruction_project_label",
        "assembly_instruction_product_label",
        "assembly_active_product_id",
        "assembly_instruction_tree_mode",
        "assembly_instruction_meta_label",
        "assembly_instruction_mode",
        "assembly_instruction_order_label",
        "assembly_instruction_pick",
        "assembly_instruction_selected_item_ids",
        "assembly_instruction_selected_meta_line_ids",
        "assembly_instruction_selected_line_status",
        "assembly_instruction_selected_meta_requirement_id",
        "assembly_instruction_selected_requirement_id",
        "assembly_instruction_selected_tree_node",
    ]:
        st.session_state.pop(key, None)


def clear_return_context() -> None:
    for key in [
        "instruction_return_context",
        "instruction_jump_request",
        "assembly_return_context",
        "assembly_restore_context",
    ]:
        st.session_state.pop(key, None)


def clear_injection_instruction_state() -> None:
    clear_injection_ui_state()


def clear_instruction_return_state() -> None:
    clear_return_context()


def _instruction_scope_suffix(instruction_scope: str) -> str:
    return "injection" if instruction_scope == "사출" else "process"


def _instruction_scoped_keys(instruction_scope: str) -> dict[str, str]:
    scope_key = _instruction_scope_suffix(instruction_scope)
    return {
        "scope_key": scope_key,
        "entry_mode": f"{scope_key}_entry_mode",
        "view_only": f"{scope_key}_view_only",
        "project_label": f"{scope_key}_project_label",
        "product_label": f"{scope_key}_product_label",
        "item_tree_label": f"{scope_key}_item_tree_label",
        "order_label": f"{scope_key}_order_label",
        "existing_pick": f"{scope_key}_existing_pick",
        "active_project_code": f"{scope_key}_active_project_code",
        "active_product_id": f"{scope_key}_active_product_id",
        "active_item_id": f"{scope_key}_active_item_id",
        "active_order_id": f"{scope_key}_active_order_id",
        "active_instruction_id": f"{scope_key}_active_instruction_id",
        "direct_visit_token": f"{scope_key}_direct_visit_token",
        "mode": f"{scope_key}_mode",
        "mode_locked": f"{scope_key}_mode_locked",
        "locked": f"{scope_key}_locked",
    }


def _clear_invalid_selectbox_value(widget_key: str, options: list[str]) -> None:
    current_value = st.session_state.get(widget_key)
    if current_value not in options:
        st.session_state.pop(widget_key, None)


def _log_return_context_state() -> None:
    print(
        "[RETURN_CTX] current",
        {
            "assembly_return_context": st.session_state.get("assembly_return_context"),
            "assembly_restore_context": st.session_state.get("assembly_restore_context"),
        },
    )


def _get_assembly_restore_context() -> dict[str, object]:
    restore_context = st.session_state.get("assembly_restore_context")
    if isinstance(restore_context, dict):
        return dict(restore_context)
    return {}


def _clear_instruction_selection_after_item_change(
    order_key: str,
    existing_pick_key: str,
    active_order_state_key: str,
    active_instruction_state_key: str,
) -> None:
    for key in [
        order_key,
        existing_pick_key,
        active_order_state_key,
        active_instruction_state_key,
    ]:
        st.session_state.pop(key, None)


def clear_instruction_top_filters(scope_key: str) -> None:
    prefix = "inject" if scope_key == "injection" else "process"
    for key in [
        f"{prefix}_project_label",
        f"{prefix}_product_label",
        f"{prefix}_item_tree_label",
        f"{prefix}_order_label",
        f"{prefix}_existing_pick",
        f"{prefix}_active_project_code",
        f"{prefix}_active_product_id",
        f"{prefix}_active_item_id",
        f"{prefix}_active_order_id",
        f"{prefix}_active_instruction_id",
        f"{prefix}_entry_mode",
        f"{prefix}_view_only",
        f"{prefix}_locked",
        f"{prefix}_editing_id",
        f"{prefix}_selected_order_id",
        f"{prefix}_selected_item_id",
        f"{prefix}_selected_requirement_id",
        f"{prefix}_form_data",
        f"{prefix}_mode",
        f"{prefix}_mode_locked",
    ]:
        st.session_state.pop(key, None)


def clear_assembly_return_state() -> None:
    clear_return_context()


def _append_nav_trace(stage: str, **payload) -> None:
    trace = st.session_state.setdefault("nav_trace_dev", [])
    trace.append({"stage": stage, **payload})
    del trace[:-30]
    print({"stage": stage, **payload})


def _order_total_required_qty(
    order_row,
    linked_requirement_extra_qty_by_order: dict[int, int] | None = None,
    *,
    default: int = 1,
) -> int:
    if order_row is None:
        return default
    base_qty = _safe_int_value(_row_field_value(order_row, "required_sample_qty"), 0)
    order_id = _safe_int_value(_row_field_value(order_row, "experiment_order_id"), 0)
    extra_qty = 0
    if linked_requirement_extra_qty_by_order and order_id:
        extra_qty = max(_safe_int_value(linked_requirement_extra_qty_by_order.get(order_id), 0), 0)
    total_qty = base_qty + extra_qty
    return total_qty if total_qty >= 1 else default


def _render_summary_info_grid(entries: list[tuple[str, str]], *, columns: int = 4) -> None:
    filtered_entries = []
    for label, value in entries:
        normalized = value if value not in (None, "", "None") else "-"
        filtered_entries.append((label, str(normalized)))
    for start in range(0, len(filtered_entries), columns):
        row_entries = filtered_entries[start:start + columns]
        row_columns = st.columns(columns)
        for idx, (label, value) in enumerate(row_entries):
            with row_columns[idx]:
                st.caption(label)
                st.write(value)


def _render_process_instruction_summary(
    process_type: str,
    *,
    instruction_code: str,
    instruction_date: str = "",
    requested_date: str,
    execution_mode: str,
    upstream_sample_code: str,
    vendor_name: str,
    note_1: str,
    note_2: str,
    milestone_name: str = "",
    extra_label_1: str = "",
    extra_value_1: str = "",
    extra_label_2: str = "",
    extra_value_2: str = "",
) -> None:
    note_1_label = "확정 뉴앙스" if process_type in ("후가공", "사상") else "지시 뉴앙스"
    note_2_label = "마스킹 위치" if process_type in ("후가공", "사상") else "위치 확인"
    entries = [
        ("지시코드", instruction_code),
        ("지시일", instruction_date),
        ("완료요청일", requested_date),
        ("실행방식", execution_mode),
        ("전공정 샘플", upstream_sample_code),
        ("업체", vendor_name),
        (note_1_label, note_1),
        (note_2_label, note_2),
        ("고객요구 마일스톤", milestone_name),
    ]
    if extra_label_1:
        entries.append((extra_label_1, extra_value_1))
    if extra_label_2:
        entries.append((extra_label_2, extra_value_2))
    _render_summary_info_grid(entries)


def _render_requirement_process_card(
    process_type: str,
    detail: dict,
    *,
    key_prefix: str,
    spec_key_suffix: str,
    compact: bool = False,
) -> dict:
    result: dict = {}
    if process_type == "사출":
        color_required = bool(detail.get("color_required"))
        color_sample_exists = detail.get("color_sample_exists", "있음")
        color_nuance_type = detail.get("color_nuance_type", detail.get("color_nuance", ""))
        color_nuance_extra = detail.get("color_nuance_extra", "")
        mold_dispatch_required = bool(detail.get("mold_dispatch_required"))
        mold_update_options = [option for option in MOLD_UPDATE_TYPE_OPTIONS if option]
        mold_update_type = detail.get("mold_update_type", "")
        if mold_update_type not in mold_update_options and mold_update_options:
            mold_update_type = mold_update_options[0]
        drawing_change_source = detail.get("drawing_change_source", "구두/이미지")
        raw_material_experiment_required = bool(detail.get("raw_material_experiment_required"))
        raw_material_1_label = detail.get("raw_material_1_label", "")
        raw_material_2_label = detail.get("raw_material_2_label", "")
        if compact:
            sec_groups = [st.container(), st.container(), st.container()]
        else:
            sec_groups = st.columns(3)
        with sec_groups[0]:
            with st.container(border=True):
                st.caption("색상")
                color_required = st.checkbox("색상 체크", value=color_required, key=f"{key_prefix}_color_required")
                color_sample_exists = st.radio(
                    "샘플 유무",
                    ["있음", "없음"],
                    horizontal=True,
                    index=0 if color_sample_exists == "있음" else 1,
                    disabled=not color_required,
                    key=f"{key_prefix}_color_sample_exists",
                )
                color_nuance_type = st.selectbox(
                    "뉴앙스",
                    options=COLOR_NUANCE_OPTIONS,
                    index=_select_index(COLOR_NUANCE_OPTIONS, color_nuance_type),
                    disabled=not color_required,
                    key=f"{key_prefix}_color_nuance_type",
                )
                color_nuance_extra = st.text_input(
                    "뉴앙스 기타",
                    value=color_nuance_extra,
                    disabled=not color_required or color_nuance_type != "기타",
                    key=f"{key_prefix}_color_nuance_extra",
                )
        with sec_groups[1]:
            with st.container(border=True):
                st.caption("금형")
                mold_dispatch_required = st.checkbox("금형수정 체크", value=mold_dispatch_required, key=f"{key_prefix}_mold_dispatch_required")
                mold_update_type = st.selectbox(
                    "수정내용",
                    options=mold_update_options,
                    index=mold_update_options.index(mold_update_type) if mold_update_type in mold_update_options else 0,
                    disabled=not mold_dispatch_required,
                    key=f"{key_prefix}_mold_update_type",
                )
                drawing_change_source = st.selectbox(
                    "수정전달방식",
                    options=["도면", "구두/이미지"],
                    index=0 if drawing_change_source == "도면" else 1,
                    disabled=not mold_dispatch_required,
                    key=f"{key_prefix}_drawing_change_source",
                )
                mold_update_detail_extra = st.text_input(
                    "수정기타",
                    value=detail.get("mold_update_detail_extra", ""),
                    disabled=not mold_dispatch_required,
                    key=f"{key_prefix}_mold_update_detail_extra",
                )
        with sec_groups[2]:
            with st.container(border=True):
                st.caption("원료")
                raw_material_experiment_required = st.checkbox(
                    "원료 체크",
                    value=raw_material_experiment_required,
                    key=f"{key_prefix}_raw_material_experiment_required",
                )
                raw_material_1_label = st.text_input(
                    "원료명 1",
                    value=raw_material_1_label,
                    disabled=not raw_material_experiment_required,
                    key=f"{key_prefix}_raw_material_1_label",
                )
                raw_material_2_label = st.text_input(
                    "원료명 2",
                    value=raw_material_2_label,
                    disabled=not raw_material_experiment_required,
                    key=f"{key_prefix}_raw_material_2_label",
                )
        st.caption("특정위치 규격 / 외관 위치")
        appearance_entries = []
        spec_entries = []
        legacy_appearance_items = detail.get("appearance_items", [])
        legacy_appearance_position = detail.get("appearance_position", "")
        for idx in range(1, 5):
            if compact:
                spec_location = st.text_input(
                    f"위치 {idx}",
                    value=detail.get(f"spec_location_{idx}", ""),
                    key=f"{key_prefix}_spec_location_{spec_key_suffix}_{idx}",
                )
                spec_value = st.text_input(
                    f"규격 {idx}",
                    value=detail.get(f"spec_value_{idx}", ""),
                    key=f"{key_prefix}_spec_value_{spec_key_suffix}_{idx}",
                )
                default_appearance_item = detail.get(f"appearance_item_{idx}", "")
                if not default_appearance_item and idx == 1 and legacy_appearance_items:
                    default_appearance_item = legacy_appearance_items[0]
                appearance_item = st.selectbox(
                    f"외관 {idx}",
                    options=["", "수축", "웰드라인", "플로우마크", "기타"],
                    index=["", "수축", "웰드라인", "플로우마크", "기타"].index(default_appearance_item)
                    if default_appearance_item in ["", "수축", "웰드라인", "플로우마크", "기타"] else 0,
                    key=f"{key_prefix}_appearance_item_{spec_key_suffix}_{idx}",
                )
                appearance_position = st.text_input(
                    f"외관 위치 {idx}",
                    value=detail.get(f"appearance_position_{idx}", legacy_appearance_position if idx == 1 else ""),
                    key=f"{key_prefix}_appearance_position_{spec_key_suffix}_{idx}",
                )
            else:
                c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                with c1:
                    spec_location = st.text_input(
                        f"위치 {idx}",
                        value=detail.get(f"spec_location_{idx}", ""),
                        key=f"{key_prefix}_spec_location_{spec_key_suffix}_{idx}",
                    )
                with c2:
                    spec_value = st.text_input(
                        f"규격 {idx}",
                        value=detail.get(f"spec_value_{idx}", ""),
                        key=f"{key_prefix}_spec_value_{spec_key_suffix}_{idx}",
                    )
                default_appearance_item = detail.get(f"appearance_item_{idx}", "")
                if not default_appearance_item and idx == 1 and legacy_appearance_items:
                    default_appearance_item = legacy_appearance_items[0]
                with c3:
                    appearance_item = st.selectbox(
                        f"외관 {idx}",
                        options=["", "수축", "웰드라인", "플로우마크", "기타"],
                        index=["", "수축", "웰드라인", "플로우마크", "기타"].index(default_appearance_item)
                        if default_appearance_item in ["", "수축", "웰드라인", "플로우마크", "기타"] else 0,
                        key=f"{key_prefix}_appearance_item_{spec_key_suffix}_{idx}",
                    )
                with c4:
                    appearance_position = st.text_input(
                        f"외관 위치 {idx}",
                        value=detail.get(f"appearance_position_{idx}", legacy_appearance_position if idx == 1 else ""),
                        key=f"{key_prefix}_appearance_position_{spec_key_suffix}_{idx}",
                    )
            spec_entries.append((spec_location, spec_value))
            appearance_entries.append((appearance_item, appearance_position))
        for idx, (spec_location, spec_value) in enumerate(spec_entries, start=1):
            result[f"spec_location_{idx}"] = spec_location
            result[f"spec_value_{idx}"] = spec_value
        appearance_items = [item for item, _position in appearance_entries if item]
        first_appearance_position = next((position for item, position in appearance_entries if item or position), "")
        for idx, (appearance_item, appearance_position) in enumerate(appearance_entries, start=1):
            result[f"appearance_item_{idx}"] = appearance_item
            result[f"appearance_position_{idx}"] = appearance_position
        result.update(
            {
                "color_required": color_required,
                "color_sample_exists": color_sample_exists,
                "color_nuance_type": color_nuance_type,
                "color_nuance_extra": color_nuance_extra.strip(),
                "color_nuance": color_nuance_extra.strip() if color_nuance_type == "기타" else color_nuance_type,
                "product_drawing_change_required": True if mold_dispatch_required and drawing_change_source == "도면" else False,
                "drawing_change_source": drawing_change_source,
                "raw_material_experiment_required": raw_material_experiment_required,
                "raw_material_1_id": None,
                "raw_material_1_label": raw_material_1_label,
                "raw_material_2_id": None,
                "raw_material_2_label": raw_material_2_label,
                "mold_dispatch_required": mold_dispatch_required,
                "mold_update_type": mold_update_type,
                "mold_update_detail_extra": mold_update_detail_extra,
                "mold_update_detail": " / ".join([part for part in [mold_update_type, mold_update_detail_extra.strip()] if part]),
                "appearance_items": appearance_items,
                "appearance_position": first_appearance_position,
            }
        )
    elif process_type in ("후가공", "사상"):
        color_required = bool(detail.get("color_required"))
        color_sample_exists = detail.get("color_sample_exists", "있음")
        color_nuance_type = detail.get("color_nuance_type", detail.get("color_nuance", ""))
        if compact:
            sec_groups = [st.container(), st.container(), st.container()]
        else:
            sec_groups = st.columns([1, 1, 1])
        with sec_groups[0]:
            color_required = st.checkbox("색상", value=color_required, key=f"{key_prefix}_color_required")
            color_sample_exists = st.radio(
                "색상샘플 유무",
                ["있음", "없음"],
                horizontal=True,
                index=0 if color_sample_exists == "있음" else 1,
                disabled=not color_required,
                key=f"{key_prefix}_color_sample_exists",
            )
        with sec_groups[1]:
            color_nuance_type = st.selectbox(
                "색상 뉴앙스",
                options=COLOR_NUANCE_OPTIONS,
                index=_select_index(COLOR_NUANCE_OPTIONS, color_nuance_type),
                disabled=not color_required,
                key=f"{key_prefix}_color_nuance_type",
            )
            color_nuance_extra = st.text_input(
                "색상 뉴앙스 기타",
                value=detail.get("color_nuance_extra", ""),
                disabled=not color_required or color_nuance_type != "기타",
                key=f"{key_prefix}_color_nuance_extra",
            )
        with sec_groups[2]:
            masking_position = st.text_input("마스킹위치", value=detail.get("masking_position", ""), key=f"{key_prefix}_masking_position")
        result.update(
            {
                "color_required": color_required,
                "color_sample_exists": color_sample_exists,
                "color_nuance_type": color_nuance_type,
                "color_nuance_extra": color_nuance_extra.strip(),
                "color_nuance": color_nuance_extra.strip() if color_nuance_type == "기타" else color_nuance_type,
                "masking_position": masking_position,
            }
        )
    elif process_type == "인쇄":
        film_revision_required = bool(detail.get("film_revision_required"))
        color_required = bool(detail.get("color_required"))
        color_sample_exists = detail.get("color_sample_exists", "있음")
        color_nuance_type = detail.get("color_nuance_type", detail.get("color_nuance", ""))
        if compact:
            sec_groups = [st.container(), st.container(), st.container()]
        else:
            sec_groups = st.columns([1, 1, 1])
        with sec_groups[0]:
            film_revision_required = st.checkbox("원화 수정 여부", value=film_revision_required, key=f"{key_prefix}_film_revision_required")
            color_required = st.checkbox("색상", value=color_required, key=f"{key_prefix}_color_required")
            color_sample_exists = st.radio(
                "색상샘플 유무",
                ["있음", "없음"],
                horizontal=True,
                index=0 if color_sample_exists == "있음" else 1,
                disabled=not color_required,
                key=f"{key_prefix}_color_sample_exists",
            )
        with sec_groups[1]:
            color_nuance_type = st.selectbox(
                "색상 뉴앙스",
                options=COLOR_NUANCE_OPTIONS,
                index=_select_index(COLOR_NUANCE_OPTIONS, color_nuance_type),
                disabled=not color_required,
                key=f"{key_prefix}_color_nuance_type",
            )
            color_nuance_extra = st.text_input(
                "색상 뉴앙스 기타",
                value=detail.get("color_nuance_extra", ""),
                disabled=not color_required or color_nuance_type != "기타",
                key=f"{key_prefix}_color_nuance_extra",
            )
        with sec_groups[2]:
            print_position = st.text_input("기준 위치", value=detail.get("print_position", ""), key=f"{key_prefix}_print_position")
            print_tolerance_deg = st.number_input(
                "허용오차 (+- 몇도)",
                min_value=0.0,
                step=0.5,
                value=float(detail.get("print_tolerance_deg", 0.0)),
                key=f"{key_prefix}_print_tolerance_deg",
            )
        result.update(
            {
                "film_revision_required": film_revision_required,
                "color_required": color_required,
                "color_sample_exists": color_sample_exists,
                "color_nuance_type": color_nuance_type,
                "color_nuance_extra": color_nuance_extra.strip(),
                "color_nuance": color_nuance_extra.strip() if color_nuance_type == "기타" else color_nuance_type,
                "print_position": print_position,
                "print_tolerance_deg": print_tolerance_deg,
            }
        )
    elif process_type == "조립":
        assembly_function_type = detail.get("assembly_function_type", detail.get("assembly_function", ""))
        backing_spec = detail.get("backing_spec", "")
        sub_material_issue_type = detail.get("sub_material_issue_type", detail.get("sub_material_other", ""))
        if compact:
            sec_groups = [st.container(), st.container(), st.container()]
        else:
            sec_groups = st.columns([1, 1, 1])
        with sec_groups[0]:
            assembly_function_type = st.selectbox(
                "기능",
                options=ASSEMBLY_FUNCTION_OPTIONS,
                index=_select_index(ASSEMBLY_FUNCTION_OPTIONS, assembly_function_type),
                key=f"{key_prefix}_assembly_function_type",
            )
            assembly_function_extra = st.text_input(
                "기능 기타",
                value=detail.get("assembly_function_extra", ""),
                disabled=assembly_function_type != "기타",
                key=f"{key_prefix}_assembly_function_extra",
            )
        with sec_groups[1]:
            backing_spec = st.text_input("바킹 규격", value=backing_spec, key=f"{key_prefix}_backing_spec")
        with sec_groups[2]:
            sub_material_issue_type = st.selectbox(
                "부재료 사양",
                options=SUB_MATERIAL_ISSUE_OPTIONS,
                index=_select_index(SUB_MATERIAL_ISSUE_OPTIONS, sub_material_issue_type),
                key=f"{key_prefix}_sub_material_issue_type",
            )
            sub_material_other_extra = st.text_input(
                "부재료 기타",
                value=detail.get("sub_material_other_extra", ""),
                disabled=sub_material_issue_type != "기타",
                key=f"{key_prefix}_sub_material_other_extra",
            )
        result.update(
            {
                "assembly_function_type": assembly_function_type,
                "assembly_function_extra": assembly_function_extra,
                "assembly_function": assembly_function_extra.strip() if assembly_function_type == "기타" else assembly_function_type,
                "backing_spec": backing_spec,
                "sub_material_issue_type": sub_material_issue_type,
                "sub_material_other_extra": sub_material_other_extra,
                "sub_material_other": sub_material_other_extra.strip() if sub_material_issue_type == "기타" else sub_material_issue_type,
            }
        )
    return result


def _render_child_requirement_nodes(
    *,
    parent_item_id: int,
    bom_df: pd.DataFrame,
    samples_df: pd.DataFrame,
    target_due_date,
    required_sample_qty: int,
    milestone_name: str,
    detail_map: dict,
    key_prefix: str,
    depth: int = 0,
) -> dict:
    updated_map: dict = {}
    child_items_df = bom_df[bom_df["parent_item_id"] == parent_item_id].copy() if not bom_df.empty else bom_df.iloc[0:0]
    for _, child_row in child_items_df.iterrows():
        child_id = int(child_row["child_item_id"])
        child_code = child_row["child_item_code"]
        child_name = child_row["child_item_name"]
        child_item_row = get_item_row(child_id)
        child_process = infer_process_type_from_item(child_item_row)
        child_key = str(child_id)
        child_detail = detail_map.get(child_key, {})
        if not isinstance(child_detail, dict):
            child_detail = {}
        child_mode_options = ["실험", "재고사용"]
        child_mode = child_detail.get("mode", "실험")
        if child_mode not in child_mode_options:
            child_mode = "실험"
        child_due_date = _safe_date_value(child_detail.get("target_due_date")) if child_detail.get("target_due_date") else target_due_date
        child_qty = _safe_int_value(child_detail.get("required_sample_qty", required_sample_qty or 1), required_sample_qty or 1)
        child_milestone = child_detail.get("milestone_name", milestone_name)
        child_note = child_detail.get("note", "")
        child_sample_df = samples_df[samples_df["item_id"] == child_id].copy() if not samples_df.empty else samples_df.iloc[0:0]
        child_sample_options = [
            (f"{row['sample_code']} | {row['sample_name'] or row['item_name']}", int(row["sample_id"]))
            for _, row in child_sample_df.iterrows()
        ]
        selected_child_stock_id = child_detail.get("stock_sample_id")
        nested_child_map = child_detail.get("child_requirements", {})
        if not isinstance(nested_child_map, dict):
            nested_child_map = {}
        with st.container(border=True):
            st.caption(f"{child_code} | {child_name} ({child_process})")
            child_mode = st.radio(
                "준비 방식",
                options=child_mode_options,
                horizontal=True,
                key=f"{key_prefix}_mode_{child_id}",
                index=child_mode_options.index(child_mode),
            )
            if child_mode == "재고사용":
                child_stock_label = st.selectbox(
                    "실험샘플 선택",
                    options=[""] + [label for label, _ in child_sample_options],
                    key=f"{key_prefix}_stock_{child_id}",
                    index=(
                        1 + [sid for _, sid in child_sample_options].index(int(selected_child_stock_id))
                        if selected_child_stock_id and any(sid == int(selected_child_stock_id) for _, sid in child_sample_options)
                        else 0
                    ) if child_sample_options else 0,
                )
                selected_child_stock_id = dict(child_sample_options).get(child_stock_label) if child_stock_label else None
                child_process_detail = {}
                nested_child_map = {}
                if child_process != "사출":
                    nested_title = "전공정" if child_process in ("후가공", "사상") else "구성품 준비"
                    with st.container(border=True):
                        st.caption(nested_title)
                        st.caption("미사용")
            else:
                selected_child_stock_id = None
                child_due_date = st.date_input("납기일", value=child_due_date, key=f"{key_prefix}_due_{child_id}")
                child_qty = st.number_input("수량", min_value=1, step=1, value=child_qty, key=f"{key_prefix}_qty_{child_id}")
                child_milestone = st.selectbox(
                    "마일스톤",
                    options=MILESTONE_OPTIONS,
                    index=MILESTONE_OPTIONS.index(child_milestone) if child_milestone in MILESTONE_OPTIONS else 0,
                    key=f"{key_prefix}_mile_{child_id}",
                )
                child_note = st.text_input("실험 요구 메모", value=child_note, key=f"{key_prefix}_note_{child_id}")
                child_process_detail = _render_requirement_process_card(
                    child_process,
                    child_detail,
                    key_prefix=f"{key_prefix}_{child_id}",
                    spec_key_suffix=f"{key_prefix}_{child_id}",
                    compact=True,
                )
                if child_process != "사출":
                    nested_title = "전공정" if child_process in ("후가공", "사상") else "구성품 준비"
                    with st.container(border=True):
                        st.caption(nested_title)
                        nested_child_map = _render_child_requirement_nodes(
                            parent_item_id=child_id,
                            bom_df=bom_df,
                            samples_df=samples_df,
                            target_due_date=child_due_date,
                            required_sample_qty=int(child_qty),
                            milestone_name=child_milestone,
                            detail_map=nested_child_map,
                            key_prefix=f"{key_prefix}_{child_id}_child",
                            depth=depth + 1,
                        )

        updated_map[child_key] = {
            "mode": child_mode,
            "stock_sample_id": int(selected_child_stock_id) if selected_child_stock_id else None,
            "target_due_date": str(child_due_date) if child_due_date else None,
            "required_sample_qty": int(child_qty),
            "milestone_name": child_milestone,
            "note": child_note,
            "child_requirements": nested_child_map,
            **child_process_detail,
        }
    return updated_map


def _validate_terminal_injection_requirements(
    *,
    parent_item_id: int,
    bom_df: pd.DataFrame,
    detail_map: dict,
) -> str | None:
    child_items_df = bom_df[bom_df["parent_item_id"] == parent_item_id].copy() if not bom_df.empty else bom_df.iloc[0:0]
    for _, child_row in child_items_df.iterrows():
        child_id = int(child_row["child_item_id"])
        child_name = child_row["child_item_name"]
        child_detail = detail_map.get(str(child_id), {})
        if not isinstance(child_detail, dict):
            return f"{child_name} 준비 방식이 올바르지 않습니다."
        child_mode = child_detail.get("mode")
        if child_mode not in {"실험", "재고사용"}:
            return f"{child_name} 준비 방식을 선택해 주세요."
        child_process = infer_process_type_from_item(get_item_row(child_id))
        if child_mode == "재고사용":
            if not child_detail.get("stock_sample_id"):
                return f"{child_name} 재고사용 시 실험샘플을 선택해 주세요."
            continue
        if child_process == "사출":
            continue
        nested_map = child_detail.get("child_requirements", {})
        if not isinstance(nested_map, dict) or not nested_map:
            return f"{child_name}의 전공정 말단은 사출품이어야 합니다. 전공정 요구를 입력해 주세요."
        nested_error = _validate_terminal_injection_requirements(
            parent_item_id=child_id,
            bom_df=bom_df,
            detail_map=nested_map,
        )
        if nested_error:
            return nested_error
    return None


def _build_injection_customer_form_preview_html(
    sample_row: pd.Series,
    item_row: pd.Series | None,
    project_row: pd.Series | None,
    experiment_date_text: str,
    experimenter_text: str,
    requirement_detail: dict,
    instruction_detail: dict,
    condition_detail: dict,
    op_detail: dict,
    after_24h_detail: dict,
    second_measurement_detail: dict,
    quality_comment_detail: dict,
    approval_status: str,
    final_comment: str,
    final_action: str,
) -> str:
    def text(value: object, default: str = "-") -> str:
        raw = "" if value is None else str(value).strip()
        return escape(raw or default)

    def stage_value(source: dict, prefix: str, stage: int) -> object:
        return source.get(f"{prefix}_{stage}", source.get(f"{prefix}{stage}", ""))

    instruction_mb_code = str(sample_row.get("mb_request_code") or "").strip()
    if not instruction_mb_code:
        instruction_mb_code = str(instruction_detail.get("mb_request_code") or "").strip()
    instruction_mb_ratio = instruction_detail.get("mb_ratio")
    mb_text = instruction_mb_code or "-"
    if instruction_mb_ratio not in (None, "", "None"):
        mb_text = f"{mb_text}  {float(instruction_mb_ratio or 0.0):.1f}%"
    display_machine_ton = (
        op_detail.get("machine_ton")
        or op_detail.get("톤수")
        or sample_row.get("machine_ton")
        or instruction_detail.get("machine_ton")
    )
    display_machine_no = (
        op_detail.get("machine_no")
        or op_detail.get("호기")
        or sample_row.get("machine_no")
        or instruction_detail.get("machine_no")
    )
    display_raw_material_label = (
        op_detail.get("used_raw_material_label")
        or instruction_detail.get("raw_material_label")
        or item_row.get("base_material_label")
        if item_row is not None
        else instruction_detail.get("raw_material_label")
    )
    experiment_mb_code = (
        op_detail.get("used_mb_name")
        or sample_row.get("mb_request_code")
        or instruction_detail.get("mb_request_code")
    )
    experiment_mb_ratio = op_detail.get("mb_ratio_pct")
    if experiment_mb_ratio in (None, "", "None"):
        experiment_mb_ratio = instruction_mb_ratio
    display_mb_text = str(experiment_mb_code or "").strip() or "-"
    if experiment_mb_ratio not in (None, "", "None"):
        display_mb_text = f"{display_mb_text}  {float(experiment_mb_ratio or 0.0):.1f}%"
    weight_values = [str(op_detail.get(f"product_weight_{idx}", "")).strip() for idx in range(1, 9)]
    weight_values = [value for value in weight_values if value]
    molds_df = get_molds()
    cavity_value = ""
    if not molds_df.empty and "used_mold_id" in sample_row.index and pd.notna(sample_row.get("used_mold_id")):
        mold_match = molds_df[molds_df["mold_id"] == int(sample_row["used_mold_id"])]
        if not mold_match.empty and pd.notna(mold_match.iloc[0]["cavity"]):
            cavity_value = str(mold_match.iloc[0]["cavity"])
    if not cavity_value:
        cavity_value = text(op_detail.get("cavity"), "")
    mold_code_text = text(
        sample_row.get("mold_code"),
        text(item_row.get("primary_mold_code") if item_row is not None else "", "-"),
    )
    drawing_info = None
    if "item_id" in sample_row.index and pd.notna(sample_row.get("item_id")):
        drawing_info = get_current_product_drawing_for_item(int(sample_row["item_id"]))
    drawing_no_text = text((drawing_info or {}).get("drawing_no"), text(item_row.get("product_drawing_no") if item_row is not None else "", text(sample_row.get("base_drawing_revision"))))
    measurement_rows = []
    for idx in range(1, 9):
        measurement_rows.append(
            [
                text(op_detail.get(f"즉시_A_{idx}"), ""),
                text(after_24h_detail.get(f"24H_A_{idx}"), ""),
                text(op_detail.get(f"즉시_B_{idx}"), ""),
                text(after_24h_detail.get(f"24H_B_{idx}"), ""),
                text(op_detail.get(f"즉시_C_{idx}"), ""),
                text(after_24h_detail.get(f"24H_C_{idx}"), ""),
                f"{idx}번",
                text(op_detail.get(f"product_weight_{idx}"), ""),
            ]
        )
    point_check_lines: list[str] = []
    if second_measurement_detail.get("dimension_checks"):
        point_check_lines.append(f"치수/중량 체크: {', '.join(second_measurement_detail.get('dimension_checks', []))}")
    if second_measurement_detail.get("appearance_checks"):
        point_check_lines.append(f"외관 체크: {', '.join(second_measurement_detail.get('appearance_checks', []))}")
    if second_measurement_detail.get("process_checks"):
        point_check_lines.append(f"공정 체크: {', '.join(second_measurement_detail.get('process_checks', []))}")
    if second_measurement_detail.get("quality_result"):
        point_check_lines.append(f"품질 판정: {second_measurement_detail.get('quality_result')}")
    if quality_comment_detail.get("action_checks"):
        point_check_lines.append(f"조치 체크: {', '.join(quality_comment_detail.get('action_checks', []))}")
    if quality_comment_detail.get("issue_summary"):
        point_check_lines.append(f"점검 요약: {quality_comment_detail.get('issue_summary')}")
    point_check_text = "\n".join(point_check_lines)
    measure_title_a = text(instruction_detail.get("measurement_title_A") or op_detail.get("즉시_A_측정부위"), "")
    measure_title_b = text(instruction_detail.get("measurement_title_B") or op_detail.get("즉시_B_측정부위"), "")
    measure_title_c = text(instruction_detail.get("measurement_title_C") or op_detail.get("즉시_C_측정부위"), "")
    runner_weight_text = text(op_detail.get("runner_weight"), "")
    def spec_text_for(title: str) -> str:
        raw = title.strip()
        if not raw:
            return ""
        for idx in range(1, 5):
            loc = str(requirement_detail.get(f"spec_location_{idx}", "") or "").strip()
            val = str(requirement_detail.get(f"spec_value_{idx}", "") or "").strip()
            if loc and raw in loc:
                return val
        return ""
    spec_a = text(instruction_detail.get("measurement_spec_A") or spec_text_for(measure_title_a), "")
    spec_b = text(instruction_detail.get("measurement_spec_B") or spec_text_for(measure_title_b), "")
    spec_c = text(instruction_detail.get("measurement_spec_C") or spec_text_for(measure_title_c), "")
    measurement_table_rows_html = "".join(
        (
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{row[0]}</td><td>{row[1]}</td>"
            f"<td>{row[2]}</td><td>{row[3]}</td>"
            f"<td>{row[4]}</td><td>{row[5]}</td>"
            f"<td>{row[6]}</td><td>{row[7]}</td>"
            "</tr>"
        )
        for idx, row in enumerate(measurement_rows, start=1)
    )
    process_stage_header = "".join(f"<div>{stage}</div>" for stage in ["10", "9", "8", "7", "6", "5", "4", "3", "2", "1"])
    process_source = condition_detail or op_detail
    process_speed = "".join(f"<div>{text(stage_value(process_source, '사출_속도', stage), '')}</div>" for stage in range(10, 0, -1))
    process_pressure = "".join(f"<div>{text(stage_value(process_source, '사출_압력', stage), '')}</div>" for stage in range(10, 0, -1))
    process_distance = "".join(f"<div>{text(stage_value(process_source, '사출_거리', stage), '')}</div>" for stage in range(10, 0, -1))
    resin_mb_value = " / ".join(filter(None, [text(display_raw_material_label), text(display_mb_text)]))
    product_rows_html = f"""
      <table class="product-table">
        <colgroup>
          <col class="c1">
          <col class="stage"><col class="stage"><col class="stage"><col class="stage">
          <col class="stage"><col class="stage">
          <col class="stage"><col class="stage">
          <col class="stage">
          <col class="stage"><col class="stage">
        </colgroup>
        <tr>
          <td class="label">도번</td>
          <td colspan="4">{drawing_no_text}</td>
          <td colspan="2" class="label">금형제작처</td>
          <td colspan="2">{text(project_row.get("mold_vendor_name") if project_row is not None else "", "")}</td>
          <td class="label">제품중량</td>
          <td colspan="2">{text(max(weight_values) if weight_values else "-")}</td>
        </tr>
        <tr>
          <td class="label">품명</td>
          <td colspan="4">{text(sample_row.get("item_name"))}</td>
          <td colspan="2" class="label">양산사출처</td>
          <td colspan="2">선일</td>
          <td class="label">런너중량</td>
          <td colspan="2">{text(op_detail.get("runner_weight"))}</td>
        </tr>
        <tr>
          <td class="label">포장재개발팀</td>
          <td>{text(project_row.get("developer_owner") if project_row is not None else "", "")}</td>
          <td class="label">금형번호</td>
          <td colspan="2">{mold_code_text}</td>
          <td colspan="2" class="label">감리처</td>
          <td colspan="2">{text(project_row.get("supervisor_name") if project_row is not None else "", "")}</td>
          <td class="label">Cavity</td>
          <td colspan="2">{text(cavity_value, "")}</td>
        </tr>
        <tr>
          <td class="label">톤수</td>
          <td>{text(display_machine_ton)}</td>
          <td class="label">호기</td>
          <td colspan="2">{text(display_machine_no)}</td>
          <td colspan="2" class="label">사출RESIN</td>
          <td colspan="2">{text(display_raw_material_label)}</td>
          <td class="label">MB정보</td>
          <td colspan="2">{text(display_mb_text)}</td>
        </tr>
      </table>
    """
    html = f"""
    <style>
      .doc {{
        --row: 18px;
        max-width: 1080px;
        margin: 0 auto;
        border: 2px solid #111;
        background: #fff;
        font-size: 12px;
        color: #111;
      }}
      .title {{
        text-align: center;
        font-size: 20px;
        font-weight: 700;
        min-height: var(--row);
        line-height: var(--row);
        padding: 2px 0;
      }}
      .title-spacer {{
        min-height: var(--row);
      }}
      .section-row {{
        display: grid;
        grid-template-columns: 110px 1fr;
        border-bottom: 1px solid #111;
      }}
      .section-row.product-box {{
        border: 1px solid #111;
        border-bottom: 1px solid #111;
      }}
      .section-label {{
        border-right: 1px solid #111;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        background: #f6f6f6;
      }}
      .section-body {{ min-width: 0; }}
      .section-spacer {{
        min-height: calc(var(--row) * 2);
        border-bottom: 1px solid #111;
      }}
      .info-grid {{
        display: block;
      }}
      .product-table {{
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
      }}
      .product-table .c1 {{
        width: 92px;
      }}
      .product-table .stage {{
        width: calc((100% - 92px) / 11);
      }}
      .product-table td {{
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        height: var(--row);
        padding: 2px 6px;
        vertical-align: middle;
      }}
      .product-table tr:last-child td {{
        border-bottom: 0;
      }}
      .product-table td:last-child {{
        border-right: 0;
      }}
      .product-table td.label {{
        font-weight: 700;
        background: #fafafa;
      }}
      .experiment-block {{ min-height: calc(var(--row) * 25); }}
      .exp-group {{
        border-bottom: 1px solid #111;
      }}
      .exp-group:last-child {{ border-bottom: 0; }}
      .exp-spacer {{
        min-height: var(--row);
        border-bottom: 1px solid #111;
      }}
      .exp-injection-grid {{
        display: grid;
        grid-template-columns: 78px 92px repeat(10, 1fr);
      }}
      .exp-injection-grid > div {{
        min-height: var(--row);
        padding: 2px 2px;
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
      }}
      .exp-injection-grid > div.label {{
        justify-content: flex-start;
        padding-left: 8px;
        background: #fafafa;
        font-weight: 600;
      }}
      .exp-injection-grid > div.title-col {{
        background: #f6f6f6;
        font-weight: 700;
      }}
      .exp-grid-11 {{
        display: grid;
        grid-template-columns: 120px repeat(10, 1fr);
      }}
      .exp-grid-11 > div {{
        min-height: var(--row);
        padding: 2px 2px;
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
      }}
      .exp-grid-11 > div:nth-child(11n+1) {{
        justify-content: flex-start;
        padding-left: 8px;
        background: #fafafa;
        font-weight: 600;
      }}
      .exp-grid-7 {{
        display: grid;
        grid-template-columns: 120px repeat(6, 1fr);
      }}
      .exp-grid-7 > div,
      .exp-grid-5 > div {{
        min-height: var(--row);
        padding: 2px 2px;
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
      }}
      .exp-grid-7 > div:nth-child(7n+1),
      .exp-grid-5 > div:nth-child(5n+1) {{
        justify-content: flex-start;
        padding-left: 8px;
        background: #fafafa;
        font-weight: 600;
      }}
      .exp-grid-5 {{
        display: grid;
        grid-template-columns: 120px repeat(4, 1fr);
      }}
      .exp-table {{
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
      }}
      .exp-hold-wrap {{
        width: calc(170px + ((100% - 170px) / 10 * 5));
      }}
      .exp-feed-wrap {{
        width: calc(170px + ((100% - 170px) / 10 * 6));
      }}
      .exp-temp-wrap {{
        width: calc(170px + ((100% - 170px) / 10 * 5));
      }}
      .exp-temp-block {{
        display: grid;
        grid-template-columns: 78px calc(92px + ((100% - 170px) / 10 * 5));
      }}
      .temp-main-label {{
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #fafafa;
        font-weight: 600;
      }}
      .temp-stack {{
        display: flex;
        flex-direction: column;
      }}
      .temp-title-row {{
        min-height: var(--row);
        padding: 2px 8px;
        border-left: 1px solid #111;
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        background: #fafafa;
        font-weight: 600;
        display: flex;
        align-items: center;
      }}
      .temp-title-row.no-right {{
        border-right: 0;
      }}
      .exp-table td {{
        height: var(--row);
        padding: 2px 2px;
        border-top: 0;
        border-left: 0;
        border-right: 1px solid #111;
        border-bottom: 1px solid #111;
        text-align: center;
        vertical-align: middle;
      }}
      .exp-table tr td:first-child {{
        border-left: 1px solid #111;
      }}
      .exp-table .hold-title {{
        width: 78px;
        background: #fafafa;
        font-weight: 600;
      }}
      .exp-table .hold-label {{
        width: 92px;
      }}
      .exp-table .hold-stage {{
        width: calc((100% - 170px) / 10);
      }}
      .hold-merge-right {{
        border-right: 0 !important;
      }}
      .hold-no-bottom {{
        border-bottom: 0 !important;
      }}
      .hold-no-right {{
        border-right: 0 !important;
      }}
      .pane-heads, .two-pane-body {{
        display: grid;
        grid-template-columns: 5fr 9fr;
      }}
      .pane-heads {{
        margin-top: 0;
      }}
      .pane-heads > div {{
        min-height: var(--row);
        padding: 0 2px 1px;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: flex-start;
        text-align: left;
      }}
      .two-pane-body > div {{
        border-top: 1px solid #111;
        border-bottom: 1px solid #111;
        border-right: 1px solid #111;
      }}
      .two-pane-body > div:first-child {{
        border-left: 1px solid #111;
      }}
      .two-pane-body > div:last-child {{ border-right: 0; }}
      .textbox {{
        min-height: calc(var(--row) * 12);
        padding: 6px 6px;
        white-space: pre-wrap;
        line-height: 1.3;
      }}
      .textbox.small {{
        min-height: calc(var(--row) * 7);
      }}
      .measure-table-wrap {{
        min-height: calc(var(--row) * 12);
      }}
      .measure-table {{
        width: 100%;
        height: 100%;
        border-collapse: collapse;
        table-layout: fixed;
      }}
      .measure-table td {{
        border: 1px solid #111;
        text-align: center;
        vertical-align: middle;
        padding: 1px 1px;
      }}
      .measure-table .head {{
        background: #fafafa;
        font-weight: 700;
      }}
      .measure-table .subhead {{
        background: #fafafa;
        font-weight: 600;
      }}
      .measure-table .top-title {{
        font-size: 14px;
        font-weight: 700;
      }}
    </style>
    <div class="doc">
      <div class="title-spacer"></div>
      <div class="title">성형조건표</div>
      <div class="title-spacer"></div>

      <div style="display:grid; grid-template-columns: 72px 1fr 72px 1fr; font-size:11px; margin-bottom:4px;">
        <div style="padding:2px 6px; font-weight:700;">실험일</div>
        <div style="padding:2px 6px;">{text(experiment_date_text, "")}</div>
        <div style="padding:2px 6px; font-weight:700;">실험자</div>
        <div style="padding:4px 6px;">{text(experimenter_text, "")}</div>
      </div>

      <div class="section-row product-box">
        <div class="section-label">제품정보</div>
        <div class="section-body">
          <div class="info-grid">
            {product_rows_html}
          </div>
        </div>
      </div>

      <div class="section-spacer"></div>

      <div class="section-row">
        <div class="section-label">실험</div>
        <div class="section-body experiment-block">
          <div class="exp-group">
            <div class="exp-injection-grid">
              <div class="title-col" style="grid-row: 1 / span 4;">사출</div>
              <div class="label">단계</div>{process_stage_header}
              <div class="label">속도</div>{process_speed}
              <div class="label">압력</div>{process_pressure}
              <div class="label">거리</div>{process_distance}
            </div>
          </div>
          <div class="exp-group">
            <div class="exp-hold-wrap">
            <table class="exp-table hold-table">
              <colgroup>
                <col style="width:78px">
                <col style="width:92px">
                <col class="hold-stage">
                <col class="hold-stage">
                <col class="hold-stage">
                <col class="hold-stage">
                <col class="hold-stage">
              </colgroup>
              <tr>
                <td rowspan="4" class="hold-title">보압</td>
                <td class="hold-label">단계</td><td>3</td><td>2</td><td>1</td><td colspan="2">쿠션(mm)</td>
              </tr>
              <tr>
                <td class="hold-label">속도(mm/s)</td>
                <td>{text(stage_value(process_source, "보압_속도", 3), "")}</td>
                <td>{text(stage_value(process_source, "보압_속도", 2), "")}</td>
                <td>{text(stage_value(process_source, "보압_속도", 1), "")}</td>
                <td class="hold-merge-right">{text(process_source.get("쿠션"), "")}</td>
                <td>mm</td>
              </tr>
              <tr>
                <td class="hold-label">압력(bar)</td>
                <td>{text(stage_value(process_source, "보압_압력", 3), "")}</td>
                <td>{text(stage_value(process_source, "보압_압력", 2), "")}</td>
                <td>{text(stage_value(process_source, "보압_압력", 1), "")}</td>
                <td class="hold-merge-right hold-no-bottom"></td>
                <td class="hold-no-bottom hold-no-right"></td>
              </tr>
              <tr>
                <td class="hold-label">시간(S)</td>
                <td>{text(stage_value(process_source, "보압_시간", 3), "")}</td>
                <td>{text(stage_value(process_source, "보압_시간", 2), "")}</td>
                <td>{text(stage_value(process_source, "보압_시간", 1), "")}</td>
                <td class="hold-merge-right hold-no-bottom"></td>
                <td class="hold-no-bottom hold-no-right"></td>
              </tr>
            </table>
            </div>
          </div>
          <div class="exp-group">
            <div class="exp-feed-wrap">
              <table class="exp-table feed-table">
                <colgroup>
                  <col style="width:78px">
                  <col style="width:92px">
                  <col class="hold-stage">
                  <col class="hold-stage">
                  <col class="hold-stage">
                  <col class="hold-stage">
                </colgroup>
                <tr>
                  <td rowspan="3" class="hold-title">계량</td>
                  <td class="hold-label">RPM(%)</td>
                  <td>석백전</td>
                  <td>{text(stage_value(process_source, "계량_RPM", 1), "")}</td>
                  <td>{text(stage_value(process_source, "계량_RPM", 2), "")}</td>
                  <td>{text(stage_value(process_source, "계량_RPM", 3), "")}</td>
                  <td>{text(stage_value(process_source, "계량_RPM", 4), "")}</td>
                  <td>석백후</td>
                </tr>
                <tr>
                  <td class="hold-label">거리</td>
                  <td rowspan="2">{text(process_source.get("석백 전"), "")}</td>
                  <td>{text(stage_value(process_source, "계량_거리", 1), "")}</td>
                  <td>{text(stage_value(process_source, "계량_거리", 2), "")}</td>
                  <td>{text(stage_value(process_source, "계량_거리", 3), "")}</td>
                  <td>{text(stage_value(process_source, "계량_거리", 4), "")}</td>
                  <td rowspan="2">{text(process_source.get("석백 후"), "")}</td>
                </tr>
                <tr>
                  <td class="hold-label">배압</td>
                  <td>{text(stage_value(process_source, "계량_배압", 1), "")}</td>
                  <td>{text(stage_value(process_source, "계량_배압", 2), "")}</td>
                  <td>{text(stage_value(process_source, "계량_배압", 3), "")}</td>
                  <td>{text(stage_value(process_source, "계량_배압", 4), "")}</td>
                </tr>
              </table>
            </div>
          </div>
          <div class="exp-group">
            <div class="exp-temp-block">
              <div class="temp-main-label">온도</div>
              <div class="temp-stack">
                <div class="temp-title-row no-right">실린더</div>
                <table class="exp-table temp-table">
                  <colgroup>
                    <col style="width:92px">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                  </colgroup>
                  <tr>
                    <td class="hold-label"></td>
                    <td>NH</td><td>N1</td><td>N2</td><td>N3</td><td>N4</td>
                  </tr>
                  <tr>
                    <td class="hold-label">설정</td>
                    <td>{text(process_source.get("실린더_NH"), "")}</td>
                    <td>{text(process_source.get("실린더_N1"), "")}</td>
                    <td>{text(process_source.get("실린더_N2"), "")}</td>
                    <td>{text(process_source.get("실린더_N3"), "")}</td>
                    <td>{text(process_source.get("실린더_N4"), "")}</td>
                  </tr>
                </table>
                <div class="temp-title-row no-right">금형 온도</div>
                <table class="exp-table temp-table">
                  <colgroup>
                    <col style="width:92px">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                  </colgroup>
                  <tr>
                    <td class="hold-label"></td>
                    <td colspan="2">고정(섭씨)</td>
                    <td colspan="2">이동(섭씨)</td>
                    <td colspan="6">특이사항</td>
                  </tr>
                  <tr>
                    <td class="hold-label">설정</td>
                    <td colspan="2">{text(process_source.get("금형온도_고정"), "")}</td>
                    <td colspan="2">{text(process_source.get("금형온도_이동"), "")}</td>
                    <td colspan="6">{text(process_source.get("금형온도_특이사항") or process_source.get("금형이동_특이사항"), "")}</td>
                  </tr>
                </table>
                <div style="height:var(--row);"></div>
                <div class="temp-title-row no-right">H/R</div>
                <table class="exp-table temp-table">
                  <colgroup>
                    <col style="width:92px">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage">
                    <col class="hold-stage" style="width: calc((100% - 92px) / 10 * 6);">
                  </colgroup>
                  <tr>
                    <td class="hold-label">번호</td>
                    <td>No1</td><td>No2</td><td>No3</td><td>No4</td><td>특이사항</td>
                  </tr>
                  <tr>
                    <td class="hold-label">온도</td>
                    <td>{text(process_source.get("H/R_온도1"), "")}</td><td>{text(process_source.get("H/R_온도2"), "")}</td><td>{text(process_source.get("H/R_온도3"), "")}</td><td>{text(process_source.get("H/R_온도4"), "")}</td><td>{text(process_source.get("H/R_특이사항"), "")}</td>
                  </tr>
                </table>
              </div>
            </div>
          </div>
          <div class="exp-spacer"></div>
          <table class="exp-table temp-table" style="width: calc(170px + ((100% - 170px) / 10 * 7));">
            <colgroup>
              <col style="width:78px">
              <col style="width:92px">
              <col class="hold-stage">
              <col class="hold-stage">
              <col class="hold-stage">
              <col class="hold-stage">
              <col class="hold-stage">
              <col class="hold-stage">
              <col class="hold-stage">
            </colgroup>
            <tr>
              <td rowspan="3" class="hold-label">Cycle Time</td>
              <td></td>
              <td>사출(충전)</td>
              <td>냉각</td>
              <td>회전</td>
              <td>C/T</td>
              <td></td>
              <td colspan="2">취출방법</td>
            </tr>
            <tr>
              <td class="hold-label">1차</td>
              <td>{text(process_source.get("사출(충진)_1차"), "")}</td>
              <td>{text(process_source.get("냉각_1차"), "")}</td>
              <td>{text(process_source.get("회전_1차"), "")}</td>
              <td>{text(process_source.get("C/T_1차"), "")}</td>
              <td></td>
              <td colspan="2">{text(process_source.get("취출방법"), "")}</td>
            </tr>
            <tr>
              <td class="hold-label">2차</td>
              <td>{text(process_source.get("사출(충진)_2차"), "")}</td>
              <td>{text(process_source.get("냉각_2차"), "")}</td>
              <td>{text(process_source.get("회전_2차"), "")}</td>
              <td>{text(process_source.get("C/T_2차"), "")}</td>
              <td></td>
              <td colspan="2"></td>
            </tr>
          </table>
        </div>
      </div>

      <div class="pane-heads">
        <div>[문제점 및 현상]</div>
        <div></div>
      </div>
      <div class="two-pane-body">
        <div class="textbox">{text(final_comment or op_detail.get("문제점_현상"), "")}</div>
        <div class="measure-table-wrap">
          <table class="measure-table">
            <tr>
              <td class="head" rowspan="2">샘플No</td>
              <td class="head top-title" colspan="8">중요부 측정 규격 (mm)</td>
            </tr>
            <tr>
              <td class="subhead" colspan="2">{measure_title_a}</td>
              <td class="subhead" colspan="2">{measure_title_b}</td>
              <td class="subhead" colspan="2">{measure_title_c}</td>
              <td class="subhead" colspan="2">런너중량</td>
            </tr>
            <tr>
              <td class="head">도면규격</td>
              <td class="subhead" colspan="2">{spec_a}</td>
              <td class="subhead" colspan="2">{spec_b}</td>
              <td class="subhead" colspan="2">{spec_c}</td>
              <td class="subhead" colspan="2">{runner_weight_text}</td>
            </tr>
            <tr>
              <td class="head">구분</td>
              <td class="subhead">즉시</td><td class="subhead">24H후</td>
              <td class="subhead">즉시</td><td class="subhead">24H후</td>
              <td class="subhead">즉시</td><td class="subhead">24H후</td>
              <td class="subhead">Cavity</td><td class="subhead">중량</td>
            </tr>
            {measurement_table_rows_html}
          </table>
        </div>
      </div>

      <div class="pane-heads">
        <div>[개선제안]</div>
        <div>[중요부위 치수 점검 내용]</div>
      </div>
      <div class="two-pane-body">
        <div class="textbox small">{text(final_action or op_detail.get("개선사항"), "")}</div>
        <div class="textbox small">{text(point_check_text, "")}</div>
      </div>
    </div>
    """
    return html


def _render_injection_customer_form_preview(
    sample_row: pd.Series,
    item_row: pd.Series | None,
    project_row: pd.Series | None,
    experiment_date_text: str,
    experimenter_text: str,
    requirement_detail: dict,
    instruction_detail: dict,
    condition_detail: dict,
    op_detail: dict,
    after_24h_detail: dict,
    second_measurement_detail: dict,
    quality_comment_detail: dict,
    approval_status: str,
    final_comment: str,
    final_action: str,
) -> str:
    html = _build_injection_customer_form_preview_html(
        sample_row=sample_row,
        item_row=item_row,
        project_row=project_row,
        experiment_date_text=experiment_date_text,
        experimenter_text=experimenter_text,
        requirement_detail=requirement_detail,
        instruction_detail=instruction_detail,
        condition_detail=condition_detail,
        op_detail=op_detail,
        after_24h_detail=after_24h_detail,
        second_measurement_detail=second_measurement_detail,
        quality_comment_detail=quality_comment_detail,
        approval_status=approval_status,
        final_comment=final_comment,
        final_action=final_action,
    )
    components.html(html, height=1600, scrolling=True)
    return html


def _requirement_value_pairs(process_type: str, detail: dict, checks: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for check_name in checks:
        if check_name == "색상":
            nuance = detail.get("color_nuance", "") or detail.get("color_nuance_type", "")
            pairs.append(("색상", f"{detail.get('color_sample_exists', '-') } / {nuance or '-'}"))
        elif check_name == "제품도변경":
            pairs.append(("제품도변경", "변경"))
        elif check_name == "금형수정":
            update_type = detail.get("mold_update_type", "")
            update_note = detail.get("mold_update_detail_extra", "") or detail.get("mold_update_detail", "")
            pairs.append(("금형수정", " / ".join([part for part in [update_type, update_note] if part]) or "변경"))
        elif check_name == "원료실험":
            pairs.append(("원료실험", detail.get("raw_material_experiment_type", "") or "실험"))
        elif check_name == "특정위치규격":
            spec_text = []
            for idx in range(1, 5):
                loc = str(detail.get(f"spec_location_{idx}", "")).strip()
                val = str(detail.get(f"spec_value_{idx}", "")).strip()
                if loc or val:
                    spec_text.append(f"{loc or '-'} / {val or '-'}")
            pairs.append(("특정위치규격", ", ".join(spec_text) if spec_text else "요구 있음"))
        elif check_name == "외관":
            app_text = []
            for idx in range(1, 5):
                item = str(detail.get(f"appearance_item_{idx}", "")).strip()
                pos = str(detail.get(f"appearance_position_{idx}", "")).strip()
                if item or pos:
                    app_text.append(f"{item or '-'} / {pos or '-'}")
            pairs.append(("외관", ", ".join(app_text) if app_text else "요구 있음"))
        elif check_name == "마스킹위치":
            pairs.append(("마스킹위치", detail.get("masking_position", "") or "-"))
        elif check_name == "원화수정":
            pairs.append(("원화수정", "수정"))
        elif check_name == "위치":
            pairs.append(("위치", f"{detail.get('print_position', '-') } / +- {detail.get('print_tolerance_deg', 0)}도"))
        elif check_name == "기능":
            pairs.append(("기능", detail.get("assembly_function_type", "") or detail.get("assembly_function", "") or "-"))
        elif check_name == "부재료사양":
            issue = detail.get("sub_material_issue_type", "") or detail.get("sub_material_other", "")
            pairs.append(("부재료사양", " / ".join([part for part in [detail.get('backing_spec', ''), issue] if part]) or "-"))
        elif check_name == "기타":
            pairs.append(("기타", detail.get("other_request", "") or "-"))
    return pairs


def _build_display_code(base_code: str, revision_no: str, material_variant_no: str) -> str:
    base = str(base_code or "").strip()
    rev = str(revision_no or "").strip()
    material_variant = str(material_variant_no or "").strip()
    if not base:
        return ""
    result = base
    if rev:
        result += f"-R{rev}"
    if material_variant:
        result += f"M{material_variant}"
    return result


def _build_revision_display(revision_no: str, revision_variant_no: str) -> str:
    base_rev = str(revision_no or "").strip()
    variant_rev = str(revision_variant_no or "").strip()
    if variant_rev:
        return variant_rev
    return base_rev


def _build_reference_revision_label(reference_type: str, revision_no: str) -> str:
    ref_type = str(reference_type or "").strip()
    rev = str(revision_no or "").strip()
    if rev.lower() in {"none", "nan"}:
        rev = ""
    if not rev:
        return ""
    if not rev.upper().startswith("R"):
        rev = f"R{rev}"
    if ref_type == "도면":
        return f"도면 {rev}"
    if ref_type == "원화":
        return f"원화 {rev}"
    return f"Rev {rev}"


def _build_display_label(
    display_code: str,
    item_name: str,
    revision_no: str,
    material_label: str,
    color_label: str,
    revision_variant_no: str = "",
    reference_type: str = "",
) -> str:
    parts = [str(display_code or "").strip(), str(item_name or "").strip()]
    rev = _build_reference_revision_label(reference_type, revision_no)
    material = str(material_label or "").strip()
    if rev:
        parts.append(rev)
    if material:
        parts.append(material)
    return " | ".join([part for part in parts if part])


def _get_requirement_identity(detail: dict, fallback_code: str, fallback_name: str) -> tuple[str, str]:
    display_code = str(detail.get("display_code") or fallback_code or "").strip()
    display_label = str(detail.get("display_label") or "").strip()
    if not display_label:
        display_label = _build_display_label(
            display_code,
            fallback_name,
            str(detail.get("revision_no") or ""),
            str(detail.get("material_label") or ""),
            str(detail.get("color_label") or ""),
            str(detail.get("revision_variant_no") or ""),
            str(detail.get("reference_type") or ""),
        )
    if not display_label:
        display_label = " | ".join([part for part in [fallback_code, fallback_name] if part])
    return display_code, display_label


def _clean_label_value(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"none", "nan"} else text


def _next_requirement_variant_no(
    orders_df: pd.DataFrame,
    item_id: int | None,
    detail_key: str,
    selected_order_id: int | None = None,
) -> str:
    if not item_id or orders_df.empty:
        return "1"
    filtered = orders_df[orders_df["item_id"] == int(item_id)].copy()
    if selected_order_id is not None and "experiment_order_id" in filtered.columns:
        filtered = filtered[filtered["experiment_order_id"] != int(selected_order_id)]
    max_no = 0
    for _, row in filtered.iterrows():
        detail = parse_json_text(row.get("requirement_detail_json"))
        raw_value = str(detail.get(detail_key) or "").strip()
        if not raw_value:
            continue
        try:
            max_no = max(max_no, int(raw_value))
        except ValueError:
            continue
    return str(max_no + 1 if max_no > 0 else 1)


def _get_current_film_revision_for_item(project_code: str, item_name: str) -> str:
    project_code = str(project_code or "").strip()
    item_name = str(item_name or "").strip()
    if not project_code or not item_name:
        return ""
    films_df = get_print_films()
    if films_df.empty:
        return ""
    project_df = films_df[films_df["project_code"].fillna("").astype(str) == project_code].copy()
    if project_df.empty:
        return ""
    if "is_current" in project_df.columns:
        current_project_df = project_df[project_df["is_current"] == 1].copy()
        if not current_project_df.empty:
            project_df = current_project_df

    matched_df = project_df[
        project_df["related_item_name"].fillna("").astype(str) == item_name
    ].copy()
    if matched_df.empty:
        item_name_lower = item_name.lower()
        matched_df = project_df[
            project_df["film_name"].fillna("").astype(str).str.lower().apply(
                lambda value: bool(value) and (value in item_name_lower or item_name_lower in value)
            )
        ].copy()
    if matched_df.empty and len(project_df) == 1:
        matched_df = project_df.copy()
    if matched_df.empty:
        return ""
    matched_df = matched_df.sort_values("print_film_id", ascending=False)
    return str(matched_df.iloc[0].get("revision_no") or "").strip()


def _order_pick_label(row: pd.Series) -> str:
    detail = parse_json_text(row.get("requirement_detail_json"))
    _display_code, display_label = _get_requirement_identity(detail, str(row.get("item_code") or ""), str(row.get("item_name") or ""))
    label_parts: list[str] = []
    if "meta_requirement_id" in row.index and pd.notna(row["meta_requirement_id"]):
        meta_row = get_meta_requirement_row(int(row["meta_requirement_id"]))
        if meta_row is not None and meta_row["meta_code"]:
            label_parts.append(str(meta_row["meta_code"]))
    if display_label:
        label_parts.append(display_label)
    label_parts.append(str(row["order_code"]))
    return " | ".join([part for part in label_parts if part])


def _sample_pick_label(sample_row: pd.Series, order_rows: pd.DataFrame | None = None) -> str:
    display_label = ""
    meta_code = ""
    if order_rows is not None and not order_rows.empty and sample_row.get("order_code"):
        matched = order_rows[order_rows["order_code"] == str(sample_row["order_code"])]
        if not matched.empty:
            if "meta_requirement_id" in matched.columns and pd.notna(matched.iloc[0].get("meta_requirement_id")):
                meta_row = get_meta_requirement_row(int(matched.iloc[0]["meta_requirement_id"]))
                if meta_row is not None and meta_row["meta_code"]:
                    meta_code = str(meta_row["meta_code"])
            detail = parse_json_text(matched.iloc[0].get("requirement_detail_json"))
            _, display_label = _get_requirement_identity(
                detail,
                str(matched.iloc[0].get("item_code") or sample_row.get("item_code") or ""),
                str(matched.iloc[0].get("item_name") or sample_row.get("item_name") or ""),
            )
    if not display_label:
        display_label = " | ".join(
            [
                part
                for part in [
                    str(sample_row.get("item_code") or "").strip(),
                    str(sample_row.get("item_name") or sample_row.get("sample_name") or "").strip(),
                ]
                if part
            ]
        )
    label_parts: list[str] = []
    if meta_code:
        label_parts.append(meta_code)
    if display_label:
        label_parts.append(display_label)
    label_parts.append(str(sample_row["sample_code"]))
    return " | ".join([part for part in label_parts if part])


def _instruction_pick_label(instruction_row: pd.Series) -> str:
    due_text = str(instruction_row.get("requested_finish_date") or instruction_row.get("target_due_date") or "").strip()
    return " | ".join(
        [
            part
            for part in [
                str(instruction_row.get("item_code") or "").strip(),
                str(instruction_row.get("item_name") or "").strip(),
                due_text,
                str(instruction_row.get("instruction_code") or "").strip(),
            ]
            if part
        ]
    )


def _upstream_sample_pick_label(sample_row: pd.Series) -> str:
    return " | ".join(
        [
            part
            for part in [
                str(sample_row.get("sample_code") or "").strip(),
                str(sample_row.get("item_code") or "").strip(),
                str(sample_row.get("item_name") or sample_row.get("sample_name") or "").strip(),
            ]
            if part
        ]
    )


def _upstream_instruction_pick_label(instruction_row: pd.Series) -> str:
    return " | ".join(
        [
            part
            for part in [
                str(instruction_row.get("instruction_code") or "").strip(),
                str(instruction_row.get("item_code") or "").strip(),
                str(instruction_row.get("item_name") or "").strip(),
            ]
            if part
        ]
    )


def _order_pick_label(order_row: pd.Series) -> str:
    due_text = str(order_row.get("target_due_date") or "").strip()
    return " | ".join(
        [
            part
            for part in [
                str(order_row.get("item_code") or "").strip(),
                str(order_row.get("item_name") or "").strip(),
                due_text,
                str(order_row.get("order_code") or "").strip(),
            ]
            if part
        ]
    )


def _instruction_order_scope_text(order_row) -> str:
    meta_requirement_id = _safe_int_value(_row_field_value(order_row, "meta_requirement_id"), 0)
    if not meta_requirement_id:
        return "공정"
    meta_row = get_meta_requirement_row(meta_requirement_id)
    if meta_row is None:
        return "조립"
    tree_mode = str(_row_field_value(meta_row, "tree_mode", "") or "").strip()
    meta_code = str(_row_field_value(meta_row, "meta_code", "") or "").strip()
    scope_text = "기본조립" if tree_mode == "기본" else "조합조립" if tree_mode == "조합" else "조립"
    return f"{scope_text} {meta_code}".strip()


def _instruction_order_pick_label(order_row) -> str:
    return " | ".join(
        [
            part
            for part in [
                str(_row_field_value(order_row, "item_code", "") or "").strip(),
                str(_row_field_value(order_row, "item_name", "") or "").strip(),
                _instruction_order_scope_text(order_row),
                str(_row_field_value(order_row, "target_due_date", "-") or "-").strip(),
                str(_row_field_value(order_row, "order_code", "") or "").strip(),
            ]
            if part
        ]
    )


def _assembly_line_status_info(
    *,
    meta_line_row: pd.Series,
    orders_df: pd.DataFrame,
    instructions_df: pd.DataFrame,
    samples_df: pd.DataFrame,
    moves_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    meta_requirement_id: int,
) -> dict:
    item_id = int(meta_line_row["item_id"])
    linked_order_id = (
        int(meta_line_row["linked_experiment_order_id"])
        if "linked_experiment_order_id" in meta_line_row.index and pd.notna(meta_line_row.get("linked_experiment_order_id"))
        else None
    )
    line_orders = orders_df[
        (pd.to_numeric(orders_df["meta_requirement_id"], errors="coerce") == int(meta_requirement_id))
        & (pd.to_numeric(orders_df["item_id"], errors="coerce") == item_id)
    ].sort_values("experiment_order_id", ascending=False) if not orders_df.empty else orders_df
    order_row = line_orders.iloc[0] if not line_orders.empty else None
    if order_row is None and linked_order_id and not orders_df.empty:
        linked_match = orders_df[
            pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == int(linked_order_id)
        ].sort_values("experiment_order_id", ascending=False)
        if not linked_match.empty:
            order_row = linked_match.iloc[0]
    if order_row is None:
        return {
            "status": "미요구",
            "status_kind": "none",
            "order_row": None,
            "instruction_row": None,
            "sample_row": None,
            "move_row": None,
            "is_ready": False,
            "is_experiment_target": False,
            "is_stock_target": False,
            "blocks_descendants": False,
        }
    order_detail = parse_json_text(order_row["requirement_detail_json"])
    execution_mode = str(order_detail.get("execution_mode") or "")
    predecessor_links = [link for link in (order_detail.get("predecessor_links", []) or []) if isinstance(link, dict)]
    uses_stock_predecessor = any(
        str(link.get("source_mode") or "") == "재고품" and link.get("source_sample_id")
        for link in predecessor_links
    )
    line_instructions = instructions_df[
        pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == int(order_row["experiment_order_id"])
    ].sort_values("experiment_instruction_id", ascending=False) if not instructions_df.empty else instructions_df
    instruction_row = line_instructions.iloc[0] if not line_instructions.empty else None
    sample_row = None
    if instruction_row is not None:
        line_samples = samples_df[
            pd.to_numeric(samples_df["experiment_instruction_id"], errors="coerce") == int(instruction_row["experiment_instruction_id"])
        ].sort_values("sample_id", ascending=False) if not samples_df.empty else samples_df
        if not line_samples.empty:
            sample_row = line_samples.iloc[0]
    line_moves = moves_df[
        (pd.to_numeric(moves_df["source_order_id"], errors="coerce") == int(order_row["experiment_order_id"]))
        & moves_df["wms_kind"].isin(["공정품출고지시", "전공정품출고지시"])
    ].sort_values("postprocess_move_id", ascending=False) if not moves_df.empty else moves_df
    move_row = line_moves.iloc[0] if not line_moves.empty else None
    if execution_mode == "재고사용":
        move_status = str(move_row["status"] or "") if move_row is not None else ""
        stock_sample_id = int(order_detail.get("stock_sample_id")) if order_detail.get("stock_sample_id") else None
        if not stock_sample_id:
            predecessor_links = [link for link in (order_detail.get("predecessor_links", []) or []) if isinstance(link, dict)]
            stock_link = next((link for link in predecessor_links if str(link.get("source_mode") or "") == "재고품" and link.get("source_sample_id")), None)
            stock_sample_id = int(stock_link.get("source_sample_id")) if stock_link and stock_link.get("source_sample_id") else None
        requested_qty = float(order_row["required_sample_qty"] or 0)
        qty_available = None
        can_dispatch = None
        if stock_sample_id and not inventory_df.empty and "sample_id" in inventory_df.columns:
            inventory_match = inventory_df[pd.to_numeric(inventory_df["sample_id"], errors="coerce") == int(stock_sample_id)]
            if not inventory_match.empty:
                inventory_row = inventory_match.iloc[0]
                qty_on_hand = float(inventory_row.get("qty_on_hand") or 0)
                qty_reserved = float(inventory_row.get("qty_reserved") or 0)
                current_reserved = 0.0
                if move_row is not None and str(move_status or "") == "출고대기":
                    current_reserved = float(move_row.get("requested_qty") or 0)
                qty_available = qty_on_hand - max(qty_reserved - current_reserved, 0)
                can_dispatch = qty_available + 1e-9 >= requested_qty
        if move_status == "출고완료":
            base_status = "출고완료"
        elif move_status in ("출고대기", "최종검토대기"):
            base_status = "출고대기"
        else:
            base_status = "출고미생성"
        status = base_status
        if qty_available is not None:
            status = f"{status} / {'가능' if can_dispatch else '부족'} ({qty_available:.0f}/{requested_qty:.0f})"
        return {
            "status": status,
            "status_kind": "stock",
            "order_row": order_row,
            "instruction_row": instruction_row,
            "sample_row": sample_row,
            "move_row": move_row,
            "is_ready": base_status in ("출고대기", "출고완료"),
            "is_experiment_target": False,
            "is_stock_target": True,
            "blocks_descendants": True,
        }
    if sample_row is not None:
        status = "샘플완료"
    elif instruction_row is not None:
        status = "지시완료"
    else:
        status = "지시필요"
    return {
        "status": status,
        "status_kind": "experiment",
        "order_row": order_row,
        "instruction_row": instruction_row,
        "sample_row": sample_row,
        "move_row": move_row,
        "is_ready": status in ("지시완료", "샘플완료"),
        "is_experiment_target": True,
        "is_stock_target": False,
        "blocks_descendants": uses_stock_predecessor,
    }


def _find_sample_row_by_id(samples_df: pd.DataFrame, sample_id: int | None) -> pd.Series | None:
    if sample_id is None or samples_df.empty:
        return None
    matched = samples_df[pd.to_numeric(samples_df["sample_id"], errors="coerce") == int(sample_id)]
    return matched.iloc[0] if not matched.empty else None


def _build_requirement_content_summary(process_type: str, order_detail: dict, selected_order_row: pd.Series) -> str:
    parts: list[str] = []
    goal = str(selected_order_row.get("experiment_goal") or "").strip()
    if goal:
        parts.append(goal)
    if process_type in ("후가공", "사상"):
        color_text = str(order_detail.get("color_nuance") or "").strip()
        if color_text:
            parts.append(f"색상 {color_text}")
        color_sample_text = str(order_detail.get("color_sample_exists") or "").strip()
        if color_sample_text:
            parts.append(f"색상샘플 {color_sample_text}")
        masking_text = str(order_detail.get("masking_position") or "").strip()
        if masking_text:
            parts.append(f"마스킹 {masking_text}")
    elif process_type == "인쇄":
        color_text = str(order_detail.get("color_nuance") or "").strip()
        if color_text:
            parts.append(f"색상 {color_text}")
        color_sample_text = str(order_detail.get("color_sample_exists") or "").strip()
        if color_sample_text:
            parts.append(f"색상샘플 {color_sample_text}")
        print_position_text = str(order_detail.get("print_position") or "").strip()
        if print_position_text:
            parts.append(f"위치 {print_position_text}")
    return " / ".join(parts) if parts else "-"


def _render_injection_instruction_summary(
    *,
    instruction_code: str,
    instruction_date: str,
    requested_date: str,
    sample_qty: str,
    mold_code: str,
    raw_material_label: str,
    mb_request_code: str,
    machine_no: str,
    machine_ton: str,
    key_prefix: str,
) -> None:
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.caption("지시번호")
            st.write(instruction_code or "-")
            st.caption("요청일")
            st.write(requested_date or "-")
            st.caption("샘플수")
            st.write(sample_qty or "-")
        with col2:
            st.caption("금형코드")
            st.write(mold_code or "-")
            st.caption("MB의뢰코드")
            st.write(mb_request_code or "-")
            st.caption("원료명")
            st.write(raw_material_label or "-")
        with col3:
            st.caption("호기")
            st.write(machine_no or "-")
            st.caption("톤수")
            st.write(machine_ton or "-")


def _render_injection_requirement_summary(
    *,
    order_row: pd.Series,
    order_detail: dict,
) -> None:
    with st.container(border=True):
        sum_c1, sum_c2 = st.columns(2)
        with sum_c1:
            st.caption("요구일")
            st.write(str(order_row.get("requirement_date") or "-"))
            st.caption("납기일")
            st.write(str(order_row["target_due_date"] or "-"))
            st.caption("마일스톤")
            st.write(order_row["milestone_name"] or "-")
            st.caption("금형수정")
            st.write("있음" if order_detail.get("mold_dispatch_required") else "없음")
            st.caption("색상실험")
            st.write("있음" if order_detail.get("color_required") else "없음")
            st.caption("원료실험")
            st.write("있음" if order_detail.get("raw_material_experiment_required") else "없음")
        with sum_c2:
            st.caption("수량")
            st.write(str(order_row["required_sample_qty"] or "-"))
            st.caption("요구코드")
            st.write(str(order_row["order_code"] or "-"))
            st.caption("도면/그외")
            st.write(order_detail.get("drawing_change_source", "-") or "-")
            st.caption("색상샘플")
            st.write(order_detail.get("color_sample_exists", "-") or "-")
            st.caption("원료명")
            raw_name_text = " / ".join(
                [value for value in [order_detail.get("raw_material_1_label", ""), order_detail.get("raw_material_2_label", "")] if value]
            ) or "-"
            st.write(raw_name_text)


def _render_product_drawing_reference_body(item_id: int) -> None:
    drawing = get_current_product_drawing_for_item(item_id)
    if not drawing:
        st.caption("연결된 제품도면이 없습니다.")
        return
    if drawing.get("used_fallback"):
        st.warning("Item에 직접 연결된 도면이 없어 프로젝트의 최신 도면을 대신 표시합니다.")
    st.write(f"도면번호: {drawing['drawing_no']}")
    st.write(f"도면명: {drawing['drawing_name']}")
    st.write(f"리비전: {drawing['revision_no']}")
    if drawing.get("file_note"):
        st.write(f"메모: {drawing['file_note']}")
    file_path = drawing.get("file_path")
    if not file_path:
        st.caption("첨부 파일은 없고 메모만 등록되어 있습니다.")
        return
    st.write(f"파일: {file_path}")
    path = Path(file_path)
    if path.exists():
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg"}:
            st.image(str(path), caption=path.name)


def _execution_mode_ui_value(value: str) -> str:
    return "외부" if str(value or "").strip() in {"외주", "외부"} else "내부"


def _execution_mode_storage_value(value: str) -> str:
    return "외주" if str(value or "").strip() == "외부" else "내부"


def _review_text(value: object, default: str = "미입력") -> str:
    raw = "" if value is None else str(value).strip()
    return raw or default


def render_customer_requirements_page(requirement_scope: str = "공정품") -> None:
    page_name = "공정품 요구" if requirement_scope == "공정품" else "조립품 요구"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = list_project_options()
    df = list_experiment_orders()
    samples_df = list_experiment_samples()
    bom_df = get_item_bom()
    instructions_df = list_experiment_instructions() if requirement_scope == "조립품" else pd.DataFrame()
    if requirement_scope == "조립품":
        try:
            moves_df = operations_service.list_postprocess_item_moves()
        except Exception:
            moves_df = pd.DataFrame()
        try:
            inventory_df = operations_service.list_sample_inventory()
        except Exception:
            inventory_df = pd.DataFrame()
    else:
        moves_df = pd.DataFrame()
        inventory_df = pd.DataFrame()
    project_code = ""
    if can_edit(page_name):
        if requirement_scope == "조립품":
            top_c1, top_c2, top_c3, top_c4 = st.columns([1, 1, 0.8, 1.1])
        else:
            top_c1, top_c2, top_c3 = st.columns([1, 1, 0.8])
        with top_c1:
            project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="requirement_project_label")
        project_code = project_label.split(" | ")[0] if project_label else ""
        project_row = get_project_by_code(project_code) if project_code else None
        product_options = list_product_options_for_project(project_code) if project_code else []
        with top_c2:
            product_label = st.selectbox("상품", options=[""] + [label for label, _ in product_options], key="requirement_product_label")
        with top_c3:
            if requirement_scope == "조립품":
                tree_mode = st.selectbox("구성 방식", options=["기본", "조합"], key=f"requirement_tree_mode_{requirement_scope}")
            else:
                tree_mode = "기본"
                st.text_input("구성 방식", value="기본", disabled=True, key=f"requirement_tree_mode_{requirement_scope}_display")
        selected_product_id = dict(product_options).get(product_label) if product_label else None
        selection_scope = f"{requirement_scope}_{tree_mode}_{selected_product_id}_{project_code}"
        selection_state_key = f"requirement_edit_item_id_{selection_scope}"
        active_meta_key = f"requirement_active_meta_id_{selection_scope}"
        meta_mode_key = f"requirement_meta_mode_{selection_scope}"
        products_df = get_products()
        selected_product_row = (
            products_df[products_df["product_id"] == int(selected_product_id)].iloc[0]
            if selected_product_id and not products_df.empty and not products_df[products_df["product_id"] == int(selected_product_id)].empty
            else None
        )
        if requirement_scope == "조립품":
            meta_options_rows = list_meta_requirements_for_context(
                int(selected_product_row["project_id"]) if selected_product_row is not None and pd.notna(selected_product_row.get("project_id")) else None,
                int(selected_product_id) if selected_product_id else None,
                tree_mode,
            )
            current_meta_id = st.session_state.get(active_meta_key)
            current_meta_mode = st.session_state.get(meta_mode_key, "new")
            meta_options = [("신규 선택", None)] + [
                (f"{row['meta_code']} | {row['title'] or row['tree_mode']}", int(row["meta_requirement_id"]))
                for row in meta_options_rows
            ]
            with top_c4:
                selected_meta_label = st.selectbox(
                    "메타코드",
                    options=[label for label, _ in meta_options],
                    index=(
                        0
                        if current_meta_mode == "new"
                        else (
                            1 + [mid for _, mid in meta_options[1:]].index(int(current_meta_id))
                            if current_meta_id and any(mid == int(current_meta_id) for _, mid in meta_options[1:])
                            else 0
                        )
                    ) if meta_options else 0,
                    key=f"requirement_meta_label_{selection_scope}",
                )
            selected_meta_id = dict(meta_options).get(selected_meta_label) if selected_meta_label else None
            if selected_meta_label == "신규 선택":
                # 신규 선택은 두 가지 경우가 있습니다.
                # 1) 정말 새 메타를 시작하려고 기존 메타에서 돌아온 경우 -> active meta 초기화
                # 2) 방금 생성한 신규 메타 흐름을 계속 이어가는 경우 -> active meta 유지
                if current_meta_mode == "existing":
                    st.session_state.pop(active_meta_key, None)
                st.session_state[meta_mode_key] = "new"
            elif selected_meta_id:
                st.session_state[active_meta_key] = int(selected_meta_id)
                st.session_state[meta_mode_key] = "existing"
            elif active_meta_key in st.session_state:
                st.session_state.pop(active_meta_key, None)
                st.session_state[meta_mode_key] = "new"
            meta_marker_key = f"requirement_meta_marker_{selection_scope}"
            current_meta_marker = int(selected_meta_id) if selected_meta_id else 0
            if st.session_state.get(meta_marker_key) != current_meta_marker:
                st.session_state[meta_marker_key] = current_meta_marker
                st.session_state.pop(selection_state_key, None)
        active_meta_id = st.session_state.get(active_meta_key) if active_meta_key and requirement_scope != "공정품" else None
        active_meta_row = get_meta_requirement_row(active_meta_id) if active_meta_id and requirement_scope == "조립품" else None
        active_meta_lines = list_meta_requirement_lines(active_meta_id) if active_meta_id and requirement_scope == "조립품" else []
        active_meta_line_ids = {
            int(row["item_id"])
            for row in active_meta_lines
            if row["item_id"] is not None and pd.notna(row["item_id"])
        }
        active_meta_line_map = {
            int(row["item_id"]): int(row["meta_line_id"])
            for row in active_meta_lines
            if row["item_id"] is not None and pd.notna(row["item_id"])
        }
        active_meta_line_row_map = {
            int(row["item_id"]): row
            for row in active_meta_lines
            if row["item_id"] is not None and pd.notna(row["item_id"])
        }
        root_item_id = None
        if selected_product_row is not None:
            linked_item_id = selected_product_row.get("linked_item_id")
            root_source_id = linked_item_id if pd.notna(linked_item_id) else selected_product_row.get("root_item_id")
            root_item_id = int(root_source_id) if pd.notna(root_source_id) else None
        product_link_missing = bool(
            selected_product_id
            and (
                selected_product_row is None
                or root_item_id is None
            )
        )
        if product_link_missing:
            st.warning("선택한 상품에 연결된 공정품이 없습니다. `관리자 > 상품`에서 연결 공정품을 선택해 저장한 뒤 다시 진행해 주세요.")
            return
        active_child_meta_line_ids = {
            int(row["item_id"])
            for row in active_meta_lines
            if row["item_id"] is not None and pd.notna(row["item_id"]) and (root_item_id is None or int(row["item_id"]) != int(root_item_id))
        }
        tree_items = (
            list_project_item_tree_options(project_code, int(selected_product_id))
            if project_code and selected_product_id
            else []
        )
        current_meta_mode = st.session_state.get(meta_mode_key, "new") if requirement_scope == "조립품" else "new"
        if requirement_scope == "조립품" and root_item_id and not bom_df.empty:
            descendant_ids: set[int] = set()
            pending = [int(root_item_id)]
            while pending:
                parent_id = pending.pop(0)
                child_rows = bom_df[bom_df["parent_item_id"] == parent_id]
                for _, child_row in child_rows.iterrows():
                    child_id = int(child_row["child_item_id"])
                    if child_id not in descendant_ids:
                        descendant_ids.add(child_id)
                        pending.append(child_id)
            tree_items = [(label, iid) for label, iid in tree_items if iid in descendant_ids]
        elif selected_product_id and tree_mode == "조합":
            items_df = list_items()
            product_items_df = items_df[items_df["product_id"] == selected_product_id].copy() if not items_df.empty else items_df.iloc[0:0]
            tree_items = [
                (f"{str(row['item_code']).strip()} | {str(row['item_name']).strip()}", int(row["item_id"]))
                for _, row in product_items_df.iterrows()
            ]
            if requirement_scope == "조립품" and current_meta_mode == "existing" and active_meta_line_ids:
                tree_items = [(label, iid) for label, iid in tree_items if iid in active_meta_line_ids]
        if selected_product_id and tree_items:
            filtered_tree_items: list[tuple[str, int]] = []
            for label, iid in tree_items:
                item_row = get_item_row(iid)
                process_type = infer_process_type_from_item(item_row)
                if requirement_scope == "공정품" and process_type != "조립":
                    filtered_tree_items.append((label, iid))
                elif requirement_scope == "조립품" and process_type != "조립":
                    filtered_tree_items.append((label, iid))
            tree_items = filtered_tree_items
        tree_generated = bool(project_code and selected_product_id)
        if tree_generated and project_code and not tree_items:
            st.warning("선택한 상품에 등록된 공정품이 없습니다. 먼저 공정품 정보를 확인해 주세요.")

        left_col, right_col = st.columns([0.55, 2.45])

        if requirement_scope == "조립품" and active_meta_id:
            status_df = df[
                (df["project_code"] == project_code)
                & (df["meta_requirement_id"] == int(active_meta_id))
            ].copy()
        else:
            status_df = df[df["project_code"] == project_code].copy() if project_code else df.iloc[0:0]
        item_status_map: dict[int, str] = {}
        saved_item_ids: set[int] = set()
        if not status_df.empty:
            if "experiment_order_id" in status_df.columns:
                status_df = status_df.sort_values("experiment_order_id")
            for _, row in status_df.iterrows():
                if pd.notna(row.get("item_id")):
                    item_id = int(row["item_id"])
                    saved_item_ids.add(item_id)
                    item_status_map[item_id] = str(row.get("status") or "진행중")

        assembly_requires_meta = bool(requirement_scope == "조립품" and not active_meta_id)
        combo_initial_selection_mode = bool(
            requirement_scope == "조립품"
            and tree_mode == "조합"
            and active_meta_id
            and not active_child_meta_line_ids
        )
        combo_existing_meta_mode = bool(
            requirement_scope == "조립품"
            and tree_mode == "조합"
            and active_meta_id
            and current_meta_mode == "existing"
            and not combo_initial_selection_mode
        )
        assembly_all_child_ready = False

        with left_col:
            render_section_title("공정품 트리")
            tree_display_options = []
            root_tree_display_label = ""
            selected_product_name = str(selected_product_row["product_name"] or "") if selected_product_row is not None and "product_name" in selected_product_row.index else ""
            if requirement_scope == "조립품" and root_item_id:
                root_item_row = get_item_row(root_item_id)
                root_item_code = str(root_item_row["item_code"] or "루트 조립품") if root_item_row is not None and "item_code" in root_item_row.keys() else "루트 조립품"
                root_item_name = str(root_item_row["item_name"] or "") if root_item_row is not None and "item_name" in root_item_row.keys() else ""
                if tree_mode == "조합" and active_meta_row is not None and "meta_code" in active_meta_row.keys() and active_meta_row["meta_code"]:
                    root_item_code = str(active_meta_row["meta_code"] or root_item_code)
                root_tree_display_label = f"{root_item_code} | {root_item_name} | 조립"
            for label, iid in tree_items:
                if " | " in label:
                    parts = label.split(" | ")
                    prefix = ""
                    first = parts[0]
                    if first.strip() != first:
                        prefix = first[: len(first) - len(first.lstrip())]
                    item_code = first.strip()
                    item_name = parts[1].strip() if len(parts) > 1 else ""
                    process_type = parts[2].strip() if len(parts) > 2 else ""
                    if not process_type:
                        display_item_row = get_item_row(iid)
                        process_type = infer_process_type_from_item(display_item_row)
                    tree_display_options.append((f"{prefix}{item_code} | {item_name} | {process_type}", iid))
                else:
                    tree_display_options.append((label, iid))
            selected_item_label = ""
            selected_item_id = None
            checked_tree_options: list[tuple[str, int]] = []
            if assembly_requires_meta:
                st.caption("조립공정 요구를 먼저 저장해 메타를 생성하면 공정품 트리가 열립니다.")
            elif tree_generated and tree_display_options:
                st.caption("선택 | 공정품 | 상태 | 입력")
                if requirement_scope == "조립품" and tree_mode == "조합":
                    if combo_initial_selection_mode or current_meta_mode == "new":
                        st.caption("조합은 필요한 공정품만 체크한 뒤 `공정품 구성 저장`을 누르고 입력합니다.")
                    else:
                        st.caption("조합에 포함된 공정품만 표시됩니다. 필요한 공정품을 선택해 입력합니다.")
                assembly_status_map: dict[int, str] = {}
                assembly_all_child_ready = False
                root_status_text = "미입력"
                if requirement_scope == "조립품" and active_meta_lines:
                    active_meta_df = pd.DataFrame(active_meta_lines)
                    if selected_product_id and root_item_id and not active_meta_df.empty and "item_id" in active_meta_df.columns:
                        active_meta_df = active_meta_df[
                            pd.to_numeric(active_meta_df["item_id"], errors="coerce") != int(root_item_id)
                        ].copy()
                    if active_meta_id and not moves_df.empty:
                        order_ids_for_meta = pd.to_numeric(
                            df[
                                pd.to_numeric(df.get("meta_requirement_id"), errors="coerce") == int(active_meta_id)
                            ]["experiment_order_id"],
                            errors="coerce",
                        )
                        instruction_ids_for_meta = pd.to_numeric(
                            instructions_df[
                                pd.to_numeric(instructions_df.get("experiment_order_id"), errors="coerce").isin(order_ids_for_meta)
                            ]["experiment_instruction_id"],
                            errors="coerce",
                        ) if not instructions_df.empty else pd.Series(dtype="float64")
                        moves_for_meta = moves_df[
                            (pd.to_numeric(moves_df.get("source_order_id"), errors="coerce").isin(order_ids_for_meta))
                            | (pd.to_numeric(moves_df.get("source_instruction_id"), errors="coerce").isin(instruction_ids_for_meta))
                        ].copy()
                    else:
                        moves_for_meta = moves_df
                    if not active_meta_df.empty:
                        assembly_all_child_ready = True
                        parent_meta_line_map = {
                            int(row["meta_line_id"]): int(row["parent_meta_line_id"])
                            for _, row in active_meta_df.iterrows()
                            if pd.notna(row.get("meta_line_id")) and pd.notna(row.get("parent_meta_line_id"))
                        }
                        stock_target_parent_ids: set[int] = set()
                        sorted_line_rows = active_meta_df.sort_values(["level_no", "line_order", "meta_line_id"])
                        for _, line_row in sorted_line_rows.iterrows():
                            meta_line_id = int(line_row["meta_line_id"])
                            ancestor_meta_line_id = parent_meta_line_map.get(meta_line_id)
                            is_excluded = False
                            while ancestor_meta_line_id is not None:
                                if int(ancestor_meta_line_id) in stock_target_parent_ids:
                                    is_excluded = True
                                    break
                                ancestor_meta_line_id = parent_meta_line_map.get(int(ancestor_meta_line_id))
                            if is_excluded:
                                assembly_status_map[int(line_row["item_id"])] = "미사용"
                                continue
                            line_status = _assembly_line_status_info(
                                meta_line_row=line_row,
                                orders_df=df,
                                instructions_df=instructions_df,
                                samples_df=samples_df,
                                moves_df=moves_for_meta,
                                inventory_df=inventory_df,
                                meta_requirement_id=int(active_meta_id),
                            )
                            assembly_status_map[int(line_row["item_id"])] = "요구저장" if line_status["order_row"] is not None else "미요구"
                            assembly_all_child_ready = assembly_all_child_ready and bool(line_status["order_row"] is not None)
                            if bool(line_status.get("blocks_descendants")) and line_status["order_row"] is not None:
                                stock_target_parent_ids.add(meta_line_id)
                if requirement_scope == "조립품" and root_item_id:
                    root_df = df[
                        (df["project_code"] == project_code)
                        & (pd.to_numeric(df["item_id"], errors="coerce") == int(root_item_id))
                    ].copy() if project_code else df.iloc[0:0]
                    if active_meta_id and not root_df.empty and "meta_requirement_id" in root_df.columns:
                        root_df = root_df[pd.to_numeric(root_df["meta_requirement_id"], errors="coerce") == int(active_meta_id)].copy()
                    if not root_df.empty:
                        root_df = root_df.sort_values("experiment_order_id")
                        latest_root_status = str(root_df.iloc[-1].get("status") or "")
                        if latest_root_status == "취소":
                            root_status_text = "취소"
                        elif latest_root_status == "완료":
                            root_status_text = "완료"
                        else:
                            root_status_text = "요구저장"
                    elif active_meta_row is not None and "status" in active_meta_row.keys() and active_meta_row["status"]:
                        root_status_text = str(active_meta_row["status"] or "미입력")
                if requirement_scope == "조립품" and root_tree_display_label:
                    root_c1, root_c2, root_c3, root_c4 = st.columns([0.55, 1.0, 0.8, 0.65])
                    with root_c1:
                        st.checkbox(
                            "",
                            value=True,
                            key=f"requirement_tree_root_checked_{selection_scope}_{active_meta_id or 'new'}",
                            label_visibility="collapsed",
                            disabled=True,
                        )
                    with root_c2:
                        _compact_tree_item_label(root_tree_display_label, selected_product_name)
                    with root_c3:
                        st.caption(root_status_text)
                    with root_c4:
                        if st.button("입력", key=f"requirement_edit_btn_{selection_scope}_root", use_container_width=True):
                            st.session_state[selection_state_key] = int(root_item_id)
                for label, iid in tree_display_options:
                    check_key = f"requirement_tree_checked_{selection_scope}_{active_meta_id or 'new'}_{iid}"
                    default_checked = bool(
                        requirement_scope == "조립품"
                        and (
                            (tree_mode == "기본" and not active_meta_id)
                            or (active_meta_id and iid in active_meta_line_ids)
                        )
                    )
                    row_c1, row_c2, row_c3, row_c4 = st.columns([0.55, 1.0, 0.8, 0.65])
                    with row_c1:
                        is_checked = st.checkbox(
                            "",
                            value=default_checked,
                            key=check_key,
                            label_visibility="collapsed",
                            disabled=combo_existing_meta_mode,
                        )
                    if is_checked:
                        if requirement_scope == "조립품" and iid in assembly_status_map:
                            status_text = assembly_status_map[iid]
                        elif iid in item_status_map:
                            status_text = "취소" if item_status_map[iid] == "취소" else "진행중"
                        else:
                            status_text = "미입력"
                    else:
                        status_text = ""
                    with row_c2:
                        _compact_tree_item_label(label, selected_product_name)
                    with row_c3:
                        st.caption(status_text)
                    with row_c4:
                        child_input_disabled = bool(
                            requirement_scope == "조립품"
                            and tree_mode == "조합"
                            and active_meta_id
                            and (current_meta_mode == "new" or combo_initial_selection_mode)
                            and (not root_item_id or int(iid) != int(root_item_id))
                        )
                        if st.button(
                            "입력",
                            key=f"requirement_edit_btn_{selection_scope}_{iid}",
                            use_container_width=True,
                            disabled=child_input_disabled,
                        ):
                            st.session_state[selection_state_key] = iid
                    if is_checked:
                        checked_tree_options.append((label, iid))
                if requirement_scope == "조립품" and tree_mode == "조합" and active_meta_id and (current_meta_mode == "new" or combo_initial_selection_mode):
                    if st.button(
                        "공정품 구성 저장",
                        key=f"save_meta_lines_{selection_scope}_{active_meta_id}",
                        use_container_width=True,
                    ):
                        selected_line_ids = [iid for _, iid in checked_tree_options]
                        if not selected_line_ids:
                            st.error("조합에 포함할 공정품을 하나 이상 체크해 주세요.")
                            st.stop()
                        save_meta_requirement_lines(
                            meta_requirement_id=int(active_meta_id),
                            root_item_id=int(root_item_id) if root_item_id else 0,
                            tree_mode="조합",
                            selected_item_ids=selected_line_ids,
                        )
                        st.session_state[meta_mode_key] = "existing"
                        flash_success("조합 공정품 구성을 저장했습니다.")
                        st.rerun()
                if checked_tree_options:
                    checked_ids = [iid for _, iid in checked_tree_options]
                    current_selected_id = st.session_state.get(selection_state_key)
                    if (
                        requirement_scope == "조립품"
                        and tree_mode == "기본"
                    ):
                        if current_selected_id not in checked_ids:
                            current_selected_id = None
                            st.session_state.pop(selection_state_key, None)
                    elif requirement_scope != "조립품" and current_selected_id not in checked_ids:
                        current_selected_id = checked_ids[0]
                        st.session_state[selection_state_key] = current_selected_id
                    selected_item_id = current_selected_id
                    selected_item_label = next((label for label, iid in checked_tree_options if iid == selected_item_id), "")
                    if selected_item_label:
                        selected_item_row_for_caption = get_item_row(int(selected_item_id)) if selected_item_id else None
                        selected_item_code_for_caption = (
                            str(selected_item_row_for_caption["item_code"] or "").strip()
                            if selected_item_row_for_caption is not None and "item_code" in selected_item_row_for_caption.keys()
                            else ""
                        )
                        selected_item_name_for_caption = (
                            str(selected_item_row_for_caption["item_name"] or "").strip()
                            if selected_item_row_for_caption is not None and "item_name" in selected_item_row_for_caption.keys()
                            else ""
                        )
                        if selected_item_code_for_caption and selected_item_name_for_caption:
                            selected_item_display = f"{selected_item_code_for_caption} | {selected_item_name_for_caption}"
                        else:
                            selected_item_display = selected_item_label
                        st.caption(f"현재 편집: {selected_item_display}")
                    elif requirement_scope == "조립품" and tree_mode == "기본":
                        st.caption("현재 편집: 최종 조립품")
                    elif requirement_scope == "조립품" and tree_mode == "조합":
                        st.caption("현재 편집: 루트 조립품")
                else:
                    if combo_existing_meta_mode:
                        st.caption("조합에 포함된 공정품이 없습니다.")
                    else:
                        st.caption("요구를 만들 공정품을 체크해 주세요.")
            elif not tree_generated:
                st.caption("프로젝트와 상품을 선택해 주세요.")
            else:
                st.caption("선택 가능한 공정품이 없습니다.")

        if requirement_scope == "조립품" and root_item_id and not selected_item_id:
            selected_item_id = int(root_item_id)
            root_item_row = get_item_row(selected_item_id)
            if root_item_row is not None and not selected_item_label:
                selected_item_label = str(root_item_row["item_code"] or "최종 조립품") if "item_code" in root_item_row.keys() else "최종 조립품"

        selected_item_row = get_item_row(selected_item_id)
        selected_meta_line_row = (
            active_meta_line_row_map.get(int(selected_item_id))
            if requirement_scope == "조립품" and selected_item_id and active_meta_line_row_map
            else None
        )
        combo_child_line_missing = bool(
            requirement_scope == "조립품"
            and tree_mode == "조합"
            and active_meta_id
            and selected_item_id
            and root_item_id
            and int(selected_item_id) != int(root_item_id)
            and selected_meta_line_row is None
        )
        filtered_df = df[(df["project_code"] == project_code) & (df["item_id"] == selected_item_id)].copy() if project_code and selected_item_id else df.iloc[0:0]
        if active_meta_id and not filtered_df.empty and "meta_requirement_id" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["meta_requirement_id"] == int(active_meta_id)].copy()
        is_existing_meta_edit_mode = bool(
            requirement_scope == "조립품"
            and active_meta_id
            and st.session_state.get(meta_mode_key) == "existing"
        )
        can_create_new_requirement_for_selected_item = bool(
            requirement_scope == "조립품"
            and active_meta_id
            and selected_item_id
            and int(selected_item_id) in active_meta_line_ids
            and filtered_df.empty
        )
        if is_existing_meta_edit_mode:
            requirement_choices = filtered_df.apply(_order_pick_label, axis=1).tolist() if not filtered_df.empty else []
            if can_create_new_requirement_for_selected_item:
                requirement_choices = ["신규 등록"]
        else:
            requirement_choices = ["신규 등록"]
            if not filtered_df.empty:
                requirement_choices += filtered_df.apply(_order_pick_label, axis=1).tolist()
        requirement_pick_key = f"requirement_pick_{selection_scope}_{active_meta_id or 'new'}_{selected_item_id or 'none'}"
        default_requirement_label = "신규 등록"
        if (
            requirement_scope == "조립품"
            and active_meta_id
            and selected_item_id
            and root_item_id
            and int(selected_item_id) == int(root_item_id)
            and not filtered_df.empty
        ):
            default_requirement_label = _order_pick_label(filtered_df.iloc[-1])
        elif is_existing_meta_edit_mode and not filtered_df.empty:
            default_requirement_label = _order_pick_label(filtered_df.iloc[-1])

        with right_col:
            if combo_child_line_missing:
                st.warning("조합은 공정품을 체크한 뒤 `공정품 구성 저장`으로 포함 공정품을 먼저 확정해 주세요.")
                return
            if requirement_scope == "조립품" and assembly_requires_meta:
                st.info("먼저 조립공정 요구를 저장해 메타를 생성합니다. 저장 후 공정품 트리가 열립니다.")
                selected_mode_label = "신규 등록"
            elif not selected_item_id:
                st.info("왼쪽에서 공정품을 체크한 뒤 `입력`을 눌러 요구를 작성합니다.")
                selected_mode_label = "신규 등록"
            elif requirement_scope == "조립품":
                selected_mode_label = _order_pick_label(filtered_df.iloc[-1]) if not filtered_df.empty else "신규 등록"
            elif is_existing_meta_edit_mode and not requirement_choices:
                st.warning("선택한 메타에 연결된 해당 공정품 요구가 없습니다. 기존 메타는 수정만 가능합니다.")
                selected_mode_label = ""
            else:
                selected_mode_label = st.selectbox(
                    "고객요구",
                    options=requirement_choices,
                    index=requirement_choices.index(default_requirement_label) if default_requirement_label in requirement_choices else 0,
                    key=requirement_pick_key,
                    disabled=bool(is_existing_meta_edit_mode and len(requirement_choices) <= 1),
                )

        selected_row = None
        if selected_mode_label and selected_mode_label != "신규 등록" and not filtered_df.empty:
            selected_row = filtered_df[
                filtered_df.apply(_order_pick_label, axis=1) == selected_mode_label
            ].iloc[0]
        if (
            selected_row is not None
            and active_meta_key
            and requirement_scope != "공정품"
            and "meta_requirement_id" in selected_row.index
            and pd.notna(selected_row["meta_requirement_id"])
        ):
            st.session_state[active_meta_key] = int(selected_row["meta_requirement_id"])
            active_meta_id = int(selected_row["meta_requirement_id"])
        active_meta_row = get_meta_requirement_row(active_meta_id) if active_meta_id else None
        linked_existing_order_id = None
        if (
            selected_meta_line_row is not None
            and "linked_experiment_order_id" in selected_meta_line_row
            and selected_meta_line_row.get("linked_experiment_order_id")
        ):
            linked_existing_order_id = int(selected_meta_line_row["linked_experiment_order_id"])
        linked_existing_required_qty = (
            _safe_int_value(selected_meta_line_row.get("linked_required_sample_qty"), 1)
            if selected_meta_line_row is not None and linked_existing_order_id
            else 1
        )
        linked_existing_order_row = None
        if linked_existing_order_id and not df.empty:
            linked_existing_match = df[
                pd.to_numeric(df["experiment_order_id"], errors="coerce") == int(linked_existing_order_id)
            ]
            if not linked_existing_match.empty:
                linked_existing_order_row = linked_existing_match.iloc[0]

        selected_detail = parse_json_text(selected_row["requirement_detail_json"]) if selected_row is not None else {}
        if selected_row is None and selected_item_id and not df.empty:
            previous_requirement_rows = df[
                (pd.to_numeric(df["item_id"], errors="coerce") == int(selected_item_id))
                & (df["status"].astype(str) == "완료")
            ].sort_values("experiment_order_id", ascending=False)
            if not previous_requirement_rows.empty:
                previous_requirement_row = previous_requirement_rows.iloc[0]
                previous_requirement_detail = parse_json_text(previous_requirement_row["requirement_detail_json"])
                selected_detail = apply_previous_quality_defaults(
                    selected_detail,
                    previous_requirement_detail,
                    source_order_id=int(previous_requirement_row["experiment_order_id"]),
                    source_order_code=str(previous_requirement_row["order_code"]),
                )
                if any(selected_detail.get(f"spec_location_{idx}") or selected_detail.get(f"spec_value_{idx}") for idx in range(1, 5)):
                    st.info(f"이전 완료 요구의 품질기준을 기본값으로 불러왔습니다. 출처: {previous_requirement_row['order_code']}")
        root_meta_df = (
            df[(df["project_code"] == project_code) & (df["item_id"] == int(root_item_id))].copy()
            if project_code and root_item_id
            else df.iloc[0:0]
        )
        if active_meta_id and not root_meta_df.empty and "meta_requirement_id" in root_meta_df.columns:
            root_meta_df = root_meta_df[root_meta_df["meta_requirement_id"] == int(active_meta_id)].copy()
        root_meta_row = root_meta_df.iloc[-1] if not root_meta_df.empty else None
        process_type = infer_process_type_from_item(selected_item_row)
        base_drawing_revision = selected_row["base_drawing_revision"] if selected_row is not None and pd.notna(selected_row["base_drawing_revision"]) else ""
        drawing_receipt_status = selected_row["drawing_receipt_status"] if selected_row is not None and selected_row["drawing_receipt_status"] in DRAWING_RECEIPT_STATUS_OPTIONS else DRAWING_RECEIPT_STATUS_OPTIONS[0]
        mold_pre_update = bool(selected_row["mold_pre_update"]) if selected_row is not None and pd.notna(selected_row["mold_pre_update"]) else False
        success_criteria = selected_row["success_criteria"] if selected_row is not None and pd.notna(selected_row["success_criteria"]) else ""
        milestone_due_date = _safe_date_value(selected_row["milestone_due_date"]) if selected_row is not None else None
        mold_dispatch_required = bool(selected_row["mold_dispatch_required"]) if selected_row is not None and pd.notna(selected_row["mold_dispatch_required"]) else False
        requested_by = selected_row["requested_by"] if selected_row is not None else current_user()["user_name"]
        request_notes = selected_row["request_notes"] if selected_row is not None else ""
        target_due_date = _safe_date_value(selected_row["target_due_date"]) if selected_row is not None else (
            _safe_date_value(linked_existing_order_row["target_due_date"])
            if linked_existing_order_row is not None and pd.notna(linked_existing_order_row["target_due_date"])
            else (
                _safe_date_value(root_meta_row["target_due_date"])
                if root_meta_row is not None and pd.notna(root_meta_row["target_due_date"]) and selected_item_id != root_item_id
                else None
            )
        )
        required_sample_qty = _safe_int_value(selected_row["required_sample_qty"], 1) if selected_row is not None else (
            linked_existing_required_qty
            if linked_existing_order_row is not None
            else (
                _safe_int_value(root_meta_row["required_sample_qty"], 1)
                if root_meta_row is not None and pd.notna(root_meta_row["required_sample_qty"]) and selected_item_id != root_item_id
                else 1
            )
        )
        milestone_name = selected_row["milestone_name"] if selected_row is not None and selected_row["milestone_name"] in MILESTONE_OPTIONS else (
            linked_existing_order_row["milestone_name"]
            if linked_existing_order_row is not None and linked_existing_order_row["milestone_name"] in MILESTONE_OPTIONS
            else (
                root_meta_row["milestone_name"]
                if root_meta_row is not None and root_meta_row["milestone_name"] in MILESTONE_OPTIONS and selected_item_id != root_item_id
                else ""
            )
        )
        experiment_goal = (
            selected_row["experiment_goal"]
            if selected_row is not None
            else (linked_existing_order_row["experiment_goal"] if linked_existing_order_row is not None else "")
        )

        detail_payload = {
            "target_position": selected_detail.get("target_position", ""),
            "sample_reference": selected_detail.get("sample_reference", ""),
            "_quality_default_source_type": selected_detail.get("_quality_default_source_type"),
            "_quality_default_source_id": selected_detail.get("_quality_default_source_id"),
            "_quality_default_source_code": selected_detail.get("_quality_default_source_code"),
            "_meta_scope": requirement_scope,
            "_meta_product_id": int(selected_product_id) if selected_product_id else None,
            "_meta_tree_mode": tree_mode if tree_generated else "기본",
            "_meta_force_new": bool(requirement_scope == "조립품" and not active_meta_id and selected_row is None),
            "_meta_root_item_id": int(root_item_id) if root_item_id else (int(selected_item_id) if selected_item_id else None),
            "_meta_title": product_label or "",
            "_meta_requirement_id": int(active_meta_id) if active_meta_id else None,
            "_meta_line_id": int(active_meta_line_map[selected_item_id]) if selected_item_id in active_meta_line_map else None,
            "_meta_selected_item_ids": [int(iid) for _, iid in checked_tree_options] if requirement_scope == "조립품" else [],
        }
        if process_type == "조립":
            mode_options = ["설계트리대로", "조합변경"]
            execution_mode = "조합변경" if tree_mode == "조합" else "설계트리대로"
        else:
            mode_options = ["실험", "재고사용"]
            if requirement_scope == "조립품" and root_item_id and selected_item_id and int(selected_item_id) != int(root_item_id):
                mode_options = ["실험", "재고사용", "기존실험요구"]
            execution_mode = selected_detail.get("execution_mode", "실험")
            if selected_row is None and linked_existing_order_row is not None:
                execution_mode = "기존실험요구"
            if execution_mode not in mode_options:
                execution_mode = "실험"
        selected_stock_sample_id = selected_detail.get("stock_sample_id")
        existing_requirement_order_id = linked_existing_order_id if linked_existing_order_row is not None else None
        existing_requirement_locked = False
        existing_requirement_options: list[tuple[str, int]] = []
        if (
            requirement_scope == "조립품"
            and process_type != "조립"
            and selected_item_id
            and project_code
            and not df.empty
        ):
            candidate_orders_df = df[
                (df["project_code"] == project_code)
                & (pd.to_numeric(df["item_id"], errors="coerce") == int(selected_item_id))
            ].copy()
            for _, order_candidate in candidate_orders_df.sort_values("experiment_order_id", ascending=False).iterrows():
                candidate_order_id = int(order_candidate["experiment_order_id"])
                if selected_row is not None and candidate_order_id == int(selected_row["experiment_order_id"]):
                    continue
                candidate_detail = parse_json_text(order_candidate["requirement_detail_json"])
                if str(candidate_detail.get("execution_mode") or "") == "재고사용":
                    continue
                if str(order_candidate.get("status") or "") == "취소":
                    continue
                candidate_has_instruction = _has_instruction_for_order(instructions_df, candidate_order_id)
                if candidate_has_instruction and candidate_order_id != linked_existing_order_id:
                    continue
                meta_text = "독립"
                if pd.notna(order_candidate.get("meta_requirement_id")):
                    candidate_meta_row = get_meta_requirement_row(int(order_candidate["meta_requirement_id"]))
                    if candidate_meta_row is not None:
                        candidate_tree_mode = str(candidate_meta_row["tree_mode"] or "기본")
                        meta_text = "기본조립" if candidate_tree_mode == "기본" else "조합조립"
                        meta_text = f"{meta_text} {candidate_meta_row['meta_code']}"
                label = " | ".join(
                    [
                        part
                        for part in [
                            meta_text,
                            str(order_candidate.get("order_code") or "").strip(),
                            str(order_candidate.get("target_due_date") or "").strip(),
                            f"수량 {int(order_candidate.get('required_sample_qty') or 0)}",
                        ]
                        if part
                    ]
                )
                existing_requirement_options.append((label, candidate_order_id))
            if linked_existing_order_id and _has_instruction_for_order(instructions_df, linked_existing_order_id):
                existing_requirement_locked = True
        item_samples_df = samples_df[samples_df["item_id"] == selected_item_id].copy() if selected_item_id and not samples_df.empty else samples_df.iloc[0:0]
        stock_sample_options: list[tuple[str, int]] = []
        if not item_samples_df.empty:
            stock_sample_options = [
                (
                    f"{row['sample_code']} | {row['sample_name'] or row['item_name']}",
                    int(row["sample_id"]),
                )
                for _, row in item_samples_df.iterrows()
            ]
        child_items_df = bom_df[bom_df["parent_item_id"] == selected_item_id].copy() if selected_item_id and not bom_df.empty else bom_df.iloc[0:0]
        spec_key_suffix = str(int(selected_row["experiment_order_id"])) if selected_row is not None else (str(selected_item_id) if selected_item_id else "new")
        req_key_prefix = f"{selection_scope}_{spec_key_suffix}"

        color_required = False
        color_sample_exists = "있음"
        color_nuance = ""
        color_nuance_type = str(selected_detail.get("color_nuance_type", selected_detail.get("color_nuance", "")) or "")
        product_drawing_change_required = False
        raw_material_experiment_required = False
        raw_material_1_label = str(selected_detail.get("raw_material_label_1", "") or "")
        raw_material_2_label = str(selected_detail.get("raw_material_label_2", "") or "")
        mold_update_detail = ""
        mold_update_type = str(selected_detail.get("mold_update_type", "") or "")
        drawing_change_source = str(selected_detail.get("drawing_change_source", "구두/이미지") or "구두/이미지")
        masking_position = ""
        film_revision_required = False
        print_position = ""
        print_tolerance_deg = 0.0
        assembly_function = ""
        backing_spec = ""
        sub_material_other = ""
        other_request = selected_detail.get("other_request", "")
        base_item_revision_no = _clean_label_value(selected_item_row.get("base_revision_no", "") if selected_item_row is not None else "")
        base_item_film_revision_no = _clean_label_value(selected_item_row.get("base_film_revision_no", "") if selected_item_row is not None else "")
        base_film_revision_no = _get_current_film_revision_for_item(
            str(selected_item_row.get("project_code", "") if selected_item_row is not None else ""),
            str(selected_item_row.get("item_name", "") if selected_item_row is not None else ""),
        )
        current_drawing_info = get_current_product_drawing_for_item(int(selected_item_id)) if selected_item_id and process_type == "사출" else None
        current_drawing_revision_no = _clean_label_value(current_drawing_info.get("revision_no", "") if current_drawing_info else "")
        revision_no = _clean_label_value(
            selected_detail.get("revision_no", "")
            or (
                (base_item_film_revision_no or base_film_revision_no)
                if process_type == "인쇄"
                else (base_item_revision_no or current_drawing_revision_no)
            )
            or ""
        )
        material_variant_no = _clean_label_value(selected_detail.get("material_variant_no", "") or "")
        material_label = _clean_label_value(
            selected_detail.get("material_label", "")
            or (selected_item_row.get("base_material_label", "") if selected_item_row is not None else "")
            or ""
        )
        color_label = _clean_label_value(
            selected_detail.get("color_label", "")
            or (selected_item_row.get("base_color_label", "") if selected_item_row is not None else "")
            or ""
        )
        root_item_row = get_item_row(root_item_id) if root_item_id else None
        upper_status_text = "미입력"
        if root_meta_row is not None:
            upper_status_text = "완료"
        elif active_meta_row is not None and "status" in active_meta_row.keys() and active_meta_row["status"]:
            upper_status_text = str(active_meta_row["status"])
        upper_root_label = (
            product_label
            or (str(root_item_row.get("item_code") or "") if root_item_row is not None else "")
            or "최종 조립품"
        )

        item_product_code = selected_item_row.get("product_code", "") if selected_item_row is not None else ""
        selected_item_code = selected_item_row.get("item_code", "") if selected_item_row is not None else ""
        selected_item_name = selected_item_row.get("item_name", "") if selected_item_row is not None else ""
        development_type_text = project_row.get("development_type", "-") if project_row is not None else "-"
        with right_col:
            if requirement_scope == "조립품":
                meta_code_text = active_meta_row["meta_code"] if active_meta_row is not None and active_meta_row["meta_code"] else "미생성"
                st.caption(
                    f"프로젝트: {project_label or '-'} / 상품: {product_label or '-'} / 메타코드: {meta_code_text} / 구성방식: {tree_mode}"
                )
                if process_type == "조립":
                    if tree_mode == "조합":
                        st.text_input(
                            "식별정보",
                            value=f"{meta_code_text} | {product_label or '-'} | 조합",
                            disabled=True,
                            key=f"assembly_meta_identity_{selection_scope}_{selected_item_id or 'root'}",
                        )
                    else:
                        st.text_input(
                            "식별정보",
                            value=f"{meta_code_text} | {product_label or '-'} | 기본",
                            disabled=True,
                            key=f"assembly_meta_identity_{selection_scope}_{selected_item_id or 'root'}",
                        )
                if project_row is not None:
                    st.caption(f"개발형태: {development_type_text or '-'}")
            elif project_row is not None:
                st.caption(f"상품: {product_label or '-'} / 개발형태: {development_type_text or '-'}")
            if selected_item_id:
                render_product_drawing_reference(selected_item_id)

            if process_type != "조립":
                with st.container(border=True):
                    mode_c1, mode_c2 = st.columns([1.05, 1.95])
                    with mode_c1:
                        execution_mode = st.radio(
                            "진행 방식",
                            options=mode_options,
                            horizontal=True,
                            index=mode_options.index(execution_mode),
                            key=f"requirement_execution_mode_{selection_scope}_{spec_key_suffix}",
                        )
                    with mode_c2:
                        if execution_mode == "재고사용":
                            selected_stock_label = st.selectbox(
                                "실험샘플 선택",
                                options=[""] + [label for label, _ in stock_sample_options],
                                index=(
                                    1 + [sid for _, sid in stock_sample_options].index(int(selected_stock_sample_id))
                                    if selected_stock_sample_id and any(sid == int(selected_stock_sample_id) for _, sid in stock_sample_options)
                                    else 0
                                ) if stock_sample_options else 0,
                                help="해당 공정품의 기존 실험 샘플 중 재고 사용 대상을 선택합니다.",
                                key=f"requirement_stock_sample_{selection_scope}_{spec_key_suffix}",
                            )
                            selected_stock_sample_id = dict(stock_sample_options).get(selected_stock_label) if selected_stock_label else None
                            existing_requirement_order_id = None
                        else:
                            selected_stock_sample_id = None
                            if execution_mode == "기존실험요구":
                                existing_label_map = {label: oid for label, oid in existing_requirement_options}
                                selected_existing_label = st.selectbox(
                                    "기존 실험요구 선택",
                                    options=[""] + list(existing_label_map.keys()),
                                    index=(
                                        1 + [oid for _, oid in existing_requirement_options].index(int(existing_requirement_order_id))
                                        if existing_requirement_order_id and any(oid == int(existing_requirement_order_id) for _, oid in existing_requirement_options)
                                        else 0
                                    ) if existing_requirement_options else 0,
                                    disabled=existing_requirement_locked,
                                    key=f"requirement_existing_order_{selection_scope}_{spec_key_suffix}",
                                )
                                existing_requirement_order_id = (
                                    existing_label_map.get(selected_existing_label) if selected_existing_label else None
                                )
                                existing_requirement_match = (
                                    df[pd.to_numeric(df["experiment_order_id"], errors="coerce") == int(existing_requirement_order_id)]
                                    if existing_requirement_order_id and not df.empty
                                    else df.iloc[0:0]
                                )
                                if not existing_requirement_match.empty:
                                    linked_existing_order_row = existing_requirement_match.iloc[0]
                                else:
                                    linked_existing_order_row = None
                                if linked_existing_order_row is not None:
                                    st.caption(
                                        f"기존 요구코드: {linked_existing_order_row['order_code']} / 기존 필요샘플수: {linked_existing_order_row['required_sample_qty']}"
                                    )
                                elif not existing_requirement_options:
                                    st.info("선택 가능한 기존 실험요구가 없습니다. 먼저 해당 공정품 요구를 저장해 주세요.")
                                if existing_requirement_locked:
                                    st.warning("이미 지시가 생성된 기존 실험요구입니다. 이 연결은 수정할 수 없습니다.")
                            else:
                                existing_requirement_order_id = None
                                st.caption("신규 실험이 필요한 공정품 요구를 아래 카드에서 보강합니다.")
            elif tree_mode == "기본":
                st.caption("기본 조합 기준으로 조립요구를 작성합니다.")
            else:
                st.caption("선택한 공정품 조합 기준으로 조립요구를 작성합니다.")

            detail_payload["execution_mode"] = execution_mode
            detail_payload["stock_sample_id"] = int(selected_stock_sample_id) if selected_stock_sample_id else None
            detail_payload["existing_source_order_id"] = int(existing_requirement_order_id) if existing_requirement_order_id else None
            if selected_stock_sample_id and not item_samples_df.empty:
                stock_sample_row = item_samples_df[item_samples_df["sample_id"] == int(selected_stock_sample_id)]
                if not stock_sample_row.empty:
                    detail_payload["stock_sample_code"] = stock_sample_row.iloc[0]["sample_code"]
                    detail_payload["stock_sample_name"] = stock_sample_row.iloc[0]["sample_name"]
            else:
                detail_payload["stock_sample_code"] = ""
                detail_payload["stock_sample_name"] = ""
            if existing_requirement_order_id and linked_existing_order_row is not None:
                detail_payload["existing_source_order_code"] = str(linked_existing_order_row["order_code"] or "")
            else:
                detail_payload["existing_source_order_code"] = ""

            render_section_title("공통 요구")
            common_c1, common_c2, common_c3, common_c4 = st.columns([0.8, 1, 1, 1])
            with common_c1:
                st.text_input("공정", value=process_type, disabled=True, key=f"requirement_process_{selection_scope}_{spec_key_suffix}")
            with common_c2:
                target_due_date = st.date_input(
                    "납기일",
                    value=target_due_date,
                    disabled=execution_mode == "기존실험요구",
                    key=f"requirement_due_date_{selection_scope}_{spec_key_suffix}",
                )
            with common_c3:
                required_sample_qty = st.number_input(
                    "추가 필요 샘플 수" if execution_mode == "기존실험요구" else "필요 샘플 수",
                    min_value=1,
                    step=1,
                    value=required_sample_qty,
                    key=f"requirement_sample_qty_{selection_scope}_{spec_key_suffix}",
                )
            with common_c4:
                milestone_name = st.selectbox(
                    "개발 마일스톤",
                    options=MILESTONE_OPTIONS,
                    index=MILESTONE_OPTIONS.index(milestone_name) if milestone_name in MILESTONE_OPTIONS else 0,
                    disabled=execution_mode == "기존실험요구",
                    key=f"requirement_milestone_{selection_scope}_{spec_key_suffix}",
                )

            if execution_mode == "기존실험요구":
                with st.container(border=True):
                    st.caption("기존 실험요구 연결")
                    if linked_existing_order_row is not None:
                        info_c1, info_c2, info_c3 = st.columns(3)
                        with info_c1:
                            st.caption("기존 요구코드")
                            st.write(str(linked_existing_order_row["order_code"] or "-"))
                        with info_c2:
                            st.caption("기존 필요샘플수")
                            st.write(str(linked_existing_order_row["required_sample_qty"] or "-"))
                        with info_c3:
                            st.caption("지시 상태")
                            st.write("지시생성" if _has_instruction_for_order(instructions_df, int(existing_requirement_order_id)) else "지시전")
                    else:
                        st.info("연결할 기존 실험요구를 선택해 주세요.")
                    st.caption("기존 요구의 조건을 그대로 사용하고, 현재 입력한 수량만 추가 요구량으로 반영합니다.")
                mold_dispatch_required = False
                product_drawing_change_required = False
                raw_material_experiment_required = False
            elif execution_mode == "재고사용" and process_type in ("사출", "후가공", "인쇄", "사상"):
                with st.container(border=True):
                    st.caption("재고사용 요구")
                    if selected_stock_sample_id:
                        selected_sample = item_samples_df[item_samples_df["sample_id"] == int(selected_stock_sample_id)]
                        if not selected_sample.empty:
                            sample_row = selected_sample.iloc[0]
                            st.text_input("선택 샘플", value=sample_row["sample_code"], disabled=True, key=f"requirement_stock_code_{req_key_prefix}")
                            st.text_input("샘플명", value=sample_row["sample_name"] or sample_row["item_name"], disabled=True, key=f"requirement_stock_name_{req_key_prefix}")
                    else:
                        st.info("재고사용을 선택한 경우 사용할 실험샘플을 선택해 주세요.")
                    other_request = st.text_area("재고 사용 메모", height=88, value=other_request, key=f"requirement_stock_note_{req_key_prefix}")
                    detail_payload["other_request"] = other_request
                mold_dispatch_required = False
                product_drawing_change_required = False
                raw_material_experiment_required = False
            elif process_type == "사출":
                render_section_title("사출 요구사항")
                color_nuance_type = selected_detail.get("color_nuance_type", selected_detail.get("color_nuance", ""))
                mold_update_type = selected_detail.get("mold_update_type", "")
                raw_material_1_label = selected_detail.get("raw_material_label_1", "")
                raw_material_2_label = selected_detail.get("raw_material_label_2", "")
                drawing_change_source = selected_detail.get("drawing_change_source", "구두/이미지")
                mold_update_options = [option for option in MOLD_UPDATE_TYPE_OPTIONS if option]

                sec_c1, sec_c2, sec_c3 = st.columns(3)
                with sec_c1:
                    with st.container(border=True):
                        st.caption("색상")
                        color_required = st.checkbox("색상 체크", value=bool(selected_detail.get("color_required")), key=f"inj_color_required_{req_key_prefix}")
                        color_sample_exists = st.radio(
                            "샘플 유무",
                            ["있음", "없음"],
                            horizontal=True,
                            index=0 if selected_detail.get("color_sample_exists", "있음") == "있음" else 1,
                            disabled=not color_required,
                            key=f"inj_color_sample_{req_key_prefix}",
                        )
                        color_nuance_type = st.selectbox(
                            "뉴앙스",
                            options=COLOR_NUANCE_OPTIONS,
                            index=_select_index(COLOR_NUANCE_OPTIONS, color_nuance_type),
                            disabled=not color_required,
                            key=f"inj_color_nuance_type_{req_key_prefix}",
                        )
                        color_nuance = st.text_input(
                            "뉴앙스 기타",
                            value=selected_detail.get("color_nuance_extra", ""),
                            disabled=not color_required or color_nuance_type != "기타",
                            key=f"inj_color_nuance_extra_{req_key_prefix}",
                        )
                with sec_c2:
                    with st.container(border=True):
                        st.caption("금형")
                        mold_dispatch_required = st.checkbox(
                            "금형수정 체크",
                            value=bool(selected_detail.get("mold_dispatch_required") or mold_dispatch_required),
                            key=f"inj_mold_dispatch_{req_key_prefix}",
                        )
                        mold_update_type = st.selectbox(
                            "수정내용",
                            options=mold_update_options,
                            index=mold_update_options.index(mold_update_type) if mold_update_type in mold_update_options else 0,
                            disabled=not mold_dispatch_required,
                            key=f"inj_mold_update_type_{req_key_prefix}",
                        )
                        drawing_change_source = st.selectbox(
                            "수정전달방식",
                            options=["도면", "구두/이미지"],
                            index=0 if drawing_change_source == "도면" else 1,
                            disabled=not mold_dispatch_required,
                            key=f"inj_drawing_source_{req_key_prefix}",
                        )
                        mold_update_detail = st.text_input("수정기타", value=selected_detail.get("mold_update_detail_extra", ""), disabled=not mold_dispatch_required, key=f"inj_mold_update_detail_{req_key_prefix}")
                with sec_c3:
                    with st.container(border=True):
                        st.caption("원료")
                        raw_material_experiment_required = st.checkbox(
                            "원료 체크",
                            value=bool(selected_detail.get("raw_material_experiment_required")),
                            key=f"inj_raw_exp_{req_key_prefix}",
                        )
                        raw_material_1_label = st.text_input(
                            "원료명 1",
                            value=raw_material_1_label,
                            disabled=not raw_material_experiment_required,
                            key=f"inj_raw_1_{req_key_prefix}",
                        )
                        raw_material_2_label = st.text_input(
                            "원료명 2",
                            value=raw_material_2_label,
                            disabled=not raw_material_experiment_required,
                            key=f"inj_raw_2_{req_key_prefix}",
                        )
                render_section_title("특정위치 규격 / 외관 위치")
                legacy_appearance_items = selected_detail.get("appearance_items", [])
                legacy_appearance_position = selected_detail.get("appearance_position", "")
                appearance_entries = []
                spec_entries = []
                for idx in range(1, 5):
                    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                    with c1:
                        spec_location = st.text_input(
                            f"위치 {idx}",
                            value=selected_detail.get(f"spec_location_{idx}", ""),
                            key=f"spec_location_{spec_key_suffix}_{idx}",
                        )
                    with c2:
                        spec_value = st.text_input(
                            f"규격 {idx}",
                            value=selected_detail.get(f"spec_value_{idx}", ""),
                            key=f"spec_value_{spec_key_suffix}_{idx}",
                        )
                    default_appearance_item = selected_detail.get(f"appearance_item_{idx}", "")
                    if not default_appearance_item and idx == 1 and legacy_appearance_items:
                        default_appearance_item = legacy_appearance_items[0]
                    with c3:
                        appearance_item = st.selectbox(
                            f"외관 {idx}",
                            options=["", "수축", "웰드라인", "플로우마크", "기타"],
                            index=["", "수축", "웰드라인", "플로우마크", "기타"].index(default_appearance_item)
                            if default_appearance_item in ["", "수축", "웰드라인", "플로우마크", "기타"] else 0,
                            key=f"appearance_item_{spec_key_suffix}_{idx}",
                        )
                    with c4:
                        appearance_position = st.text_input(
                            f"외관 위치 {idx}",
                            value=selected_detail.get(f"appearance_position_{idx}", legacy_appearance_position if idx == 1 else ""),
                            key=f"appearance_position_{spec_key_suffix}_{idx}",
                        )
                    spec_entries.append((spec_location, spec_value))
                    appearance_entries.append((appearance_item, appearance_position))
                other_request = st.text_area("기타 요구", height=88, value=other_request, key=f"inj_other_request_{req_key_prefix}")
                for idx, (spec_location, spec_value) in enumerate(spec_entries, start=1):
                    detail_payload[f"spec_location_{idx}"] = spec_location
                    detail_payload[f"spec_value_{idx}"] = spec_value
                appearance_items = [item for item, _position in appearance_entries if item]
                first_appearance_position = next((position for item, position in appearance_entries if item or position), "")
                for idx, (appearance_item, appearance_position) in enumerate(appearance_entries, start=1):
                    detail_payload[f"appearance_item_{idx}"] = appearance_item
                    detail_payload[f"appearance_position_{idx}"] = appearance_position
                detail_payload.update(
                    {
                        "color_required": color_required,
                        "color_sample_exists": color_sample_exists,
                        "color_nuance_type": color_nuance_type,
                        "color_nuance_extra": color_nuance.strip(),
                        "color_nuance": color_nuance.strip() if color_nuance_type == "기타" else color_nuance_type,
                        "product_drawing_change_required": True if mold_dispatch_required and drawing_change_source == "도면" else False,
                        "drawing_change_source": drawing_change_source,
                        "raw_material_experiment_required": raw_material_experiment_required,
                        "raw_material_1_id": None,
                        "raw_material_1_label": raw_material_1_label,
                        "raw_material_2_id": None,
                        "raw_material_2_label": raw_material_2_label,
                        "mold_dispatch_required": mold_dispatch_required,
                        "mold_update_type": mold_update_type,
                        "mold_update_detail_extra": mold_update_detail,
                        "mold_update_detail": " / ".join([part for part in [mold_update_type, mold_update_detail.strip()] if part]),
                        "appearance_items": appearance_items,
                        "appearance_position": first_appearance_position,
                        "other_request": other_request,
                    }
                )
            elif process_type in ("후가공", "인쇄", "사상"):
                predecessor_links_raw = selected_detail.get("predecessor_links", [])
                predecessor_links_map = {
                    int(link.get("item_id")): link for link in predecessor_links_raw
                    if isinstance(link, dict) and link.get("item_id")
                }
                if execution_mode == "실험":
                    render_section_title("전공정품")
                    predecessor_links: list[dict] = []
                    process_label = "후가공품" if process_type in ("후가공", "사상") else "인쇄품"
                    if child_items_df.empty:
                        st.info(f"이 {process_label}에는 연결된 전공정품이 없습니다.")
                    else:
                        for _, child_row in child_items_df.iterrows():
                            child_item_id = int(child_row["child_item_id"])
                            child_item = get_item_row(child_item_id)
                            child_code = str(child_item.get("item_code") or child_row.get("child_item_code") or "")
                            child_name = str(child_item.get("item_name") or child_row.get("child_item_name") or "")
                            child_saved = predecessor_links_map.get(child_item_id, {})
                            source_mode = child_saved.get("source_mode", "기존실험요구")
                            child_order_df = df[(df["project_code"] == project_code) & (df["item_id"] == child_item_id)].copy() if project_code else df.iloc[0:0]
                            child_sample_df = samples_df[(samples_df["project_code"] == project_code) & (samples_df["item_id"] == child_item_id)].copy() if project_code else samples_df.iloc[0:0]
                            order_options = [
                                (
                                    f"{get_meta_requirement_row(int(row['meta_requirement_id']))['meta_code']} | {row['order_code']} | {row['experiment_goal'] or row['item_name']}"
                                    if "meta_requirement_id" in row.index and pd.notna(row["meta_requirement_id"]) and get_meta_requirement_row(int(row["meta_requirement_id"])) is not None
                                    else f"{row['order_code']} | {row['experiment_goal'] or row['item_name']}",
                                    int(row["experiment_order_id"]),
                                )
                                for _, row in child_order_df.iterrows()
                            ]
                            sample_options = [
                                (f"{row['sample_code']} | {row['sample_name'] or row['item_name']}", int(row["sample_id"]))
                                for _, row in child_sample_df.iterrows()
                            ]
                            with st.container(border=True):
                                st.caption(f"{child_code} | {child_name}")
                                st.caption("여기서는 전공정 요구를 새로 만들지 않고, 기존 전공정 실험요구 또는 재고만 선택합니다.")
                                source_mode = st.radio(
                                    "사용 방식",
                                    options=["기존실험요구", "재고품"],
                                    horizontal=True,
                                    index=0 if source_mode == "기존실험요구" else 1,
                                    key=f"post_predecessor_mode_{spec_key_suffix}_{child_item_id}",
                                )
                                selected_order_id = child_saved.get("source_order_id")
                                selected_sample_id = child_saved.get("source_sample_id")
                                if source_mode == "기존실험요구":
                                    if not order_options:
                                        st.info("선택 가능한 기존 전공정 실험요구가 없습니다. 먼저 해당 공정품 요구를 저장해 주세요.")
                                    selected_order_label = st.selectbox(
                                        "기존 실험요구 선택",
                                        options=[""] + [label for label, _ in order_options],
                                        index=(
                                            1 + [oid for _, oid in order_options].index(int(selected_order_id))
                                            if selected_order_id and any(oid == int(selected_order_id) for _, oid in order_options)
                                            else 0
                                        ) if order_options else 0,
                                        key=f"post_predecessor_order_{spec_key_suffix}_{child_item_id}",
                                    )
                                    selected_order_id = dict(order_options).get(selected_order_label) if selected_order_label else None
                                    selected_sample_id = None
                                else:
                                    selected_sample_label = st.selectbox(
                                        "재고중 선택",
                                        options=[""] + [label for label, _ in sample_options],
                                        index=(
                                            1 + [sid for _, sid in sample_options].index(int(selected_sample_id))
                                            if selected_sample_id and any(sid == int(selected_sample_id) for _, sid in sample_options)
                                            else 0
                                        ) if sample_options else 0,
                                        key=f"post_predecessor_sample_{spec_key_suffix}_{child_item_id}",
                                    )
                                    selected_sample_id = dict(sample_options).get(selected_sample_label) if selected_sample_label else None
                                    selected_order_id = None
                                predecessor_links.append(
                                    {
                                        "item_id": child_item_id,
                                        "item_code": child_code,
                                        "item_name": child_name,
                                        "source_mode": source_mode,
                                        "source_order_id": int(selected_order_id) if selected_order_id else None,
                                        "source_sample_id": int(selected_sample_id) if selected_sample_id else None,
                                    }
                                )
                    detail_payload["predecessor_links"] = predecessor_links
                else:
                    detail_payload["predecessor_links"] = []

                if process_type in ("후가공", "사상"):
                    render_section_title(f"{process_type} 요구사항")
                    sec_c1, sec_c2, sec_c3 = st.columns([1, 1, 1])
                    with sec_c1:
                        color_required = st.checkbox("색상", value=bool(selected_detail.get("color_required")), key=f"post_color_required_{req_key_prefix}")
                        color_sample_exists = st.radio(
                            "색상샘플 유무",
                            ["있음", "없음"],
                            horizontal=True,
                            index=0 if selected_detail.get("color_sample_exists", "있음") == "있음" else 1,
                            disabled=not color_required,
                            key=f"post_color_sample_{req_key_prefix}",
                        )
                    with sec_c2:
                        color_nuance_type = selected_detail.get("color_nuance_type", selected_detail.get("color_nuance", ""))
                        color_nuance_type = st.selectbox("색상 뉴앙스", options=COLOR_NUANCE_OPTIONS, index=_select_index(COLOR_NUANCE_OPTIONS, color_nuance_type), disabled=not color_required, key=f"post_color_nuance_type_{req_key_prefix}")
                        color_nuance = st.text_input("색상 뉴앙스 기타", value=selected_detail.get("color_nuance_extra", ""), disabled=not color_required or color_nuance_type != "기타", key=f"post_color_nuance_extra_{req_key_prefix}")
                    with sec_c3:
                        masking_position = st.text_input("마스킹위치", value=selected_detail.get("masking_position", ""), key=f"post_masking_position_{req_key_prefix}")
                    other_request = st.text_area("고객요구 부연설명", height=88, value=other_request, key=f"post_other_request_{req_key_prefix}")
                    detail_payload.update(
                        {
                            "color_required": color_required,
                            "color_sample_exists": color_sample_exists,
                            "color_nuance_type": color_nuance_type,
                            "color_nuance_extra": color_nuance.strip(),
                            "color_nuance": color_nuance.strip() if color_nuance_type == "기타" else color_nuance_type,
                            "masking_position": masking_position,
                            "other_request": other_request,
                        }
                    )
                else:
                    render_section_title("인쇄 요구사항")
                    sec_c1, sec_c2, sec_c3, sec_c4 = st.columns([1, 1, 1, 1.2])
                    with sec_c1:
                        film_revision_required = st.checkbox("원화 수정 여부", value=bool(selected_detail.get("film_revision_required")), key=f"print_film_revision_required_{req_key_prefix}")
                        color_required = st.checkbox("색상", value=bool(selected_detail.get("color_required")), key=f"print_color_required_{req_key_prefix}")
                        color_sample_exists = st.radio(
                            "색상샘플 유무",
                            ["있음", "없음"],
                            horizontal=True,
                            index=0 if selected_detail.get("color_sample_exists", "있음") == "있음" else 1,
                            disabled=not color_required,
                            key=f"print_color_sample_{req_key_prefix}",
                        )
                    with sec_c2:
                        color_nuance_type = selected_detail.get("color_nuance_type", selected_detail.get("color_nuance", ""))
                        color_nuance_type = st.selectbox("색상 뉴앙스", options=COLOR_NUANCE_OPTIONS, index=_select_index(COLOR_NUANCE_OPTIONS, color_nuance_type), disabled=not color_required, key=f"print_color_nuance_type_{req_key_prefix}")
                        color_nuance = st.text_input("색상 뉴앙스 기타", value=selected_detail.get("color_nuance_extra", ""), disabled=not color_required or color_nuance_type != "기타", key=f"print_color_nuance_extra_{req_key_prefix}")
                    with sec_c3:
                        print_position = st.text_input("기준 위치", value=selected_detail.get("print_position", ""), key=f"print_position_{req_key_prefix}")
                        print_tolerance_deg = st.number_input("허용오차 (+- 몇도)", min_value=0.0, step=0.5, value=float(selected_detail.get("print_tolerance_deg", 0.0)), key=f"print_tolerance_{req_key_prefix}")
                    with sec_c4:
                        other_request = st.text_area("기타 요구", height=88, value=other_request, key=f"print_other_request_{req_key_prefix}")
                    detail_payload.update(
                        {
                            "film_revision_required": film_revision_required,
                            "color_required": color_required,
                            "color_sample_exists": color_sample_exists,
                            "color_nuance_type": color_nuance_type,
                            "color_nuance_extra": color_nuance.strip(),
                            "color_nuance": color_nuance.strip() if color_nuance_type == "기타" else color_nuance_type,
                            "print_position": print_position,
                            "print_tolerance_deg": print_tolerance_deg,
                            "other_request": other_request,
                        }
                    )
                mold_dispatch_required = False
                product_drawing_change_required = False
                raw_material_experiment_required = False
            elif process_type == "조립":
                render_section_title("조립 요구사항")
                sec_c1, sec_c2, sec_c3, sec_c4 = st.columns([1, 1, 1, 1.2])
                with sec_c1:
                    assembly_function_type = selected_detail.get("assembly_function_type", selected_detail.get("assembly_function", ""))
                    assembly_function_type = st.selectbox("기능", options=ASSEMBLY_FUNCTION_OPTIONS, index=_select_index(ASSEMBLY_FUNCTION_OPTIONS, assembly_function_type), key=f"assy_function_type_{req_key_prefix}")
                    assembly_function = st.text_input("기능 기타", value=selected_detail.get("assembly_function_extra", ""), disabled=assembly_function_type != "기타", key=f"assy_function_extra_{req_key_prefix}")
                with sec_c2:
                    backing_spec = st.text_input("바킹 규격", value=selected_detail.get("backing_spec", ""), key=f"assy_backing_spec_{req_key_prefix}")
                with sec_c3:
                    sub_material_issue_type = selected_detail.get("sub_material_issue_type", selected_detail.get("sub_material_other", ""))
                    sub_material_issue_type = st.selectbox("부재료 사양", options=SUB_MATERIAL_ISSUE_OPTIONS, index=_select_index(SUB_MATERIAL_ISSUE_OPTIONS, sub_material_issue_type), key=f"assy_sub_material_type_{req_key_prefix}")
                    sub_material_other = st.text_input("부재료 기타", value=selected_detail.get("sub_material_other_extra", ""), disabled=sub_material_issue_type != "기타", key=f"assy_sub_material_extra_{req_key_prefix}")
                with sec_c4:
                    other_request = st.text_area("기타 요구", height=88, value=other_request, key=f"assy_other_request_{req_key_prefix}")
                detail_payload.update(
                    {
                        "assembly_function_type": assembly_function_type,
                        "assembly_function_extra": assembly_function,
                        "assembly_function": assembly_function.strip() if assembly_function_type == "기타" else assembly_function_type,
                        "backing_spec": backing_spec,
                        "sub_material_issue_type": sub_material_issue_type,
                        "sub_material_other_extra": sub_material_other,
                        "sub_material_other": sub_material_other.strip() if sub_material_issue_type == "기타" else sub_material_issue_type,
                        "other_request": other_request,
                    }
                )
                mold_dispatch_required = False
                product_drawing_change_required = False
                raw_material_experiment_required = False
            else:
                mold_dispatch_required = False
                product_drawing_change_required = False
                raw_material_experiment_required = False
                st.info("프로젝트와 공정품을 선택하면 해당 공정의 고객요구 입력이 열립니다.")

            derived_revision_no = revision_no.strip()
            derived_material_variant_no = material_variant_no.strip()
            derived_material_label = material_label.strip()
            derived_color_label = color_label.strip()
            current_order_id = int(selected_row["experiment_order_id"]) if selected_row is not None and "experiment_order_id" in selected_row.index and pd.notna(selected_row["experiment_order_id"]) else None
            if process_type == "사출":
                if mold_dispatch_required:
                    revision_variant_no = str(selected_detail.get("revision_variant_no") or "").strip()
                    if not revision_variant_no:
                        revision_variant_no = _next_requirement_variant_no(
                            df,
                            selected_item_id,
                            "revision_variant_no",
                            current_order_id,
                        )
                else:
                    revision_variant_no = ""
                if raw_material_experiment_required:
                    existing_material_variant_no = str(selected_detail.get("material_variant_no") or "").strip()
                    derived_material_variant_no = existing_material_variant_no or _next_requirement_variant_no(
                        df,
                        selected_item_id,
                        "material_variant_no",
                        current_order_id,
                    )
                else:
                    derived_material_variant_no = ""
                if raw_material_experiment_required:
                    derived_material_label = " / ".join(
                        [value for value in [raw_material_1_label.strip(), raw_material_2_label.strip()] if value]
                    )
                else:
                    derived_material_label = ""
                if color_required:
                    derived_color_label = color_nuance.strip() if color_nuance_type == "기타" else color_nuance_type.strip()
                else:
                    derived_color_label = ""
            elif process_type == "인쇄":
                if film_revision_required:
                    revision_variant_no = str(selected_detail.get("revision_variant_no") or "").strip()
                    if not revision_variant_no:
                        revision_variant_no = _next_requirement_variant_no(
                            df,
                            selected_item_id,
                            "revision_variant_no",
                            current_order_id,
                        )
                else:
                    revision_variant_no = ""
                derived_material_variant_no = ""
                derived_color_label = ""
            else:
                revision_variant_no = ""

            base_display_code = str(selected_item_code or item_product_code or "")
            display_code = base_display_code
            display_label = _build_display_label(
                display_code,
                str(selected_item_name or ""),
                derived_revision_no,
                derived_material_label,
                derived_color_label,
                revision_variant_no,
                "도면" if process_type == "사출" else ("원화" if process_type == "인쇄" else ""),
            )
            detail_payload.update(
                {
                    "revision_no": derived_revision_no,
                    "revision_variant_no": revision_variant_no,
                    "material_variant_no": derived_material_variant_no,
                    "material_label": derived_material_label,
                    "color_label": derived_color_label,
                    "display_code": display_code,
                    "display_label": display_label,
                    "reference_type": "도면" if process_type == "사출" else ("원화" if process_type == "인쇄" else ""),
                }
            )

            selected_order_usage = (
                get_experiment_order_usage(int(selected_row["experiment_order_id"]))
                if selected_row is not None and "experiment_order_id" in selected_row.index and pd.notna(selected_row["experiment_order_id"])
                else {}
            )
            can_hard_delete = bool(
                selected_row is not None
                and not any(
                    selected_order_usage.get(flag, False)
                    for flag in ["has_meta", "has_meta_line", "has_sample", "has_mb_request", "has_mold_dispatch"]
                )
            )
            requirement_completed = False
            if requirement_scope == "조립품" and root_item_id and selected_item_id and int(selected_item_id) == int(root_item_id):
                if not assembly_all_child_ready:
                    st.caption("체크된 하위 공정품이 모두 `요구저장` 또는 `미사용` 상태여야 요구완료를 체크할 수 있습니다.")
                requirement_completed = st.checkbox(
                    "요구완료",
                    value=bool(selected_row is not None and str(selected_row.get("status") or "") == "완료" and assembly_all_child_ready),
                    disabled=not assembly_all_child_ready,
                    key=f"assembly_requirement_completed_{selection_scope}_{active_meta_id or 'new'}_{selected_item_id or 'root'}",
                )
            primary_label = "수정저장" if selected_row is not None else "저장"
            action_defs = [(primary_label, "save_requirement_button", True)]
            if selected_row is not None:
                action_defs.append(("취소", "cancel_requirement_button", True))
                action_defs.append(("삭제", "delete_requirement_button", can_hard_delete))
            action_results = render_page_actions(action_defs)
            save_clicked = action_results[0]
            cancel_clicked = action_results[1] if selected_row is not None else False
            delete_clicked = action_results[2] if selected_row is not None else False

        if delete_clicked and selected_row is not None:
            ok, message = delete_experiment_order(int(selected_row["experiment_order_id"]))
            if ok:
                flash_success(message)
                st.rerun()
            st.error(message)
        elif cancel_clicked and selected_row is not None:
            ok, message = update_experiment_order_status(int(selected_row["experiment_order_id"]), "취소")
            if ok:
                flash_success("요구를 취소 상태로 변경했습니다.")
                st.rerun()
            st.error(message)
        elif save_clicked:
            if execution_mode == "기존실험요구":
                current_meta_line_id = detail_payload.get("_meta_line_id")
                if requirement_scope != "조립품" or not active_meta_id or not current_meta_line_id:
                    st.error("기존실험요구 연결은 조립 요구의 공정품 라인에서만 사용할 수 있습니다.")
                    return
                if selected_row is not None:
                    st.error("이미 현재 메타에 저장된 요구가 있습니다. 기존실험요구로 바꾸려면 현재 요구를 정리한 뒤 다시 연결해 주세요.")
                    return
                if not existing_requirement_order_id or linked_existing_order_row is None:
                    st.error("연결할 기존 실험요구를 선택해 주세요.")
                    return
                if _has_instruction_for_order(instructions_df, int(existing_requirement_order_id)):
                    st.error("이미 지시가 생성된 요구는 조립 요구에서 다시 연결할 수 없습니다.")
                    return
                try:
                    save_meta_requirement_line_link(
                        meta_requirement_id=int(active_meta_id),
                        meta_line_id=int(current_meta_line_id),
                        linked_experiment_order_id=int(existing_requirement_order_id),
                        linked_required_sample_qty=int(required_sample_qty),
                    )
                except Exception as exc:
                    st.error(f"기존 실험요구 연결 중 오류가 발생했습니다: {exc}")
                    return
                flash_success("기존 실험요구를 연결했습니다.")
                st.rerun()
            if is_existing_meta_edit_mode and selected_row is None and not can_create_new_requirement_for_selected_item:
                st.error("기존 메타 선택 상태에서는 연결된 기존 요구만 수정할 수 있습니다.")
                return
            validation_error = validate_requirement_save(project_label, selected_item_id, process_type, detail_payload)
            if validation_error:
                st.error(validation_error)
                return
            if (
                requirement_scope != "공정품"
                and tree_mode == "기본"
                and not active_meta_id
                and root_item_id
                and selected_item_id != root_item_id
                and process_type != "조립"
            ):
                st.error("기본 방식에서는 최종 공정품 요구를 먼저 저장해 메타 요구를 생성해 주세요.")
                return
            if (
                requirement_scope == "조립품"
                and tree_mode == "조합"
                and active_meta_id
                and process_type != "조립"
                and selected_item_id not in active_meta_line_ids
            ):
                st.error("조합은 공정품을 체크한 뒤 `공정품 구성 저장`으로 포함 공정품을 먼저 확정해 주세요.")
                return
            item_code = selected_item_label.strip().split(" | ")[0] if selected_item_label else "ITEM"
            requirement_checks = derive_requirement_checks(process_type, detail_payload)
            order_payload: ExperimentOrderPayload = {
                "project_id": dict(projects).get(project_label),
                "item_id": selected_item_id,
                "item_code": item_code,
                "process_type": process_type,
                "milestone_name": milestone_name,
                "base_drawing_revision": base_drawing_revision,
                "drawing_receipt_status": drawing_receipt_status,
                "mold_pre_update": mold_pre_update,
                "mold_dispatch_required": mold_dispatch_required,
                "product_drawing_change_required": product_drawing_change_required,
                "target_due_date": str(target_due_date) if target_due_date else None,
                "milestone_due_date": str(milestone_due_date) if milestone_due_date else None,
                "required_sample_qty": required_sample_qty,
                "experiment_goal": experiment_goal,
                "success_criteria": success_criteria,
                "request_notes": request_notes,
                "requirement_checks": requirement_checks,
                "detail_payload": detail_payload,
                "requested_by": requested_by,
            }
            try:
                saved_order_id, order_code, saved_meta_id = save_experiment_order(
                    selected_row,
                    payload=order_payload,
                    current_user_name=current_user()["user_name"],
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            if requirement_scope == "조립품" and requirement_completed and saved_order_id:
                update_experiment_order_status(int(saved_order_id), "완료")
            if active_meta_key and saved_meta_id:
                st.session_state[active_meta_key] = int(saved_meta_id)
            if requirement_scope == "조립품" and selected_row is None:
                st.session_state[meta_mode_key] = "new"
            flash_success(f"고객요구를 저장했습니다. 코드: {order_code}")
            st.rerun()

    project_history_df = df[df["project_code"] == project_code] if project_code else df.iloc[0:0]
    if not project_history_df.empty:
        display_df = project_history_df.copy()
        display_df["요구세부항목"] = display_df["requirement_checks_json"].apply(lambda raw: ", ".join(json.loads(raw)) if raw else "")
        render_history_panel("이력 보기", display_df[["order_code", "project_code", "item_code", "item_name", "process_type", "milestone_name", "base_drawing_revision", "drawing_receipt_status", "mold_pre_update", "mold_dispatch_required", "milestone_due_date", "target_due_date", "required_sample_qty", "experiment_goal", "success_criteria", "요구세부항목", "requested_by", "status"]])


def render_sample_instructions_page(instruction_scope: str = "공정품") -> None:
    page_name = "사출 실험지시" if instruction_scope == "사출" else "공정품 실험지시"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = list_project_options()
    instructions_df = list_experiment_instructions()
    samples_df = list_experiment_samples()
    orders_df = list_experiment_orders()
    meta_line_links_df = list_meta_requirement_line_links()
    linked_requirement_extra_qty_by_order = _linked_requirement_extra_qty_map(meta_line_links_df)
    mb_requests_df = list_mb_requests()
    mold_dispatch_df = list_mold_dispatch_orders()
    project_code = ""
    if can_edit(page_name):
        scope_keys = _instruction_scoped_keys(instruction_scope)
        scope_key = scope_keys["scope_key"]
        project_key = scope_keys["project_label"]
        product_key = scope_keys["product_label"]
        tree_key = scope_keys["item_tree_label"]
        order_key = scope_keys["order_label"]
        existing_pick_key = scope_keys["existing_pick"]
        active_project_state_key = scope_keys["active_project_code"]
        active_product_state_key = scope_keys["active_product_id"]
        active_item_state_key = scope_keys["active_item_id"]
        active_order_state_key = scope_keys["active_order_id"]
        active_instruction_state_key = scope_keys["active_instruction_id"]
        direct_visit_key = scope_keys["direct_visit_token"]
        entry_mode_key = scope_keys["entry_mode"]
        view_only_key = scope_keys["view_only"]
        jump_request = st.session_state.pop("instruction_jump_request", None)
        if isinstance(jump_request, dict):
            requirement_row_id = jump_request.get("requirement_row_id")
            resolved_jump_context = (
                get_requirement_jump_context(requirement_row_id, jump_request.get("scope"))
                if requirement_row_id
                else {}
            )
            project_code_for_jump = str(resolved_jump_context.get("project_code") or jump_request.get("project_code") or "").strip()
            product_id_for_jump = resolved_jump_context.get("product_id") or jump_request.get("product_id")
            item_id_for_jump = resolved_jump_context.get("item_id") or jump_request.get("item_id")
            jump_order_id = resolved_jump_context.get("order_id") or jump_request.get("order_id")
            jump_instruction_id = resolved_jump_context.get("instruction_id") or jump_request.get("instruction_id")
            jump_item_id = int(item_id_for_jump) if item_id_for_jump is not None else None
            if project_code_for_jump:
                st.session_state[active_project_state_key] = project_code_for_jump
            if product_id_for_jump:
                st.session_state[active_product_state_key] = int(product_id_for_jump)
            if item_id_for_jump:
                st.session_state[active_item_state_key] = int(item_id_for_jump)
            if project_code_for_jump:
                project_label_for_jump = next(
                    (label for label, _ in projects if label.split(" | ")[0] == project_code_for_jump),
                    "",
                )
                if project_label_for_jump:
                    st.session_state[project_key] = project_label_for_jump
            if project_code_for_jump and product_id_for_jump:
                product_choices_for_jump = list_product_options_for_project(project_code_for_jump)
                product_label_for_jump = next(
                    (label for label, pid in product_choices_for_jump if int(pid) == int(product_id_for_jump)),
                    "",
                )
                if product_label_for_jump:
                    st.session_state[product_key] = product_label_for_jump
            if project_code_for_jump and product_id_for_jump and item_id_for_jump:
                jump_tree_choices = list_project_item_tree_options(project_code_for_jump, int(product_id_for_jump))
                if any(int(iid) == int(item_id_for_jump) for _, iid in jump_tree_choices):
                    st.session_state[tree_key] = int(item_id_for_jump)
            if jump_request.get("instruction_mode"):
                mode_value = str(jump_request["instruction_mode"])
                if instruction_scope == "사출":
                    st.session_state["inject_mode"] = mode_value
                else:
                    st.session_state["process_mode"] = mode_value
            st.session_state[view_only_key] = bool(jump_request.get("read_only"))
            jump_request_scope = str(jump_request.get("scope") or "").strip()
        else:
            project_code_for_jump = ""
            product_id_for_jump = None
            item_id_for_jump = None
            jump_order_id = None
            jump_instruction_id = None
            jump_item_id = None
            jump_request_scope = ""
            st.session_state[view_only_key] = False

        entry_source = str(st.session_state.get("menu_entry_source_dev") or "direct")
        entry_mode = str(st.session_state.get(entry_mode_key) or "direct")
        instruction_view_only = bool(st.session_state.get(view_only_key))
        return_context = st.session_state.get("assembly_return_context")
        _append_nav_trace(
            "injection_page_entry",
            instruction_scope=instruction_scope,
            current_menu=st.session_state.get("current_menu"),
            entry_source=entry_source,
            entry_mode=entry_mode,
            return_context=return_context,
            instruction_jump_request=jump_request if isinstance(jump_request, dict) else None,
            assembly_return_context=st.session_state.get("assembly_return_context"),
            assembly_restore_context=st.session_state.get("assembly_restore_context"),
        )
        _log_return_context_state()
        st.session_state[entry_mode_key] = entry_mode
        instruction_locked = entry_mode == "from_assembly" and isinstance(return_context, dict)
        return_clicked = False
        if isinstance(return_context, dict):
            return_clicked = st.button("조립 실험지시로 복귀", key=f"return_to_assembly_instruction_{instruction_scope}")
            if return_clicked:
                return_ctx = dict(st.session_state.get("assembly_return_context") or {})
                _append_nav_trace(
                    "return_button_clicked_before_clear",
                    instruction_scope=instruction_scope,
                    current_menu=st.session_state.get("current_menu"),
                    entry_source=st.session_state.get("menu_entry_source_dev"),
                    return_context=return_ctx,
                    instruction_jump_request=jump_request if isinstance(jump_request, dict) else None,
                    assembly_return_context=st.session_state.get("assembly_return_context"),
                    pending_nav_dev=st.session_state.get("pending_nav_dev"),
                )
                if return_ctx.get("project_label"):
                    st.session_state["assembly_instruction_project_label"] = return_ctx["project_label"]
                if return_ctx.get("product_label"):
                    st.session_state["assembly_instruction_product_label"] = return_ctx["product_label"]
                if return_ctx.get("tree_mode"):
                    st.session_state["assembly_instruction_tree_mode"] = return_ctx["tree_mode"]
                if return_ctx.get("meta_label"):
                    st.session_state["assembly_instruction_meta_label"] = return_ctx["meta_label"]
                if return_ctx.get("mode"):
                    st.session_state["assembly_instruction_mode"] = return_ctx["mode"]
                if return_ctx.get("mode") == "신규":
                    st.session_state["assembly_instruction_order_label"] = str(return_ctx.get("order_label") or "")
                    st.session_state["assembly_instruction_pick"] = ""
                elif return_ctx.get("mode") == "수정":
                    st.session_state["assembly_instruction_pick"] = str(return_ctx.get("instruction_pick") or "")
                    st.session_state["assembly_instruction_order_label"] = ""
                clear_injection_instruction_state()
                st.session_state["assembly_restore_context"] = {
                    "project_label": return_ctx.get("project_label"),
                    "product_label": return_ctx.get("product_label"),
                    "tree_mode": return_ctx.get("tree_mode"),
                    "meta_label": return_ctx.get("meta_label"),
                    "mode": return_ctx.get("mode"),
                    "order_id": return_ctx.get("order_id"),
                    "instruction_id": return_ctx.get("instruction_id"),
                    "item_id": return_ctx.get("item_id"),
                    "tree_node": return_ctx.get("selected_tree_node"),
                }
                st.session_state["pending_nav_dev"] = {
                    "group": "개발진행",
                    "menu": "조립 실험지시",
                }
                _log_return_context_state()
                _append_nav_trace(
                    "return_button_clicked_after_nav_set",
                    instruction_scope=instruction_scope,
                    pending_nav_dev=st.session_state.get("pending_nav_dev"),
                    assembly_restore_context=st.session_state.get("assembly_restore_context"),
                    assembly_return_context=st.session_state.get("assembly_return_context"),
                )
                st.rerun()
        if not return_clicked and entry_source != "pending_nav" and (entry_mode == "from_assembly" or return_context):
            _append_nav_trace(
                "stale_injection_context_cleanup",
                instruction_scope=instruction_scope,
                current_menu=st.session_state.get("current_menu"),
                entry_source=entry_source,
                entry_mode=entry_mode,
                return_context=return_context,
            )
            if instruction_scope == "사출":
                clear_injection_ui_state()
            else:
                clear_process_ui_state()
            clear_return_context()
            entry_mode = "direct"
            return_context = None
            st.session_state[entry_mode_key] = entry_mode
            instruction_locked = False
            st.session_state[view_only_key] = False
        current_menu_visit_token = st.session_state.get("menu_visit_token_dev")
        if entry_source == "direct" and not return_context:
            if st.session_state.get(direct_visit_key) != current_menu_visit_token:
                clear_instruction_top_filters(scope_key)
                if instruction_scope == "사출":
                    clear_injection_ui_state()
                else:
                    clear_process_ui_state()
                entry_mode = "direct"
                st.session_state[entry_mode_key] = entry_mode
                instruction_locked = False
                st.session_state[view_only_key] = False
                st.session_state[direct_visit_key] = current_menu_visit_token
        _log_return_context_state()
        if instruction_locked:
            st.caption("조립 실험지시에서 진입한 화면입니다. 상단 선택은 잠겨 있습니다.")
        else:
            st.caption("실험지시 화면입니다. 상단 선택을 새로 시작할 수 있습니다.")
        if instruction_view_only:
            st.caption("조립 화면에서 연 조회 전용 모드입니다. 수정/삭제는 해당 지시 화면에서 직접 진행해 주세요.")

        top_c1, top_c2, top_c3, top_c4, top_c5 = st.columns([1.0, 1.0, 1.1, 1.05, 1.5])
        active_project_code = str(st.session_state.get(active_project_state_key) or "")
        current_project_label = str(st.session_state.get(project_key, "") or "")
        available_project_labels = [""] + [label for label, _ in projects]
        active_project_label = next((label for label, _ in projects if label.split(" | ")[0] == active_project_code), "")
        if active_project_label and (not current_project_label or current_project_label not in available_project_labels):
            st.session_state[project_key] = active_project_label
        elif current_project_label and current_project_label not in available_project_labels:
            st.session_state.pop(project_key, None)
        with top_c1:
            if st.session_state.get(project_key) not in available_project_labels:
                st.session_state.pop(project_key, None)
            project_label = st.selectbox("프로젝트", options=available_project_labels, key=project_key, disabled=instruction_locked)
        project_code = project_label.split(" | ")[0] if project_label else ""
        print(
            "[INJECTION] project_selection",
            {
                "project_label_raw": project_label,
                "project_code_used": project_code,
                "project_label_repr": repr(project_label),
                "project_code_repr": repr(project_code),
            },
        )
        if project_code:
            st.session_state[active_project_state_key] = project_code
        else:
            st.session_state.pop(active_project_state_key, None)
        project_row = get_project_by_code(project_code) if project_code else None
        product_options = list_product_options_for_project(project_code) if project_code else []
        print(
            "[INJECTION] product_query_result",
            {
                "project_code_used": project_code,
                "products_len": len(product_options),
                "product_options": product_options,
            },
        )
        active_product_id = st.session_state.get(active_product_state_key)
        current_product_label = str(st.session_state.get(product_key, "") or "")
        available_product_labels = [""] + [label for label, _ in product_options]
        active_product_label = next(
            (label for label, pid in product_options if active_product_id and int(pid) == int(active_product_id)),
            "",
        )
        if active_product_label and (not current_product_label or current_product_label not in available_product_labels):
            st.session_state[product_key] = active_product_label
        elif current_product_label and current_product_label not in available_product_labels:
            st.session_state.pop(product_key, None)
        with top_c2:
            if st.session_state.get(product_key) not in available_product_labels:
                st.session_state.pop(product_key, None)
            product_label = st.selectbox("상품", options=available_product_labels, key=product_key, disabled=instruction_locked)
        selected_product_id = dict(product_options).get(product_label) if product_label else None
        print(
            "[INJECTION] before_product_guard",
            {
                "project_code": project_code,
                "product_label": product_label,
                "selected_product_id": selected_product_id,
                "product_options": product_options,
            },
        )
        if selected_product_id:
            st.session_state[active_product_state_key] = int(selected_product_id)
        else:
            st.session_state.pop(active_product_state_key, None)
        tree_items = list_project_item_tree_options(project_code, selected_product_id) if project_code and selected_product_id else []
        if tree_items:
            scoped_tree_items: list[tuple[str, int]] = []
            for label, iid in tree_items:
                item_row = get_item_row(iid)
                process_text = infer_process_type_from_item(item_row) if item_row is not None else ""
                if instruction_scope == "사출":
                    if process_text == "사출":
                        scoped_tree_items.append((label, iid))
                else:
                    if process_text not in ("사출", "조립"):
                        scoped_tree_items.append((label, iid))
            tree_items = scoped_tree_items
        tree_item_ids = [0] + [int(iid) for _, iid in tree_items]
        previous_active_item_id = st.session_state.get(active_item_state_key)
        current_tree_value = st.session_state.get(tree_key, None)
        jump_restore_item_id = None
        if jump_item_id and tree_items and int(jump_item_id) in tree_item_ids:
            jump_restore_item_id = int(jump_item_id)
            st.session_state[tree_key] = jump_restore_item_id
            st.session_state[active_item_state_key] = jump_restore_item_id
            current_tree_value = jump_restore_item_id
        elif tree_items and current_tree_value not in tree_item_ids:
            st.session_state.pop(tree_key, None)
            current_tree_value = None
        if project_code and not selected_product_id:
            st.info("상품을 먼저 선택하면 공정품 트리와 요구/지시 선택이 열립니다.")
            return
        elif project_code and selected_product_id and not tree_items:
            st.warning("선택한 상품에 등록된 공정품이 없습니다. 먼저 공정품 정보를 확인해 주세요.")
            return

        selected_item_label = ""
        selected_item_id = None
        with top_c3:
            if tree_items:
                if st.session_state.get(tree_key) not in tree_item_ids:
                    st.session_state.pop(tree_key, None)
                selected_item_id = st.selectbox(
                    "트리 선택",
                    options=tree_item_ids,
                    format_func=lambda item_id: next(
                        (label for label, iid in tree_items if int(iid) == int(item_id)),
                        "",
                    )
                    if int(item_id)
                    else "",
                    index=tree_item_ids.index(int(current_tree_value)) if current_tree_value in tree_item_ids else 0,
                    key=tree_key,
                    disabled=instruction_locked,
                )
                selected_item_id = int(selected_item_id) if selected_item_id else None
                previous_item_id = int(previous_active_item_id) if previous_active_item_id else None
                current_item_id = int(selected_item_id) if selected_item_id else None
                item_changed = previous_item_id != current_item_id
                if item_changed and not instruction_locked and jump_restore_item_id is None:
                    _clear_instruction_selection_after_item_change(
                        order_key=order_key,
                        existing_pick_key=existing_pick_key,
                        active_order_state_key=active_order_state_key,
                        active_instruction_state_key=active_instruction_state_key,
                    )
                if selected_item_id:
                    st.session_state[active_item_state_key] = int(selected_item_id)
                else:
                    st.session_state.pop(active_item_state_key, None)
            else:
                st.selectbox("트리 선택", options=[""], key=f"{tree_key}_empty", disabled=True)
                st.session_state.pop(active_item_state_key, None)

        if project_code and selected_product_id and not selected_item_id:
            st.info("공정품을 먼저 선택하면 공정품 트리와 요구/지시 선택이 열립니다.")
            return

        selected_item_row = get_item_row(selected_item_id) if selected_item_id else None
        selected_item_process = infer_process_type_from_item(selected_item_row) if selected_item_row is not None else ""
        is_injection_item = selected_item_process == "사출"
        selected_instruction_row = None
        selected_order_row = None
        selected_order_id = None
        process_type = ""
        instruction_mode = ""

        if is_injection_item:
            locked_instruction_id = st.session_state.get(active_instruction_state_key)
            locked_order_id = st.session_state.get(active_order_state_key)
            if instruction_locked:
                jump_instruction_id_locked = jump_instruction_id
                jump_order_id_locked = jump_order_id
                if not locked_instruction_id and jump_instruction_id_locked:
                    locked_instruction_id = int(jump_instruction_id_locked)
                    st.session_state[active_instruction_state_key] = int(locked_instruction_id)
                if not locked_order_id and jump_order_id_locked:
                    locked_order_id = int(jump_order_id_locked)
                    st.session_state[active_order_state_key] = int(locked_order_id)
            if instruction_locked:
                instruction_mode = "수정" if locked_instruction_id else "신규"
                with top_c4:
                    st.text_input(
                        "모드",
                        value=instruction_mode,
                        key=f"{scope_key}_mode_locked",
                        disabled=True,
                    )
                if instruction_mode == "신규" and locked_order_id:
                    selected_order_id = int(locked_order_id)
                    order_match = orders_df[
                        pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id
                    ] if not orders_df.empty else orders_df
                    selected_order_row = order_match.iloc[0] if not order_match.empty else None
                    process_type = str(selected_order_row["process_type"]) if selected_order_row is not None else ""
                    with top_c5:
                        st.text_input(
                            "고객요구",
                            value=_instruction_order_pick_label(selected_order_row) if selected_order_row is not None else "",
                            key=f"{order_key}_locked",
                            disabled=True,
                        )
                elif instruction_mode == "수정" and locked_instruction_id:
                    selected_instruction_id = int(locked_instruction_id)
                    selected_instruction_match = instructions_df[
                        pd.to_numeric(instructions_df["experiment_instruction_id"], errors="coerce") == selected_instruction_id
                    ] if not instructions_df.empty else instructions_df
                    selected_instruction_row = selected_instruction_match.iloc[0] if not selected_instruction_match.empty else None
                    with top_c5:
                        st.text_input(
                            "실험지시",
                            value=_instruction_pick_label(selected_instruction_row) if selected_instruction_row is not None else "",
                            key=f"{existing_pick_key}_locked",
                            disabled=True,
                        )
                    if selected_instruction_row is not None:
                        selected_order_id = int(selected_instruction_row["experiment_order_id"])
                        st.session_state[active_order_state_key] = int(selected_order_id)
                        order_match = orders_df[
                            pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id
                        ] if not orders_df.empty else orders_df
                        selected_order_row = order_match.iloc[0] if not order_match.empty else None
                        process_type = "사출"
            else:
                with top_c4:
                    instruction_mode = st.selectbox("모드", options=["신규", "수정"], key=f"{scope_key}_mode", disabled=instruction_locked)
            if not instruction_locked and instruction_mode == "신규":
                orders = list_order_options_for_project(project_code) if project_code else []
                if selected_item_id:
                    orders = [(label, oid) for label, oid in orders if not orders_df[(orders_df["experiment_order_id"] == oid) & (orders_df["item_id"] == selected_item_id)].empty]
                order_display_options: list[tuple[str, int, tuple]] = []
                for label, oid in orders:
                    order_match = orders_df[orders_df["experiment_order_id"] == oid]
                    order_row_for_label = order_match.iloc[0] if not order_match.empty else None
                    if not instructions_df.empty and not instructions_df[
                        pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == int(oid)
                    ].empty:
                        continue
                    if order_row_for_label is not None and str(order_row_for_label.get("status") or "") == "완료":
                        continue
                    order_detail_for_label = parse_json_text(order_row_for_label["requirement_detail_json"]) if order_row_for_label is not None else {}
                    if str(order_detail_for_label.get("execution_mode") or "") == "재고사용":
                        continue
                    if selected_product_id and order_row_for_label is not None and pd.notna(order_row_for_label.get("product_id")) and int(order_row_for_label.get("product_id")) != int(selected_product_id):
                        continue
                    order_code_for_label = str(order_row_for_label["order_code"]) if order_row_for_label is not None else ""
                    sort_key = (
                        str(order_row_for_label.get("target_due_date") or "9999-12-31"),
                        order_code_for_label,
                    ) if order_row_for_label is not None else ("9999-12-31", "")
                    display_text = _instruction_order_pick_label(order_row_for_label) if order_row_for_label is not None else label
                    order_display_options.append((display_text or label, oid, sort_key))
                order_display_options = sorted(order_display_options, key=lambda row: row[2])
                active_order_id = jump_order_id if jump_order_id else st.session_state.get(active_order_state_key)
                default_order_label = next((label for label, oid, _ in order_display_options if jump_order_id and int(oid) == int(jump_order_id)), "")
                with top_c5:
                    order_labels = [""] + [label for label, _, _ in order_display_options]
                    active_order_label = next(
                        (label for label, oid, _ in order_display_options if active_order_id and int(oid) == int(active_order_id)),
                        "",
                    )
                    current_order_label = str(st.session_state.get(order_key, "") or "")
                    if current_order_label and current_order_label not in order_labels:
                        st.session_state.pop(order_key, None)
                        current_order_label = ""
                    preferred_order_label = current_order_label or default_order_label or active_order_label or ""
                    if st.session_state.get(order_key) not in order_labels:
                        st.session_state.pop(order_key, None)
                    selected_order_label = st.selectbox(
                        "고객요구",
                        options=order_labels,
                        index=order_labels.index(preferred_order_label) if preferred_order_label in order_labels else 0,
                        key=order_key,
                        disabled=instruction_locked,
                    )
                selected_order_id = {label: oid for label, oid, _ in order_display_options}.get(selected_order_label) if selected_order_label else None
                if not selected_order_id and active_order_id:
                    fallback_order_match = orders_df[
                        pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == int(active_order_id)
                    ] if not orders_df.empty else orders_df
                    if not fallback_order_match.empty:
                        selected_order_id = int(active_order_id)
                if selected_order_id:
                    st.session_state[active_order_state_key] = int(selected_order_id)
                    st.session_state.pop(active_instruction_state_key, None)
                    selected_order_row = orders_df[orders_df["experiment_order_id"] == selected_order_id].iloc[0]
                    process_type = str(selected_order_row["process_type"])
                else:
                    st.session_state.pop(active_order_state_key, None)
            elif not instruction_locked:
                filtered_instructions = instructions_df[instructions_df["project_code"] == project_code] if project_code else instructions_df.iloc[0:0]
                if selected_product_id and not filtered_instructions.empty and "product_id" in filtered_instructions.columns:
                    filtered_instructions = filtered_instructions[pd.to_numeric(filtered_instructions["product_id"], errors="coerce") == int(selected_product_id)]
                if selected_item_id:
                    filtered_instructions = filtered_instructions[filtered_instructions["item_id"] == selected_item_id]
                filtered_instructions = filtered_instructions[filtered_instructions["process_type"] == "사출"] if not filtered_instructions.empty else filtered_instructions
                instruction_option_map = {
                    _instruction_pick_label(row): int(row["experiment_instruction_id"])
                    for _, row in filtered_instructions.iterrows()
                } if not filtered_instructions.empty else {}
                instruction_options = [""] + list(instruction_option_map.keys())
                active_instruction_id = jump_instruction_id if jump_instruction_id else st.session_state.get(active_instruction_state_key)
                default_instruction_pick = next((label for label, iid in instruction_option_map.items() if jump_instruction_id and int(iid) == int(jump_instruction_id)), "")
                with top_c5:
                    active_instruction_pick = next(
                        (label for label, iid in instruction_option_map.items() if active_instruction_id and int(iid) == int(active_instruction_id)),
                        "",
                    )
                    current_instruction_pick = str(st.session_state.get(existing_pick_key, "") or "")
                    if current_instruction_pick and current_instruction_pick not in instruction_options:
                        st.session_state.pop(existing_pick_key, None)
                        current_instruction_pick = ""
                    preferred_instruction_pick = current_instruction_pick or default_instruction_pick or active_instruction_pick or ""
                    if st.session_state.get(existing_pick_key) not in instruction_options:
                        st.session_state.pop(existing_pick_key, None)
                    selected_instruction_pick = st.selectbox(
                        "실험지시",
                        options=instruction_options,
                        index=instruction_options.index(preferred_instruction_pick) if preferred_instruction_pick in instruction_options else 0,
                        key=existing_pick_key,
                        disabled=instruction_locked,
                    )
                selected_instruction_id = instruction_option_map.get(selected_instruction_pick) if selected_instruction_pick else None
                if not selected_instruction_id and active_instruction_id and not filtered_instructions.empty:
                    fallback_instruction_match = filtered_instructions[
                        pd.to_numeric(filtered_instructions["experiment_instruction_id"], errors="coerce") == int(active_instruction_id)
                    ]
                    if not fallback_instruction_match.empty:
                        selected_instruction_id = int(active_instruction_id)
                if selected_instruction_id and not filtered_instructions.empty:
                    st.session_state[active_instruction_state_key] = int(selected_instruction_id)
                    selected_instruction_match = filtered_instructions[filtered_instructions["experiment_instruction_id"] == selected_instruction_id]
                    selected_instruction_row = selected_instruction_match.iloc[0] if not selected_instruction_match.empty else None
                if selected_instruction_row is not None:
                    selected_order_id = int(selected_instruction_row["experiment_order_id"])
                    st.session_state[active_order_state_key] = int(selected_order_id)
                    order_match = orders_df[pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id] if not orders_df.empty else orders_df
                    selected_order_row = order_match.iloc[0] if not order_match.empty else None
                    process_type = "사출"
                elif not selected_instruction_id:
                    st.session_state.pop(active_instruction_state_key, None)
        else:
            locked_instruction_id = st.session_state.get(active_instruction_state_key)
            locked_order_id = st.session_state.get(active_order_state_key)
            if instruction_locked:
                jump_instruction_id_locked = jump_instruction_id
                jump_order_id_locked = jump_order_id
                if not locked_instruction_id and jump_instruction_id_locked:
                    locked_instruction_id = int(jump_instruction_id_locked)
                    st.session_state[active_instruction_state_key] = int(locked_instruction_id)
                if not locked_order_id and jump_order_id_locked:
                    locked_order_id = int(jump_order_id_locked)
                    st.session_state[active_order_state_key] = int(locked_order_id)
            if instruction_locked:
                instruction_mode = "수정" if locked_instruction_id else "신규"
                with top_c4:
                    st.text_input(
                        "모드",
                        value=instruction_mode,
                        key=f"{scope_key}_mode_locked",
                        disabled=True,
                    )
            else:
                with top_c4:
                    instruction_mode = st.selectbox("모드", options=["신규", "수정"], key=f"{scope_key}_mode", disabled=instruction_locked)
            orders = list_order_options_for_project(project_code) if project_code else []
            if selected_item_id:
                orders = [(label, oid) for label, oid in orders if not orders_df[(orders_df["experiment_order_id"] == oid) & (orders_df["item_id"] == selected_item_id)].empty]
            order_display_options: list[tuple[str, int, tuple]] = []
            for label, oid in orders:
                order_match = orders_df[orders_df["experiment_order_id"] == oid]
                order_row_for_label = order_match.iloc[0] if not order_match.empty else None
                if not instructions_df.empty and not instructions_df[
                    pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == int(oid)
                ].empty:
                    continue
                if order_row_for_label is not None and str(order_row_for_label.get("status") or "") == "완료":
                    continue
                order_detail_for_label = parse_json_text(order_row_for_label["requirement_detail_json"]) if order_row_for_label is not None else {}
                if str(order_detail_for_label.get("execution_mode") or "") == "재고사용":
                    continue
                if selected_product_id and order_row_for_label is not None and pd.notna(order_row_for_label.get("product_id")) and int(order_row_for_label.get("product_id")) != int(selected_product_id):
                    continue
                order_code_for_label = str(order_row_for_label["order_code"]) if order_row_for_label is not None else ""
                sort_key = (
                    str(order_row_for_label.get("target_due_date") or "9999-12-31"),
                    order_code_for_label,
                ) if order_row_for_label is not None else ("9999-12-31", "")
                display_text = _instruction_order_pick_label(order_row_for_label) if order_row_for_label is not None else label
                order_display_options.append((display_text or label, oid, sort_key))
            order_display_options = sorted(order_display_options, key=lambda row: row[2])
            if instruction_locked:
                if instruction_mode == "신규" and locked_order_id:
                    selected_order_id = int(locked_order_id)
                    order_match = orders_df[
                        pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id
                    ] if not orders_df.empty else orders_df
                    selected_order_row = order_match.iloc[0] if not order_match.empty else None
                    process_type = str(selected_order_row["process_type"]) if selected_order_row is not None else ""
                    with top_c5:
                        st.text_input(
                            "고객요구",
                            value=_instruction_order_pick_label(selected_order_row) if selected_order_row is not None else "",
                            key=f"{order_key}_locked",
                            disabled=True,
                        )
                elif instruction_mode == "수정" and locked_instruction_id:
                    selected_instruction_id = int(locked_instruction_id)
                    selected_instruction_match = instructions_df[
                        pd.to_numeric(instructions_df["experiment_instruction_id"], errors="coerce") == selected_instruction_id
                    ] if not instructions_df.empty else instructions_df
                    selected_instruction_row = selected_instruction_match.iloc[0] if not selected_instruction_match.empty else None
                    with top_c5:
                        st.text_input(
                            "실험지시",
                            value=_instruction_pick_label(selected_instruction_row) if selected_instruction_row is not None else "",
                            key=f"{existing_pick_key}_locked",
                            disabled=True,
                        )
                    if selected_instruction_row is not None:
                        selected_order_id = int(selected_instruction_row["experiment_order_id"])
                        st.session_state[active_order_state_key] = int(selected_order_id)
                        order_match = orders_df[
                            pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id
                        ] if not orders_df.empty else orders_df
                        selected_order_row = order_match.iloc[0] if not order_match.empty else None
                        process_type = str(selected_instruction_row["process_type"])
            if project_code and selected_item_id and not orders:
                st.warning("선택한 공정품에 등록된 고객요구가 없습니다. 먼저 고객요구를 등록해 주세요.")
            if not instruction_locked:
                with top_c5:
                    if instruction_mode == "신규":
                        active_order_id = jump_order_id if jump_order_id else st.session_state.get(active_order_state_key)
                        default_order_label = next((label for label, oid, _ in order_display_options if jump_order_id and int(oid) == int(jump_order_id)), "")
                        order_labels = [""] + [label for label, _, _ in order_display_options]
                        active_order_label = next(
                            (label for label, oid, _ in order_display_options if active_order_id and int(oid) == int(active_order_id)),
                            "",
                        )
                        current_order_label = str(st.session_state.get(order_key, "") or "")
                        if current_order_label and current_order_label not in order_labels:
                            st.session_state.pop(order_key, None)
                            current_order_label = ""
                        preferred_order_label = current_order_label or default_order_label or active_order_label or ""
                        if st.session_state.get(order_key) not in order_labels:
                            st.session_state.pop(order_key, None)
                        selected_order_label = st.selectbox(
                            "고객요구",
                            options=order_labels,
                            index=order_labels.index(preferred_order_label) if preferred_order_label in order_labels else 0,
                            key=order_key,
                            disabled=instruction_locked,
                        )
                        selected_order_id = {label: oid for label, oid, _ in order_display_options}.get(selected_order_label) if selected_order_label else None
                        if not selected_order_id and active_order_id:
                            fallback_order_match = orders_df[
                                pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == int(active_order_id)
                            ] if not orders_df.empty else orders_df
                            if not fallback_order_match.empty:
                                selected_order_id = int(active_order_id)
                        if selected_order_id:
                            st.session_state[active_order_state_key] = int(selected_order_id)
                            st.session_state.pop(active_instruction_state_key, None)
                            selected_order_row = orders_df[orders_df["experiment_order_id"] == selected_order_id].iloc[0]
                            process_type = str(selected_order_row["process_type"])
                        else:
                            st.session_state.pop(active_order_state_key, None)
                    else:
                        filtered_instructions = instructions_df[instructions_df["project_code"] == project_code] if project_code else instructions_df.iloc[0:0]
                        if selected_product_id and not filtered_instructions.empty and "product_id" in filtered_instructions.columns:
                            filtered_instructions = filtered_instructions[pd.to_numeric(filtered_instructions["product_id"], errors="coerce") == int(selected_product_id)]
                        if selected_item_id:
                            filtered_instructions = filtered_instructions[filtered_instructions["item_id"] == selected_item_id]
                        if selected_item_process:
                            filtered_instructions = filtered_instructions[filtered_instructions["process_type"] == selected_item_process] if not filtered_instructions.empty else filtered_instructions
                        instruction_option_map = {
                            _instruction_pick_label(row): int(row["experiment_instruction_id"])
                            for _, row in filtered_instructions.iterrows()
                        } if not filtered_instructions.empty else {}
                        active_instruction_id = jump_instruction_id if jump_instruction_id else st.session_state.get(active_instruction_state_key)
                        instruction_options = [""] + list(instruction_option_map.keys())
                        default_instruction_pick = next((label for label, iid in instruction_option_map.items() if jump_instruction_id and int(iid) == int(jump_instruction_id)), "")
                        active_instruction_pick = next(
                            (label for label, iid in instruction_option_map.items() if active_instruction_id and int(iid) == int(active_instruction_id)),
                            "",
                        )
                        current_instruction_pick = str(st.session_state.get(existing_pick_key, "") or "")
                        if current_instruction_pick and current_instruction_pick not in instruction_options:
                            st.session_state.pop(existing_pick_key, None)
                            current_instruction_pick = ""
                        preferred_instruction_pick = current_instruction_pick or default_instruction_pick or active_instruction_pick or ""
                        if st.session_state.get(existing_pick_key) not in instruction_options:
                            st.session_state.pop(existing_pick_key, None)
                        selected_instruction_pick = st.selectbox(
                            "실험지시",
                            options=instruction_options,
                            index=instruction_options.index(preferred_instruction_pick) if preferred_instruction_pick in instruction_options else 0,
                            key=existing_pick_key,
                            disabled=instruction_locked,
                        )
                        selected_instruction_id = instruction_option_map.get(selected_instruction_pick) if selected_instruction_pick else None
                        if not selected_instruction_id and active_instruction_id and not filtered_instructions.empty:
                            fallback_instruction_match = filtered_instructions[
                                pd.to_numeric(filtered_instructions["experiment_instruction_id"], errors="coerce") == int(active_instruction_id)
                            ]
                            if not fallback_instruction_match.empty:
                                selected_instruction_id = int(active_instruction_id)
                        if selected_instruction_id and not filtered_instructions.empty:
                            st.session_state[active_instruction_state_key] = int(selected_instruction_id)
                            selected_instruction_match = filtered_instructions[filtered_instructions["experiment_instruction_id"] == selected_instruction_id]
                            selected_instruction_row = selected_instruction_match.iloc[0] if not selected_instruction_match.empty else None
                        if selected_instruction_row is not None:
                            selected_order_id = int(selected_instruction_row["experiment_order_id"])
                            st.session_state[active_order_state_key] = int(selected_order_id)
                            order_match = orders_df[pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id] if not orders_df.empty else orders_df
                            selected_order_row = order_match.iloc[0] if not order_match.empty else None
                            process_type = str(selected_instruction_row["process_type"])
                        elif not selected_instruction_id:
                            st.session_state.pop(active_instruction_state_key, None)

        left_col, right_col = st.columns([1.0, 2.0])

        linked_mb_request_row = None
        if selected_order_id and not mb_requests_df.empty:
            matched = mb_requests_df[mb_requests_df["experiment_order_id"] == selected_order_id]
            if not matched.empty:
                linked_mb_request_row = matched.iloc[0]

        linked_mold_dispatch_row = None
        if selected_order_id and not mold_dispatch_df.empty:
            matched_dispatch = mold_dispatch_df[mold_dispatch_df["experiment_order_id"] == selected_order_id]
            if not matched_dispatch.empty:
                linked_mold_dispatch_row = matched_dispatch.iloc[0]

        filtered_samples = samples_df.iloc[0:0]
        selected_row = None
        if project_code and selected_item_id:
            filtered_samples = filter_instruction_samples(
                samples_df,
                project_code,
                selected_item_id,
                selected_order_row["order_code"] if selected_order_row is not None else None,
            )

        project_molds = list_mold_options_for_project(project_code) if project_code else []
        project_films = list_film_options_for_project(project_code) if project_code else []
        project_raw_materials = list_raw_material_options_for_project(project_code) if project_code else []
        order_detail = parse_json_text(selected_order_row["requirement_detail_json"]) if selected_order_row is not None else {}
        selected_order_total_required_qty = _order_total_required_qty(
            selected_order_row,
            linked_requirement_extra_qty_by_order,
        )
        requirement_checks = (
            json.loads(selected_order_row["requirement_checks_json"])
            if selected_order_row is not None and selected_order_row["requirement_checks_json"]
            else derive_requirement_checks(process_type, order_detail) if process_type else []
        )

        if is_injection_item or process_type == "사출":
            if selected_order_id and not instructions_df.empty and selected_instruction_row is None:
                filtered_instructions = instructions_df[(instructions_df["experiment_order_id"] == selected_order_id)].copy()
                if not filtered_instructions.empty and instruction_mode == "수정":
                    selected_instruction_row = filtered_instructions.iloc[0]
            if selected_instruction_row is not None and selected_order_row is None:
                selected_order_id = int(selected_instruction_row["experiment_order_id"])
                order_match = orders_df[pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == selected_order_id] if not orders_df.empty else orders_df
                selected_order_row = order_match.iloc[0] if not order_match.empty else None
                process_type = "사출"
            selected_instruction_detail = (
                parse_json_text(selected_instruction_row["instruction_detail_json"])
                if selected_instruction_row is not None else {}
            )
            current_drawing_info = get_current_product_drawing_for_item(int(selected_item_id)) if selected_item_id else None
            current_drawing_rev = _clean_label_value(current_drawing_info.get("revision_no", "") if current_drawing_info else "")

            with left_col:
                render_section_title("요구 요약")
                if selected_order_row is None:
                    st.caption("고객요구를 선택하면 요약이 표시됩니다.")
                else:
                    meta_info_text = "-"
                    selected_meta_id = (
                        int(selected_order_row["meta_requirement_id"])
                        if "meta_requirement_id" in selected_order_row.index and pd.notna(selected_order_row["meta_requirement_id"])
                        else None
                    )
                    selected_meta_row = get_meta_requirement_row(selected_meta_id) if selected_meta_id else None
                    if selected_meta_row is not None:
                        meta_tree_mode = str(order_detail.get("_meta_tree_mode") or selected_meta_row["tree_mode"] or "기본")
                        meta_root_item_id = (
                            int(selected_meta_row["root_item_id"])
                            if "root_item_id" in selected_meta_row.keys() and pd.notna(selected_meta_row["root_item_id"])
                            else None
                        )
                        meta_root_order_df = (
                            orders_df[
                                (pd.to_numeric(orders_df["meta_requirement_id"], errors="coerce") == int(selected_meta_id))
                                & (pd.to_numeric(orders_df["item_id"], errors="coerce") == int(meta_root_item_id))
                            ].copy()
                            if not orders_df.empty and meta_root_item_id
                            else orders_df.iloc[0:0]
                        )
                        meta_root_order_code = str(meta_root_order_df.iloc[-1]["order_code"]) if not meta_root_order_df.empty else ""
                        meta_info_text = f"{'기본조립' if meta_tree_mode == '기본' else '조합조립'} | {meta_root_order_code or selected_meta_row['meta_code']}"
                    raw_material_text = " / ".join(
                        [
                            value for value in [
                                str(order_detail.get("raw_material_1_label") or "").strip(),
                                str(order_detail.get("raw_material_2_label") or "").strip(),
                            ] if value
                        ]
                    ) or "-"
                    with st.container(border=True):
                        row1_c1, row1_c2, row1_c3 = st.columns(3)
                        with row1_c1:
                            st.caption("납기일")
                            st.write(str(selected_order_row["target_due_date"] or "-"))
                        with row1_c2:
                            st.caption("수량")
                            st.write(str(selected_order_total_required_qty or "-"))
                        with row1_c3:
                            st.caption("마일스톤")
                            st.write(selected_order_row["milestone_name"] or "-")

                        row2_c1, row2_c2 = st.columns(2)
                        with row2_c1:
                            st.caption("메타정보")
                            st.write(meta_info_text)
                        with row2_c2:
                            st.caption("공정요구코드")
                            st.write(str(selected_order_row["order_code"] or "-"))

                        row3_c1, row3_c2, row3_c3 = st.columns(3)
                        with row3_c1:
                            st.caption("금형수정")
                            st.write("있음" if order_detail.get("mold_dispatch_required") else "없음")
                        with row3_c2:
                            st.caption("색상")
                            color_text = "있음" if order_detail.get("color_required") else "없음"
                            if order_detail.get("color_required"):
                                color_sample_text = str(order_detail.get("color_sample_exists", "") or "").strip()
                                if color_sample_text:
                                    color_text = f"{color_text} / {color_sample_text}"
                            st.write(color_text)
                        with row3_c3:
                            st.caption("원료")
                            st.write(raw_material_text)

            with right_col:
                render_section_title("사출 지시")
                if project_row is not None:
                    st.caption(f"상품코드: {selected_item_row.get('product_code', '') if selected_item_row is not None else '-'} / 개발형태: {project_row.get('development_type', '-') or '-'}")
                identity_label = _build_display_label(
                    str(selected_item_row.get("item_code", "") if selected_item_row is not None else ""),
                    str(selected_item_row.get("item_name", "") if selected_item_row is not None else ""),
                    current_drawing_rev,
                    str(selected_item_row.get("base_material_label", "") if selected_item_row is not None else ""),
                    "",
                    "",
                    "도면",
                )
                st.caption(identity_label or "-")
                if selected_order_row is None:
                    st.info("신규는 고객요구를, 수정은 기존 실험지시를 선택하면 사출 지시 입력창이 열립니다.")
                    return

                common_c1, common_c2, common_c3, common_c4 = st.columns(4)
                default_required_qty = (
                    _safe_int_value(selected_instruction_row["required_sample_qty"], 1)
                    if selected_instruction_row is not None and pd.notna(selected_instruction_row["required_sample_qty"])
                    else selected_order_total_required_qty
                )
                default_finish_date = (
                    _safe_date_value(selected_instruction_row["requested_finish_date"])
                    if selected_instruction_row is not None and selected_instruction_row["requested_finish_date"]
                    else (_safe_date_value(selected_order_row["target_due_date"]) if selected_order_row["target_due_date"] else None)
                )
                saved_mold_id = int(selected_instruction_detail.get("mold_id")) if selected_instruction_detail.get("mold_id") else None
                candidate_project_molds, mold_filter_note = _candidate_mold_options_for_item(
                    selected_item_row,
                    project_molds,
                    preferred_mold_id=saved_mold_id,
                )
                mold_option_map = dict(candidate_project_molds)
                mold_labels = [""] + [label for label, _ in candidate_project_molds]
                selected_mold_label = next((label for label, mold_id in mold_option_map.items() if mold_id == saved_mold_id), "")
                default_machine_no = str(selected_instruction_row["machine_no"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["machine_no"]) else ""
                default_machine_ton = str(selected_instruction_row["machine_ton"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["machine_ton"]) else ""
                with common_c1:
                    instruction_required_qty = st.number_input("필요샘플수", min_value=1, step=1, value=default_required_qty, key=f"instruction_req_qty_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}")
                with common_c2:
                    instruction_finish_date = st.date_input("완료요청일", value=default_finish_date, key=f"instruction_finish_date_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}")
                with common_c3:
                    instruction_machine_no = st.text_input("호기", value=default_machine_no, key=f"instruction_machine_no_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}")
                with common_c4:
                    instruction_machine_ton = st.text_input("톤수", value=default_machine_ton, key=f"instruction_machine_ton_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}")

                mode_c1, mode_c2, mode_c3 = st.columns([0.8, 1.2, 1.2])
                instruction_execution_mode_ui = _execution_mode_ui_value(str(selected_instruction_detail.get("execution_mode") or "내부"))
                with mode_c1:
                    instruction_execution_mode_ui = st.selectbox(
                        "실행방식",
                        options=["내부", "외부"],
                        index=["내부", "외부"].index(instruction_execution_mode_ui),
                        key=f"instruction_execution_mode_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                    )
                instruction_execution_mode = _execution_mode_storage_value(instruction_execution_mode_ui)
                default_instruction_vendor = str(selected_instruction_detail.get("vendor_name") or ("내부" if instruction_execution_mode == "내부" else ""))
                with mode_c2:
                    instruction_vendor_name = st.text_input(
                        "실험할곳",
                        value=default_instruction_vendor,
                        disabled=instruction_execution_mode == "내부",
                        key=f"instruction_vendor_name_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                    )
                with mode_c3:
                    mold_label = st.selectbox(
                        "금형선택",
                        options=mold_labels,
                        index=mold_labels.index(selected_mold_label) if selected_mold_label in mold_labels else 0,
                        key=f"instruction_mold_label_main_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                    )
                if mold_filter_note:
                    st.caption(mold_filter_note)

                cond_c1, cond_c2, cond_c3 = st.columns(3)
                with cond_c1:
                    with st.container(border=True):
                        st.caption("금형수정")
                        st.text_input(
                            "금형출고상태",
                            value=str(linked_mold_dispatch_row["status"]) if linked_mold_dispatch_row is not None and order_detail.get("mold_dispatch_required") else "-",
                            disabled=True,
                            key=f"instruction_mold_dispatch_status_{selected_order_id}",
                        )
                        st.text_input(
                            "도면 Rev",
                            value=(f"R{current_drawing_rev}" if current_drawing_rev and not current_drawing_rev.upper().startswith("R") else current_drawing_rev) or "-",
                            disabled=True,
                            key=f"instruction_drawing_rev_{selected_order_id}",
                        )
                with cond_c2:
                    with st.container(border=True):
                        st.caption("색상실험")
                        color_vendor_name = st.text_input(
                            "MB생산할곳",
                            value=str(
                                selected_instruction_detail.get("mb_supplier_name")
                                or selected_instruction_detail.get("color_vendor_name")
                                or (linked_mb_request_row["supplier_name"] if linked_mb_request_row is not None and pd.notna(linked_mb_request_row["supplier_name"]) else "")
                            ),
                            disabled=not order_detail.get("color_required"),
                            key=f"instruction_color_vendor_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                        )
                        color_due_date = st.date_input(
                            "납기일",
                            value=(
                                _safe_date_value(selected_instruction_detail.get("mb_expected_receipt_date"))
                                if selected_instruction_detail.get("mb_expected_receipt_date")
                                else (_safe_date_value(selected_instruction_detail.get("vendor_due_date"))
                                     if selected_instruction_detail.get("vendor_due_date")
                                     else (_safe_date_value(linked_mb_request_row["expected_receipt_date"]) if linked_mb_request_row is not None and linked_mb_request_row["expected_receipt_date"] else None))
                            ),
                            disabled=not order_detail.get("color_required"),
                            key=f"instruction_color_due_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                        )
                        color_instruction = st.text_input(
                            "색상지시",
                            value=str(
                                selected_instruction_detail.get("mb_nuance")
                                or selected_instruction_detail.get("color_instruction")
                                or order_detail.get("color_nuance", "")
                            ),
                            disabled=not order_detail.get("color_required"),
                            key=f"instruction_color_instruction_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                        )
                        color_sample_checked = st.checkbox(
                            "색상샘플확인",
                            value=bool(selected_instruction_detail.get("color_sample_checked", False)),
                            disabled=not order_detail.get("color_required"),
                            key=f"instruction_color_sample_checked_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                        )
                        color_physical_checked = st.checkbox(
                            "실물확인",
                            value=bool(selected_instruction_detail.get("color_physical_checked", False)),
                            disabled=not order_detail.get("color_required"),
                            key=f"instruction_color_physical_checked_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                        )
                color_plan_rows: list[dict] = []
                if order_detail.get("color_required"):
                    render_section_title("색상샘플 계획")
                    saved_plan_rows = selected_instruction_detail.get("color_plan_rows", selected_instruction_detail.get("mb_ratio_plan_rows", []))
                    plan_cols = st.columns(4)
                    for idx in range(1, 5):
                        saved_row = saved_plan_rows[idx - 1] if idx - 1 < len(saved_plan_rows) else {}
                        default_ratio = float(saved_row.get("ratio", 0.0) or 0.0)
                        with plan_cols[idx - 1]:
                            ratio_value = st.number_input(
                                f"{idx}안(%)",
                                min_value=0.0,
                                step=0.1,
                                value=default_ratio,
                                key=f"instruction_color_plan_ratio_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}_{idx}",
                            )
                        if float(ratio_value) > 0:
                            color_plan_rows.append({"label": f"{idx}안", "ratio": float(ratio_value)})
                with cond_c3:
                    with st.container(border=True):
                        st.caption("원료실험")
                        instruction_raw_material = st.text_input(
                            "원료명",
                            value=str(
                                selected_instruction_detail.get("raw_material_label")
                                or " / ".join(
                                    [value for value in [order_detail.get("raw_material_1_label", ""), order_detail.get("raw_material_2_label", "")] if value]
                                )
                                or str(selected_item_row.get("base_material_label", "") if selected_item_row is not None else "")
                            ),
                            disabled=not order_detail.get("raw_material_experiment_required"),
                            key=f"instruction_raw_material_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                        )

                render_section_title("규격 위치 / 값 / 외관 구분 / 위치")
                spec_locations: list[str] = []
                spec_values: list[str] = []
                appearance_items: list[str] = []
                appearance_positions: list[str] = []
                legacy_appearance_note = str(selected_instruction_detail.get("appearance_position_note", "") or "").strip()
                appearance_options = ["", "수축", "웰드라인", "플로우마크", "기타"]
                for idx in range(1, 5):
                    row_c1, row_c2, row_c3, row_c4 = st.columns([1.15, 0.9, 0.95, 1.15])
                    default_spec_location = str(
                        selected_instruction_detail.get(f"spec_location_{idx}", "")
                        or (
                            selected_instruction_detail.get(f"measurement_title_{['A', 'B', 'C'][idx - 1]}", "")
                            if idx <= 3 else ""
                        )
                        or order_detail.get(f"spec_location_{idx}", "")
                        or ""
                    )
                    default_spec_value = str(
                        selected_instruction_detail.get(f"spec_value_{idx}", "")
                        or (
                            selected_instruction_detail.get(f"measurement_spec_{['A', 'B', 'C'][idx - 1]}", "")
                            if idx <= 3 else ""
                        )
                        or order_detail.get(f"spec_value_{idx}", "")
                        or ""
                    )
                    default_appearance_item = str(
                        selected_instruction_detail.get(f"appearance_item_{idx}", "")
                        or order_detail.get(f"appearance_item_{idx}", "")
                        or ""
                    )
                    default_appearance_position = str(
                        selected_instruction_detail.get(f"appearance_position_{idx}", "")
                        or (legacy_appearance_note if idx == 1 else "")
                        or order_detail.get(f"appearance_position_{idx}", "")
                        or ""
                    )
                    with row_c1:
                        spec_locations.append(
                            st.text_input(
                                "규격 위치" if idx == 1 else f"규격 위치 {idx}",
                                value=default_spec_location,
                                key=f"instruction_spec_location_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}_{idx}",
                            )
                        )
                    with row_c2:
                        spec_values.append(
                            st.text_input(
                                "값" if idx == 1 else f"값 {idx}",
                                value=default_spec_value,
                                key=f"instruction_spec_value_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}_{idx}",
                            )
                        )
                    with row_c3:
                        appearance_items.append(
                            st.selectbox(
                                "외관 구분" if idx == 1 else f"외관 구분 {idx}",
                                options=appearance_options,
                                index=appearance_options.index(default_appearance_item) if default_appearance_item in appearance_options else 0,
                                key=f"instruction_appearance_item_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}_{idx}",
                            )
                        )
                    with row_c4:
                        appearance_positions.append(
                            st.text_input(
                                "위치" if idx == 1 else f"위치 {idx}",
                                value=default_appearance_position,
                                key=f"instruction_appearance_position_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}_{idx}",
                            )
                        )

                requirement_completed = st.checkbox(
                    "요구완료",
                    value=bool(selected_instruction_row["requirement_completed"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["requirement_completed"]) else False,
                    key=f"instruction_requirement_completed_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )

                action_defs = [
                    ("저장", "save_instruction_button", selected_instruction_row is None),
                    ("수정", "update_instruction_button", selected_instruction_row is not None and not instruction_view_only),
                    ("삭제", "delete_instruction_button", selected_instruction_row is not None and not instruction_view_only),
                ]
                save_clicked, update_clicked, delete_clicked = render_page_actions(action_defs)
                if delete_clicked and selected_instruction_row is not None:
                    ok, message = delete_experiment_instruction(int(selected_instruction_row["experiment_instruction_id"]))
                    if ok:
                        clear_instruction_return_state()
                        flash_success(message)
                        st.rerun()
                    st.error(message)
                    return
                if save_clicked or update_clicked:
                    instruction_payload: ExperimentInstructionPayload = {
                        "experiment_order_id": int(selected_order_id),
                        "project_id": int(selected_order_row["project_id"]),
                        "item_id": int(selected_item_id),
                        "process_type": process_type,
                        "required_sample_qty": int(instruction_required_qty),
                        "requested_finish_date": str(instruction_finish_date) if instruction_finish_date else None,
                        "machine_no": instruction_machine_no,
                        "machine_ton": instruction_machine_ton,
                        "requirement_completed": bool(requirement_completed),
                        "detail_payload": {
                            "execution_mode": instruction_execution_mode,
                            "vendor_name": "내부" if instruction_execution_mode == "내부" else instruction_vendor_name.strip(),
                            "mold_id": mold_option_map.get(mold_label) if mold_label else None,
                            "mold_code": mold_label.split(" | ")[0].strip() if mold_label else "",
                            "mb_supplier_name": color_vendor_name.strip() if order_detail.get("color_required") else "",
                            "mb_nuance": color_instruction if order_detail.get("color_required") else "",
                            "mb_expected_receipt_date": str(color_due_date) if color_due_date and order_detail.get("color_required") else None,
                            "mb_sample_received": bool(color_sample_checked) if order_detail.get("color_required") else False,
                            "color_sample_checked": bool(color_sample_checked) if order_detail.get("color_required") else False,
                            "color_physical_checked": bool(color_physical_checked) if order_detail.get("color_required") else False,
                            "color_plan_rows": color_plan_rows if order_detail.get("color_required") else [],
                            "raw_material_label": instruction_raw_material if order_detail.get("raw_material_experiment_required") else "",
                            "spec_location_1": spec_locations[0].strip() if len(spec_locations) > 0 else "",
                            "spec_location_2": spec_locations[1].strip() if len(spec_locations) > 1 else "",
                            "spec_location_3": spec_locations[2].strip() if len(spec_locations) > 2 else "",
                            "spec_location_4": spec_locations[3].strip() if len(spec_locations) > 3 else "",
                            "spec_value_1": spec_values[0].strip() if len(spec_values) > 0 else "",
                            "spec_value_2": spec_values[1].strip() if len(spec_values) > 1 else "",
                            "spec_value_3": spec_values[2].strip() if len(spec_values) > 2 else "",
                            "spec_value_4": spec_values[3].strip() if len(spec_values) > 3 else "",
                            "measurement_title_A": spec_locations[0].strip() if len(spec_locations) > 0 else "",
                            "measurement_title_B": spec_locations[1].strip() if len(spec_locations) > 1 else "",
                            "measurement_title_C": spec_locations[2].strip() if len(spec_locations) > 2 else "",
                            "measurement_spec_A": spec_values[0].strip() if len(spec_values) > 0 else "",
                            "measurement_spec_B": spec_values[1].strip() if len(spec_values) > 1 else "",
                            "measurement_spec_C": spec_values[2].strip() if len(spec_values) > 2 else "",
                            "appearance_item_1": appearance_items[0] if len(appearance_items) > 0 else "",
                            "appearance_item_2": appearance_items[1] if len(appearance_items) > 1 else "",
                            "appearance_item_3": appearance_items[2] if len(appearance_items) > 2 else "",
                            "appearance_item_4": appearance_items[3] if len(appearance_items) > 3 else "",
                            "appearance_position_1": appearance_positions[0].strip() if len(appearance_positions) > 0 else "",
                            "appearance_position_2": appearance_positions[1].strip() if len(appearance_positions) > 1 else "",
                            "appearance_position_3": appearance_positions[2].strip() if len(appearance_positions) > 2 else "",
                            "appearance_position_4": appearance_positions[3].strip() if len(appearance_positions) > 3 else "",
                            "appearance_position_note": appearance_positions[0].strip() if len(appearance_positions) > 0 else "",
                        },
                    }
                    saved_instruction = _save_instruction_safely(
                        selected_instruction_row,
                        payload=instruction_payload,
                        current_user_name=current_user()["user_name"],
                    )
                    if saved_instruction is None:
                        return
                    _, instruction_code, mb_request_code = saved_instruction
                    clear_instruction_return_state()
                    success_message = f"실험지시를 저장했습니다. 코드: {instruction_code}"
                    if mb_request_code:
                        success_message += f" | MB의뢰 코드: {mb_request_code}"
                    flash_success(success_message)
                    st.rerun()
            project_history_df = orders_df[orders_df["project_code"] == project_code] if project_code else orders_df.iloc[0:0]
            if not project_history_df.empty:
                render_history_panel(
                    "이력 보기",
                    project_history_df[["order_code", "project_code", "item_code", "item_name", "process_type", "target_due_date", "required_sample_qty", "experiment_goal", "status"]],
                )
            return

        if process_type == "조립" and selected_order_row is not None:
            selected_meta_id = (
                int(selected_order_row["meta_requirement_id"])
                if "meta_requirement_id" in selected_order_row.index and pd.notna(selected_order_row["meta_requirement_id"])
                else None
            )
            active_meta_row = get_meta_requirement_row(selected_meta_id) if selected_meta_id else None
            active_meta_lines = list_meta_requirement_lines(selected_meta_id) if selected_meta_id else []
            active_meta_df = pd.DataFrame(active_meta_lines)
            all_child_ready = False
            try:
                wms_moves_df = operations_service.list_postprocess_item_moves()
            except Exception:
                wms_moves_df = pd.DataFrame()
            try:
                inventory_df = operations_service.list_sample_inventory()
            except Exception:
                inventory_df = pd.DataFrame()
            if selected_meta_id and not wms_moves_df.empty:
                wms_moves_df = wms_moves_df[
                    (pd.to_numeric(wms_moves_df["source_order_id"], errors="coerce").isin(
                        pd.to_numeric(
                            orders_df[
                                pd.to_numeric(orders_df["meta_requirement_id"], errors="coerce") == int(selected_meta_id)
                            ]["experiment_order_id"],
                            errors="coerce",
                        )
                    ))
                    | (pd.to_numeric(wms_moves_df["source_instruction_id"], errors="coerce").isin(
                        pd.to_numeric(
                            instructions_df[
                                pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce").isin(
                                    pd.to_numeric(
                                        orders_df[
                                            pd.to_numeric(orders_df["meta_requirement_id"], errors="coerce") == int(selected_meta_id)
                                        ]["experiment_order_id"],
                                        errors="coerce",
                                    )
                                )
                            ]["experiment_instruction_id"],
                            errors="coerce",
                        )
                    ))
                ].copy()

            with left_col:
                render_section_title("상태트리")
                if active_meta_df.empty or "item_id" not in active_meta_df.columns:
                    st.info("메타에 연결된 공정품 구성이 없습니다.")
                else:
                    line_rows = active_meta_df.copy()
                    line_rows = line_rows[pd.to_numeric(line_rows["item_id"], errors="coerce") != int(selected_item_id)]
                    if line_rows.empty:
                        st.caption("하위 공정품이 없습니다.")
                        all_child_ready = False
                    else:
                        st.caption("체크 | 공정품코드 | 상태 | 입력")
                        all_child_ready = True
                        for _, line_row in line_rows.sort_values(["level_no", "line_order", "meta_line_id"]).iterrows():
                            line_status = _assembly_line_status_info(
                                meta_line_row=line_row,
                                orders_df=orders_df,
                                instructions_df=instructions_df,
                                samples_df=samples_df,
                                moves_df=wms_moves_df,
                                inventory_df=inventory_df,
                                meta_requirement_id=int(selected_meta_id),
                            )
                            all_child_ready = all_child_ready and bool(line_status["is_ready"])
                            item_indent = "  " * max(int(line_row.get("level_no", 0) or 0) - 1, 0)
                            item_label = f"{item_indent}{str(line_row.get('item_code') or '-')}"
                            row_c1, row_c2, row_c3, row_c4 = st.columns([0.22, 1.2, 0.85, 0.5])
                            with row_c1:
                                st.checkbox(
                                    "선택",
                                    value=True,
                                    disabled=True,
                                    key=f"assembly_instruction_line_checked_{int(line_row['meta_line_id'])}",
                                    label_visibility="collapsed",
                                )
                            with row_c2:
                                st.write(item_label)
                            with row_c3:
                                st.caption(str(line_status["status"]))
                            with row_c4:
                                if line_status["is_experiment_target"] and line_status["order_row"] is not None:
                                    if st.button("입력", key=f"assembly_instruction_line_edit_{int(line_row['meta_line_id'])}", use_container_width=True):
                                        st.session_state["instruction_jump_request"] = {
                                            "project_code": project_code,
                                            "product_id": int(selected_product_id) if selected_product_id else None,
                                            "item_id": int(line_row["item_id"]),
                                            "scope": "공정품",
                                            "instruction_mode": "수정" if line_status["instruction_row"] is not None else "신규",
                                            "order_id": int(line_status["order_row"]["experiment_order_id"]),
                                            "instruction_id": int(line_status["instruction_row"]["experiment_instruction_id"]) if line_status["instruction_row"] is not None else None,
                                        }
                                        st.session_state["process_entry_mode"] = "from_assembly"
                                        st.rerun()
                                elif line_status["is_stock_target"]:
                                    st.caption("WMS")
                                else:
                                    st.caption("-")
            with right_col:
                render_section_title("조립 지시")
                with st.container():
                    if selected_item_id:
                        render_product_drawing_reference(selected_item_id)
                    else:
                        st.caption("도면 정보가 없습니다.")
                with st.expander("요구요약", expanded=True):
                    summary_df = pd.DataFrame(
                        [
                            {
                                "요구일": str(selected_order_row.get("requirement_date") or "-"),
                                "납기일": str(selected_order_row["target_due_date"] or "-"),
                                "수량": str(selected_order_total_required_qty or "-"),
                                "마일스톤": str(selected_order_row["milestone_name"] or "-"),
                                "요구코드": str(selected_order_row["order_code"] or "-"),
                                "요구내용": _build_requirement_content_summary(process_type, order_detail, selected_order_row) or "-",
                                "메타": str(active_meta_row["meta_code"]) if active_meta_row is not None else "-",
                            }
                        ]
                    )
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)
                st.caption(
                    " | ".join(
                        [
                            part
                            for part in [
                                str(active_meta_row["meta_code"]) if active_meta_row is not None else "",
                                str(active_meta_row["tree_mode"]) if active_meta_row is not None else "",
                                str(selected_item_row.get("item_code") or "") if selected_item_row is not None else "",
                                str(selected_item_row.get("item_name") or "") if selected_item_row is not None else "",
                            ]
                            if part
                        ]
                    )
                    or "-"
                )
                selected_instruction_detail = parse_json_text(selected_instruction_row["instruction_detail_json"]) if selected_instruction_row is not None else {}
                root_vendor_name = st.text_input(
                    "업체",
                    value=str(selected_instruction_detail.get("vendor_name", "")),
                    key=f"assembly_root_vendor_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                root_expected_receipt_date = st.date_input(
                    "완료요청일",
                    value=_safe_date_value(selected_instruction_detail.get("expected_receipt_date")) if selected_instruction_detail.get("expected_receipt_date") else (_safe_date_value(selected_order_row["target_due_date"]) if selected_order_row["target_due_date"] else None),
                    key=f"assembly_root_expected_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                reselection_requirement_type = selected_instruction_detail.get("reselection_requirement_type", selected_instruction_detail.get("reselection_requirement", "없음"))
                reselection_requirement_type = st.selectbox(
                    "업체 재선정",
                    options=VENDOR_RESELECTION_OPTIONS,
                    index=_select_index(VENDOR_RESELECTION_OPTIONS, reselection_requirement_type),
                    key=f"assembly_root_vendor_reselection_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                reselection_requirement = st.text_input(
                    "업체 재선정 기타",
                    value=str(selected_instruction_detail.get("reselection_requirement_extra", "")),
                    disabled=reselection_requirement_type != "기타",
                    key=f"assembly_root_vendor_reselection_extra_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                if order_detail.get("assembly_function") or order_detail.get("backing_spec") or order_detail.get("sub_material_other"):
                    info_c1, info_c2 = st.columns(2)
                    with info_c1:
                        st.text_area("기능 요구", value=str(order_detail.get("assembly_function", "")), height=80, disabled=True)
                        st.text_input("바킹 규격", value=str(order_detail.get("backing_spec", "")), disabled=True)
                    with info_c2:
                        st.text_area("부재료 기타", value=str(order_detail.get("sub_material_other", "")), height=80, disabled=True)
                assembly_note = st.text_area(
                    "지시 확인 메모",
                    height=88,
                    value=str(selected_instruction_detail.get("assembly_note", "")),
                    key=f"assembly_root_note_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                children_ready = bool(all_child_ready)
                if not children_ready:
                    st.caption("체크된 하위 공정품이 모두 `지시완료` 또는 `출고대기/완료` 상태여야 메타 완료를 체크할 수 있습니다.")
                requirement_completed = st.checkbox(
                    "요구완료",
                    value=bool(selected_instruction_row["requirement_completed"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["requirement_completed"]) and children_ready else False,
                    disabled=not children_ready,
                    key=f"assembly_root_requirement_completed_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                action_defs = [
                    ("저장", "save_assembly_instruction_button", selected_instruction_row is None),
                    ("수정", "update_assembly_instruction_button", selected_instruction_row is not None),
                    ("삭제", "delete_assembly_instruction_button", selected_instruction_row is not None),
                ]
                save_clicked, update_clicked, delete_clicked = render_page_actions(action_defs)
                if delete_clicked and selected_instruction_row is not None:
                    ok, message = delete_experiment_instruction(int(selected_instruction_row["experiment_instruction_id"]))
                    if ok:
                        clear_instruction_return_state()
                        flash_success(message)
                        st.rerun()
                    st.error(message)
                    return
                if save_clicked or update_clicked:
                    instruction_payload: ExperimentInstructionPayload = {
                        "experiment_order_id": int(selected_order_id),
                        "project_id": int(selected_order_row["project_id"]),
                        "item_id": int(selected_item_id),
                        "process_type": process_type,
                        "required_sample_qty": selected_order_total_required_qty,
                        "requested_finish_date": str(root_expected_receipt_date) if root_expected_receipt_date else None,
                        "machine_no": "",
                        "machine_ton": "",
                        "requirement_completed": bool(requirement_completed),
                        "detail_payload": {
                            "vendor_name": root_vendor_name,
                            "reselection_requirement_type": reselection_requirement_type,
                            "reselection_requirement_extra": reselection_requirement,
                            "reselection_requirement": reselection_requirement if reselection_requirement_type == "기타" else reselection_requirement_type,
                            "expected_receipt_date": str(root_expected_receipt_date) if root_expected_receipt_date else None,
                            "assembly_note": assembly_note,
                            "meta_requirement_id": int(selected_meta_id) if selected_meta_id else None,
                        },
                    }
                    saved_instruction = _save_instruction_safely(
                        selected_instruction_row,
                        payload=instruction_payload,
                        current_user_name=current_user()["user_name"],
                    )
                    if saved_instruction is None:
                        return
                    _, instruction_code, mb_request_code = saved_instruction
                    clear_instruction_return_state()
                    success_message = f"조립 실험지시를 저장했습니다. 코드: {instruction_code}"
                    if mb_request_code:
                        success_message += f" | MB의뢰 코드: {mb_request_code}"
                    flash_success(success_message)
                    st.rerun()
            return

        with left_col:
            render_section_title("요구요약")
            if selected_order_row is not None:
                if process_type == "사출" and requirement_checks:
                    req_color_c, req_mold_c, req_raw_c = st.columns(3)
                    with req_color_c:
                        with st.container(border=True):
                            st.caption("색상")
                            st.text_input("색상", value="요구" if order_detail.get("color_required") else "-", disabled=True, key=f"instruction_left_req_color_{selected_order_id}")
                            st.text_input("샘플 유무", value=order_detail.get("color_sample_exists", "-"), disabled=True, key=f"instruction_left_req_color_sample_{selected_order_id}")
                            st.text_input("뉴앙스", value=order_detail.get("color_nuance", "-"), disabled=True, key=f"instruction_left_req_color_nuance_{selected_order_id}")
                    with req_mold_c:
                        with st.container(border=True):
                            st.caption("금형")
                            st.text_input("금형수정", value="수정" if order_detail.get("mold_dispatch_required") else "-", disabled=True, key=f"instruction_left_req_mold_{selected_order_id}")
                            st.text_input("수정내용", value=order_detail.get("mold_update_type", "-"), disabled=True, key=f"instruction_left_req_mold_type_{selected_order_id}")
                            st.text_input("수정전달방식", value=order_detail.get("drawing_change_source", "-"), disabled=True, key=f"instruction_left_req_mold_source_{selected_order_id}")
                            if order_detail.get("mold_dispatch_required"):
                                st.text_input("출고의뢰", value="생성" if linked_mold_dispatch_row is not None else "미생성", disabled=True, key=f"instruction_left_mold_dispatch_{selected_order_id}")
                    with req_raw_c:
                        with st.container(border=True):
                            st.caption("원료")
                            st.text_input("원료체크", value="요구" if order_detail.get("raw_material_experiment_required") else "-", disabled=True, key=f"instruction_left_req_raw_{selected_order_id}")
                            st.text_input("원료명 1", value=order_detail.get("raw_material_1_label", "-"), disabled=True, key=f"instruction_left_req_raw1_{selected_order_id}")
                            st.text_input("원료명 2", value=order_detail.get("raw_material_2_label", "-"), disabled=True, key=f"instruction_left_req_raw2_{selected_order_id}")
                elif process_type in ("후가공", "인쇄", "사상"):
                    predecessor_links = [link for link in (order_detail.get("predecessor_links", []) or []) if isinstance(link, dict)]
                    predecessor_summary = "-"
                    if str(order_detail.get("execution_mode") or "") == "재고사용":
                        stock_sample_id = int(order_detail.get("stock_sample_id")) if order_detail.get("stock_sample_id") else None
                        stock_sample_code = str(order_detail.get("stock_sample_code") or "").strip()
                        source_sample_row = _find_sample_row_by_id(samples_df, stock_sample_id) if stock_sample_id else None
                        predecessor_summary = (
                            str(source_sample_row["sample_code"]).strip()
                            if source_sample_row is not None and str(source_sample_row["sample_code"]).strip()
                            else stock_sample_code or "-"
                        )
                    elif predecessor_links:
                        first_link = predecessor_links[0]
                        source_mode = str(first_link.get("source_mode") or "")
                        source_order_id = int(first_link.get("source_order_id")) if first_link.get("source_order_id") else None
                        source_sample_id = int(first_link.get("source_sample_id")) if first_link.get("source_sample_id") else None
                        if source_mode in ("기존실험요구", "실험요구") and source_order_id:
                            source_instruction_match = instructions_df[
                                pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == source_order_id
                            ].sort_values("experiment_instruction_id", ascending=False) if not instructions_df.empty else instructions_df
                            if not source_instruction_match.empty:
                                predecessor_summary = str(source_instruction_match.iloc[0]["instruction_code"] or "-")
                            else:
                                source_order_match = orders_df[pd.to_numeric(orders_df["experiment_order_id"], errors="coerce") == source_order_id] if not orders_df.empty else orders_df
                                if not source_order_match.empty:
                                    predecessor_summary = str(source_order_match.iloc[0]["order_code"] or "-")
                        elif source_mode == "재고품" and source_sample_id:
                            source_sample_row = _find_sample_row_by_id(samples_df, source_sample_id)
                            if source_sample_row is not None:
                                predecessor_summary = str(source_sample_row["sample_code"] or "-")
                    with st.container(border=True):
                        sum_c1, sum_c2 = st.columns(2)
                        with sum_c1:
                            st.caption("납기일")
                            st.write(str(selected_order_row["target_due_date"] or "-"))
                            st.caption("마일스톤")
                            st.write(str(selected_order_row["milestone_name"] or "-"))
                            st.caption("요구내용")
                            st.write(_build_requirement_content_summary(process_type, order_detail, selected_order_row))
                        with sum_c2:
                            st.caption("수량")
                            st.write(str(selected_order_total_required_qty or "-"))
                            st.caption("요구코드")
                            st.write(str(selected_order_row["order_code"] or "-"))
                            st.caption("전공정")
                            st.write(predecessor_summary)
                elif requirement_checks:
                    for check_name, check_value in _requirement_value_pairs(process_type, order_detail, requirement_checks):
                        st.text_input(check_name, value=check_value, disabled=True, key=f"instruction_left_req_{selected_order_id}_{check_name}")
                else:
                    st.caption("설정된 요구 항목이 없습니다.")
            else:
                st.caption("상단에서 고객요구 또는 실험지시를 선택하면 요구요약이 표시됩니다.")

        item_product_code = selected_item_row.get("product_code", "") if selected_item_row is not None else ""
        development_type_text = project_row.get("development_type", "-") if project_row is not None else "-"
        with right_col:
            render_section_title("지시입력")
            if project_row is not None:
                st.caption(f"상품코드: {item_product_code or '-'} / 개발형태: {development_type_text or '-'}")
            if selected_item_id:
                render_product_drawing_reference(selected_item_id)

            if selected_order_row is None:
                st.info("상단에서 트리, 모드, 고객요구/실험지시를 선택하면 입력카드가 열립니다.")

            if selected_order_row is not None:
                selected_instruction_detail = parse_json_text(selected_instruction_row["instruction_detail_json"]) if selected_instruction_row is not None else {}
                if selected_instruction_detail.get("inspection_plan"):
                    plan_version = int(selected_instruction_detail.get("plan_version") or 1)
                    plan_source = selected_instruction_detail.get("inspection_plan_source") or {}
                    plan_source_code = plan_source.get("order_code") or plan_source.get("instruction_code") or selected_order_row["order_code"]
                    st.caption(f"검사계획 v{plan_version} / 출처: {plan_source_code}")
                    if selected_instruction_detail.get("inspection_plan_changes"):
                        st.warning(f"현재 지시에서 요구 품질기준 {len(selected_instruction_detail['inspection_plan_changes'])}건을 조정했습니다.")
                measurement_instruction_titles = {
                    slot: str(
                        selected_instruction_detail.get(f"measurement_title_{slot}", "") or
                        order_detail.get(f"spec_location_{idx}", "") or
                        ""
                    ).strip()
                    for idx, slot in enumerate(["A", "B", "C"], start=1)
                }
                measurement_instruction_specs = {
                    slot: str(
                        selected_instruction_detail.get(f"measurement_spec_{slot}", "") or
                        order_detail.get(f"spec_value_{idx}", "") or
                        ""
                    ).strip()
                    for idx, slot in enumerate(["A", "B", "C"], start=1)
                }
                saved_raw_label = selected_instruction_detail.get("raw_material_label", "")
                saved_mold_id = int(selected_instruction_detail.get("mold_id")) if selected_instruction_detail.get("mold_id") else None
                saved_film_id = int(selected_instruction_detail.get("film_id")) if selected_instruction_detail.get("film_id") else None
                candidate_project_molds, mold_filter_note = _candidate_mold_options_for_item(
                    selected_item_row,
                    project_molds,
                    preferred_mold_id=saved_mold_id,
                )
                mold_option_map = dict(candidate_project_molds)
                film_option_map = dict(project_films)
                raw_option_map = dict(project_raw_materials)
                mold_labels = [""] + [label for label, _ in candidate_project_molds]
                film_labels = [""] + [label for label, _ in project_films]
                raw_labels = [""] + [label for label, _ in project_raw_materials]
                selected_mold_label = next((label for label, mold_id in mold_option_map.items() if mold_id == saved_mold_id), "")
                selected_film_label = next((label for label, film_id in film_option_map.items() if film_id == saved_film_id), "")
                selected_raw_label = saved_raw_label if saved_raw_label in raw_option_map else ""
                upstream_samples_df = samples_df[samples_df["project_code"] == project_code].copy() if project_code else samples_df.iloc[0:0]
                if selected_item_id and not upstream_samples_df.empty:
                    upstream_samples_df = upstream_samples_df[upstream_samples_df["item_id"] != int(selected_item_id)]
                upstream_sample_options = (
                    [
                        (_upstream_sample_pick_label(row), int(row["sample_id"]))
                        for _, row in upstream_samples_df.sort_values("sample_id", ascending=False).iterrows()
                    ]
                    if not upstream_samples_df.empty else []
                )
                selected_upstream_sample_id = (
                    int(selected_instruction_detail.get("upstream_sample_id"))
                    if selected_instruction_detail.get("upstream_sample_id") else None
                )
                selected_upstream_sample_label = (
                    next((label for label, sid in upstream_sample_options if sid == selected_upstream_sample_id), "")
                    if selected_upstream_sample_id else ""
                )
                instruction_widget_suffix = str(int(selected_instruction_row["experiment_instruction_id"])) if selected_instruction_row is not None and pd.notna(selected_instruction_row["experiment_instruction_id"]) else "new"

                detail_payload = {}

                if process_type == "사출":
                    render_section_title("사출 지시")
                    code_c1, code_c2 = st.columns(2)
                    with code_c1:
                        st.text_input(
                            "실험지시 코드",
                            value=str(selected_instruction_row["instruction_code"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["instruction_code"]) else "-",
                            disabled=True,
                            key=f"instruction_code_display_{selected_order_id}_{instruction_widget_suffix}",
                        )
                    with code_c2:
                        st.text_input(
                            "MB의뢰 코드",
                            value=str(linked_mb_request_row["request_code"]) if linked_mb_request_row is not None and pd.notna(linked_mb_request_row["request_code"]) else "-",
                            disabled=True,
                            key=f"instruction_mb_request_code_display_{selected_order_id}_{instruction_widget_suffix}",
                        )
                    mode_c3, mode_c4 = st.columns([1.1, 0.9])
                    with mode_c3:
                        mold_label = st.selectbox(
                            "금형선택",
                            options=mold_labels,
                            index=mold_labels.index(selected_mold_label) if selected_mold_label in mold_labels else 0,
                            key=f"instruction_mold_label_{selected_order_id}_{instruction_widget_suffix}",
                        )
                    with mode_c4:
                        st.text_input("자동 샘플순번", value=str(sample_seq), disabled=True)
                    if mold_filter_note:
                        st.caption(mold_filter_note)
                    film_label = ""

                    if order_detail.get("color_required"):
                        render_section_title("색상 조합")
                        color_c1, color_c2, color_c3 = st.columns([1, 1, 1.1])
                        ratio_plan_rows = selected_instruction_detail.get("mb_ratio_plan_rows", [])
                        if not ratio_plan_rows:
                            default_sample_label = str(selected_row["sample_name"]) if selected_row is not None and pd.notna(selected_row["sample_name"]) else "1안"
                            ratio_plan_rows = [{"label": default_sample_label, "ratio": selected_instruction_detail.get("mb_ratio", 0.0)}]
                        mb_nuance = color_instruction.strip()
                        mb_supplier_name = color_vendor_name.strip()
                        mb_expected_receipt_date = color_due_date
                        mb_sample_received = bool(color_sample_checked)
                        render_section_title("샘플 농도 구분")
                        ratio_plan_values = []
                        ratio_cols = st.columns(4)
                        current_sample_label = str(selected_row["sample_name"]) if selected_row is not None and pd.notna(selected_row["sample_name"]) else ""
                        for idx in range(1, 5):
                            default_row = ratio_plan_rows[idx - 1] if idx - 1 < len(ratio_plan_rows) else {}
                            default_ratio = float(default_row.get("ratio", 0.0))
                            if current_sample_label == f"{idx}안" and selected_instruction_detail.get("mb_ratio") is not None:
                                default_ratio = float(selected_instruction_detail.get("mb_ratio", default_ratio))
                            with ratio_cols[idx - 1]:
                                ratio_value = st.number_input(
                                    f"{idx}안(%)",
                                    min_value=0.0,
                                    step=0.1,
                                    value=default_ratio,
                                    key=f"mb_ratio_value_{selected_order_id}_{idx}",
                                )
                            ratio_plan_values.append({"label": f"{idx}안", "ratio": ratio_value})
                        valid_ratio_rows = [row for row in ratio_plan_values if float(row.get("ratio", 0.0)) > 0]
                        if selected_row is None:
                            st.caption("입력한 농도 수만큼 샘플이 자동 생성됩니다.")
                        if selected_row is not None:
                            selected_ratio_label = current_sample_label if current_sample_label in {f"{idx}안" for idx in range(1, 5)} else (valid_ratio_rows[0]["label"] if valid_ratio_rows else "1안")
                            selected_ratio_row = next((row for row in ratio_plan_values if row["label"] == selected_ratio_label), ratio_plan_values[0])
                        else:
                            selected_ratio_row = valid_ratio_rows[0] if valid_ratio_rows else {"label": "1안", "ratio": 0.0}
                        mb_ratio = float(selected_ratio_row.get("ratio", 0.0))
                        if selected_row is None and valid_ratio_rows:
                            sample_name = str(valid_ratio_rows[0]["label"])
                    else:
                        mb_nuance = ""
                        mb_ratio = 0.0
                        mb_supplier_name = ""
                        mb_expected_receipt_date = None
                        mb_sample_received = False
                        ratio_plan_values = []
                        valid_ratio_rows = []

                    render_section_title("원료")
                    raw_c1, raw_c2 = st.columns([1, 1.2])
                    with raw_c1:
                        raw_material_label = st.selectbox("원료", options=raw_labels, index=raw_labels.index(selected_raw_label) if selected_raw_label in raw_labels else 0)
                    with raw_c2:
                        st.text_input("선택 조합", value=f"{mold_label or '-'} / {raw_material_label or '-'} / {mb_nuance or '-'} / {mb_ratio:.1f}%", disabled=True)
                    if not mold_label or not raw_material_label:
                        st.caption("사출은 금형, 원료가 필수입니다.")

                    render_section_title("측정부위 / 도면규격")
                    measurement_rows = []
                    for idx, slot in enumerate(["A", "B", "C"], start=1):
                        mc1, mc2 = st.columns([1, 1])
                        with mc1:
                            measurement_title = st.text_input(
                                f"{slot} 측정부위",
                                value=measurement_instruction_titles[slot],
                                key=f"instruction_measurement_title_{selected_order_id}_{slot}",
                            )
                        with mc2:
                            measurement_spec = st.text_input(
                                f"{slot} 도면규격",
                                value=measurement_instruction_specs[slot],
                                key=f"instruction_measurement_spec_{selected_order_id}_{slot}",
                            )
                        measurement_rows.append((slot, measurement_title, measurement_spec))
                    for slot, measurement_title, measurement_spec in measurement_rows:
                        measurement_instruction_titles[slot] = measurement_title.strip()
                        measurement_instruction_specs[slot] = measurement_spec.strip()

                    if order_detail.get("mold_dispatch_required"):
                        render_section_title("금형 수정 / 출고 확정")
                        mold_c1, mold_c2 = st.columns([1, 1.2])
                        with mold_c1:
                            st.text_input("금형 출고지시", value=linked_mold_dispatch_row["dispatch_code"] if linked_mold_dispatch_row is not None else "", disabled=True)
                        with mold_c2:
                            mold_dispatch_note = st.text_area("수정 요청 확정 내용", height=88, value=selected_instruction_detail.get("mold_dispatch_note", linked_mold_dispatch_row["dispatch_reason"] if linked_mold_dispatch_row is not None and pd.notna(linked_mold_dispatch_row["dispatch_reason"]) else order_detail.get("mold_update_detail", "")))
                            mold_sample_request_date = st.date_input(
                                "사출샘플 입고요청일",
                                value=_safe_date_value(selected_instruction_detail.get("mold_sample_request_date") or (linked_mold_dispatch_row["sample_request_date"] if linked_mold_dispatch_row is not None and linked_mold_dispatch_row["sample_request_date"] else None))
                                if (selected_instruction_detail.get("mold_sample_request_date") or (linked_mold_dispatch_row is not None and linked_mold_dispatch_row["sample_request_date"])) else None,
                            )
                    else:
                        mold_dispatch_note = ""
                        mold_sample_request_date = None

                    instruction_drawing_receipt_status = selected_order_row["drawing_receipt_status"] if selected_order_row["drawing_receipt_status"] in DRAWING_RECEIPT_STATUS_OPTIONS else DRAWING_RECEIPT_STATUS_OPTIONS[0]
                    instruction_base_drawing_revision = selected_order_row["base_drawing_revision"] or ""
                    drawing_change_source = order_detail.get("drawing_change_source", "도면" if order_detail.get("product_drawing_change_required") else "구두/이미지")
                    drawing_receipt_note = selected_instruction_detail.get("drawing_receipt_note", "")
                    if order_detail.get("product_drawing_change_required"):
                        render_section_title("제품도 변경 / 입수 확인")
                        drawing_c1, drawing_c2 = st.columns(2)
                        with drawing_c1:
                            instruction_base_drawing_revision = st.text_input("기준 제품도면 리비전", value=selected_instruction_detail.get("base_drawing_revision", instruction_base_drawing_revision))
                        with drawing_c2:
                            default_receipt_status = selected_instruction_detail.get("drawing_receipt_status", instruction_drawing_receipt_status)
                            instruction_drawing_receipt_status = st.selectbox(
                                "제품도 입수상태",
                                options=DRAWING_RECEIPT_STATUS_OPTIONS,
                                index=DRAWING_RECEIPT_STATUS_OPTIONS.index(default_receipt_status) if default_receipt_status in DRAWING_RECEIPT_STATUS_OPTIONS else 0,
                            )
                    elif order_detail.get("mold_dispatch_required"):
                        render_section_title("전달자료 확인")
                        drawing_c1, drawing_c2 = st.columns(2)
                        with drawing_c1:
                            st.text_input("전달방식", value="구두/이미지", disabled=True)
                        with drawing_c2:
                            drawing_receipt_note = st.text_input("구두/이미지 확인", value=drawing_receipt_note)
                    detail_payload.update(
                        {
                            "base_drawing_revision": instruction_base_drawing_revision,
                            "drawing_receipt_status": instruction_drawing_receipt_status,
                            "drawing_change_source": drawing_change_source,
                            "drawing_receipt_note": drawing_receipt_note if not order_detail.get("product_drawing_change_required") else "",
                            "mb_ratio": mb_ratio,
                            "mb_ratio_plan_rows": ratio_plan_values if order_detail.get("color_required") else [],
                            "measurement_title_A": measurement_instruction_titles["A"],
                            "measurement_title_B": measurement_instruction_titles["B"],
                            "measurement_title_C": measurement_instruction_titles["C"],
                            "measurement_spec_A": measurement_instruction_specs["A"],
                            "measurement_spec_B": measurement_instruction_specs["B"],
                            "measurement_spec_C": measurement_instruction_specs["C"],
                        }
                    )

                    if order_detail.get("other_request"):
                        st.text_area("기타 요구", value=order_detail.get("other_request", ""), height=70, disabled=True)
                    detail_payload.update(
                        {
                            "mold_id": mold_option_map.get(mold_label) if mold_label else None,
                            "mold_code": (mold_label.split(" | ")[0].strip() if mold_label else ""),
                            "raw_material_id": dict(project_raw_materials).get(raw_material_label),
                            "raw_material_label": raw_material_label,
                            "mb_request_id": int(linked_mb_request_row["mb_request_id"]) if linked_mb_request_row is not None else None,
                            "mb_supplier_name": mb_supplier_name if order_detail.get("color_required") else "",
                            "mb_nuance": mb_nuance if order_detail.get("color_required") else "",
                            "mb_expected_receipt_date": str(mb_expected_receipt_date) if mb_expected_receipt_date and order_detail.get("color_required") else None,
                            "mb_sample_received": mb_sample_received if order_detail.get("color_required") else False,
                            "color_sample_exists": order_detail.get("color_sample_exists", "없음"),
                            "mold_dispatch_id": int(linked_mold_dispatch_row["mold_dispatch_order_id"]) if linked_mold_dispatch_row is not None else None,
                            "mold_dispatch_note": mold_dispatch_note,
                            "mold_sample_request_date": str(mold_sample_request_date) if mold_sample_request_date else None,
                        }
                    )
                elif process_type == "인쇄":
                    render_section_title("인쇄 지시")
                    execution_mode_options = ["내부", "외부"]
                    execution_mode = _execution_mode_ui_value(selected_instruction_detail.get("execution_mode", "내부"))
                    predecessor_links = [link for link in (order_detail.get("predecessor_links", []) or []) if isinstance(link, dict)]
                    preferred_link = predecessor_links[0] if predecessor_links else {}
                    preferred_source_mode = str(selected_instruction_detail.get("upstream_source_mode") or "")
                    if not preferred_source_mode:
                        if str(order_detail.get("execution_mode") or "") == "재고사용" and order_detail.get("stock_sample_id"):
                            preferred_source_mode = "재고품"
                        else:
                            preferred_source_mode = str(preferred_link.get("source_mode") or "")
                    if preferred_source_mode == "실험요구":
                        preferred_source_mode = "기존실험요구"
                    preferred_order_id = (
                        int(selected_instruction_detail.get("upstream_order_id"))
                        if selected_instruction_detail.get("upstream_order_id")
                        else int(preferred_link.get("source_order_id"))
                        if preferred_link.get("source_order_id")
                        else None
                    )
                    preferred_sample_id = (
                        int(selected_instruction_detail.get("upstream_sample_id"))
                        if selected_instruction_detail.get("upstream_sample_id")
                        else int(preferred_link.get("source_sample_id"))
                        if preferred_link.get("source_sample_id")
                        else int(order_detail.get("stock_sample_id"))
                        if order_detail.get("stock_sample_id")
                        else None
                    )
                    predecessor_item_ids = [int(link.get("item_id")) for link in predecessor_links if link.get("item_id")]
                    predecessor_order_ids = [
                        int(link.get("source_order_id"))
                        for link in predecessor_links
                        if str(link.get("source_mode") or "") in ("기존실험요구", "실험요구") and link.get("source_order_id")
                    ]
                    upstream_instruction_df = instructions_df[instructions_df["project_code"] == project_code].copy() if project_code else instructions_df.iloc[0:0]
                    if predecessor_item_ids and not upstream_instruction_df.empty:
                        upstream_instruction_df = upstream_instruction_df[upstream_instruction_df["item_id"].isin(predecessor_item_ids)]
                    if predecessor_order_ids and not upstream_instruction_df.empty:
                        upstream_instruction_df = upstream_instruction_df[
                            pd.to_numeric(upstream_instruction_df["experiment_order_id"], errors="coerce").isin(predecessor_order_ids)
                        ]
                    default_upstream_instruction_row = None
                    if preferred_order_id and not upstream_instruction_df.empty:
                        upstream_instruction_match = upstream_instruction_df[
                            pd.to_numeric(upstream_instruction_df["experiment_order_id"], errors="coerce") == int(preferred_order_id)
                        ].sort_values("experiment_instruction_id", ascending=False)
                        if not upstream_instruction_match.empty:
                            default_upstream_instruction_row = upstream_instruction_match.iloc[0]
                    default_upstream_instruction_id = (
                        int(selected_instruction_detail.get("upstream_instruction_id"))
                        if selected_instruction_detail.get("upstream_instruction_id")
                        else int(default_upstream_instruction_row["experiment_instruction_id"])
                        if default_upstream_instruction_row is not None
                        else None
                    )
                    upstream_instruction_options = (
                        [(_upstream_instruction_pick_label(row), int(row["experiment_instruction_id"])) for _, row in upstream_instruction_df.iterrows()]
                        if not upstream_instruction_df.empty else []
                    )
                    common_c1, common_c2, common_c3 = st.columns([0.9, 1.4, 1.0])
                    with common_c1:
                        execution_mode = st.selectbox("실행방식", options=execution_mode_options, index=execution_mode_options.index(execution_mode), key=f"print_execution_mode_{selected_order_id}_{instruction_widget_suffix}")
                    execution_mode_value = _execution_mode_storage_value(execution_mode)
                    with common_c2:
                        selected_upstream_instruction_id = None
                        selected_upstream_instruction_code = ""
                        if preferred_source_mode == "기존실험요구":
                            st.caption("요구 기준 전공정: 실험")
                            upstream_instruction_label = st.selectbox(
                                "전공정 지시",
                                options=[""] + [label for label, _ in upstream_instruction_options],
                                index=(
                                    1 + [iid for _, iid in upstream_instruction_options].index(int(default_upstream_instruction_id))
                                    if default_upstream_instruction_id and any(iid == int(default_upstream_instruction_id) for _, iid in upstream_instruction_options)
                                    else 0
                                ) if upstream_instruction_options else 0,
                                key=f"print_upstream_instruction_{selected_order_id}_{instruction_widget_suffix}",
                            )
                            selected_upstream_instruction_id = dict(upstream_instruction_options).get(upstream_instruction_label) if upstream_instruction_label else None
                            selected_instruction_source_row = (
                                upstream_instruction_df[upstream_instruction_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].iloc[0]
                                if selected_upstream_instruction_id and not upstream_instruction_df.empty and not upstream_instruction_df[upstream_instruction_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].empty
                                else None
                            )
                            selected_upstream_instruction_code = str(selected_instruction_source_row["instruction_code"]) if selected_instruction_source_row is not None else ""
                            linked_upstream_sample_row = (
                                samples_df[samples_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].sort_values("sample_id", ascending=False).iloc[0]
                                if selected_upstream_instruction_id and not samples_df.empty and not samples_df[samples_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].empty
                                else None
                            )
                            selected_upstream_sample_id = int(linked_upstream_sample_row["sample_id"]) if linked_upstream_sample_row is not None else None
                            selected_upstream_sample_code = str(linked_upstream_sample_row["sample_code"]) if linked_upstream_sample_row is not None else selected_upstream_instruction_code
                            if not upstream_instruction_options:
                                st.warning("이 메타 요구에 연결된 전공정 실험지시가 없습니다. 먼저 해당 전공정 지시를 생성한 뒤 인쇄 지시를 저장해 주세요.")
                        else:
                            st.caption("요구 기준 전공정: 재고사용" if preferred_source_mode == "재고품" else "전공정 샘플")
                            upstream_sample_label = st.selectbox(
                                "전공정 샘플",
                                options=[""] + [label for label, _ in upstream_sample_options],
                                index=(1 + [sid for _, sid in upstream_sample_options].index(int(preferred_sample_id)) if preferred_sample_id and any(sid == int(preferred_sample_id) for _, sid in upstream_sample_options) else 0),
                                key=f"print_upstream_sample_{selected_order_id}_{instruction_widget_suffix}",
                            )
                            selected_upstream_sample_id = dict(upstream_sample_options).get(upstream_sample_label) if upstream_sample_label else None
                            selected_upstream_sample_row = _find_sample_row_by_id(upstream_samples_df, int(selected_upstream_sample_id)) if selected_upstream_sample_id else None
                            selected_upstream_sample_code = str(selected_upstream_sample_row["sample_code"]) if selected_upstream_sample_row is not None else ""
                            selected_upstream_instruction_id = None
                            selected_upstream_instruction_code = ""
                    with common_c3:
                        film_label = st.selectbox("원화", options=film_labels, index=film_labels.index(selected_film_label) if selected_film_label in film_labels else 0, key=f"print_film_{selected_order_id}_{instruction_widget_suffix}")
                    expected_receipt_date = st.date_input("완료요청일", value=_safe_date_value(selected_instruction_detail.get("expected_receipt_date")) if selected_instruction_detail.get("expected_receipt_date") else None, key=f"print_expected_date_{selected_order_id}_{instruction_widget_suffix}")
                    vendor_name = st.text_input(
                        "업체",
                        value=str(selected_instruction_detail.get("vendor_name") or ("내부" if execution_mode_value == "내부" else "")),
                        disabled=execution_mode_value == "내부",
                        key=f"print_vendor_name_{selected_order_id}_{instruction_widget_suffix}",
                    )
                    reselection_requirement_type = selected_instruction_detail.get("reselection_requirement_type", selected_instruction_detail.get("reselection_requirement", "없음"))
                    reselection_requirement_type = st.selectbox("업체 재선정", options=VENDOR_RESELECTION_OPTIONS, index=_select_index(VENDOR_RESELECTION_OPTIONS, reselection_requirement_type), key=f"print_vendor_reselection_{selected_order_id}_{instruction_widget_suffix}")
                    reselection_requirement = st.text_input("업체 재선정 기타", value=selected_instruction_detail.get("reselection_requirement_extra", ""), disabled=reselection_requirement_type != "기타", key=f"print_vendor_reselection_extra_{selected_order_id}_{instruction_widget_suffix}")
                    if order_detail.get("film_revision_required"):
                        st.checkbox("원화 수정 필요", value=True, disabled=True)
                    if order_detail.get("color_required") or order_detail.get("print_position") or order_detail.get("print_tolerance_deg"):
                        render_section_title("인쇄 요구 반영")
                        req_c1, req_c2, req_c3 = st.columns(3)
                        with req_c1:
                            st.text_input("색상샘플", value=order_detail.get("color_sample_exists", "없음"), disabled=True)
                            st.text_input("요구 뉴앙스", value=order_detail.get("color_nuance", ""), disabled=True)
                        with req_c2:
                            color_nuance = st.text_input("지시 확정 뉴앙스", value=selected_instruction_detail.get("color_nuance", order_detail.get("color_nuance", "")), key=f"print_color_nuance_{selected_order_id}_{instruction_widget_suffix}")
                            st.text_input("기준 위치", value=order_detail.get("print_position", ""), disabled=True)
                        with req_c3:
                            tolerance_text = f"+- {order_detail.get('print_tolerance_deg')}도" if order_detail.get("print_tolerance_deg") else "-"
                            st.text_input("허용오차", value=tolerance_text, disabled=True)
                            print_position_note = st.text_input("위치 확인 메모", value=selected_instruction_detail.get("print_position_note", ""), key=f"print_position_note_{selected_order_id}_{instruction_widget_suffix}")
                    else:
                        color_nuance = selected_instruction_detail.get("color_nuance", "")
                        print_position_note = ""
                    mold_label = ""
                    if order_detail.get("other_request"):
                        st.text_area("기타 요구", value=order_detail.get("other_request", ""), height=70, disabled=True)
                    detail_payload.update(
                        {
                            "execution_mode": execution_mode_value,
                            "upstream_source_mode": preferred_source_mode or ("기존실험요구" if selected_upstream_instruction_id else "재고품" if selected_upstream_sample_id else ""),
                            "upstream_order_id": int(preferred_order_id) if preferred_order_id else None,
                            "upstream_instruction_id": int(selected_upstream_instruction_id) if selected_upstream_instruction_id else None,
                            "upstream_instruction_code": selected_upstream_instruction_code,
                            "upstream_sample_id": int(selected_upstream_sample_id) if selected_upstream_sample_id else None,
                            "upstream_sample_code": selected_upstream_sample_code,
                            "color_sample_exists": order_detail.get("color_sample_exists", "없음"),
                            "color_nuance": color_nuance,
                            "vendor_name": "내부" if execution_mode_value == "내부" else vendor_name.strip(),
                            "reselection_requirement_type": reselection_requirement_type,
                            "reselection_requirement_extra": reselection_requirement,
                            "reselection_requirement": reselection_requirement if reselection_requirement_type == "기타" else reselection_requirement_type,
                            "expected_receipt_date": str(expected_receipt_date) if expected_receipt_date else None,
                            "print_position_note": print_position_note,
                            "film_id": int(film_option_map.get(film_label)) if film_label else None,
                            "film_code": str(film_label.split(" | ")[0]) if film_label else "",
                        }
                    )
                    if preferred_source_mode == "기존실험요구" and not selected_upstream_instruction_id:
                        st.caption("전공정 실험지시를 먼저 선택해야 저장할 수 있습니다.")
                    if not film_label:
                        st.caption("인쇄는 원화가 필수입니다.")
                elif process_type in ("후가공", "사상"):
                    render_section_title(f"{process_type} 지시")
                    execution_mode_options = ["내부", "외부"]
                    execution_mode = _execution_mode_ui_value(selected_instruction_detail.get("execution_mode", "내부"))
                    predecessor_links = [link for link in (order_detail.get("predecessor_links", []) or []) if isinstance(link, dict)]
                    preferred_link = predecessor_links[0] if predecessor_links else {}
                    preferred_source_mode = str(selected_instruction_detail.get("upstream_source_mode") or "")
                    if not preferred_source_mode:
                        if str(order_detail.get("execution_mode") or "") == "재고사용" and order_detail.get("stock_sample_id"):
                            preferred_source_mode = "재고품"
                        else:
                            preferred_source_mode = str(preferred_link.get("source_mode") or "")
                    if preferred_source_mode == "실험요구":
                        preferred_source_mode = "기존실험요구"
                    preferred_order_id = (
                        int(selected_instruction_detail.get("upstream_order_id"))
                        if selected_instruction_detail.get("upstream_order_id")
                        else int(preferred_link.get("source_order_id"))
                        if preferred_link.get("source_order_id")
                        else None
                    )
                    preferred_sample_id = (
                        int(selected_instruction_detail.get("upstream_sample_id"))
                        if selected_instruction_detail.get("upstream_sample_id")
                        else int(preferred_link.get("source_sample_id"))
                        if preferred_link.get("source_sample_id")
                        else int(order_detail.get("stock_sample_id"))
                        if order_detail.get("stock_sample_id")
                        else None
                    )
                    predecessor_item_ids = [int(link.get("item_id")) for link in predecessor_links if link.get("item_id")]
                    predecessor_order_ids = [
                        int(link.get("source_order_id"))
                        for link in predecessor_links
                        if str(link.get("source_mode") or "") in ("기존실험요구", "실험요구") and link.get("source_order_id")
                    ]
                    upstream_instruction_df = instructions_df[instructions_df["project_code"] == project_code].copy() if project_code else instructions_df.iloc[0:0]
                    if predecessor_item_ids and not upstream_instruction_df.empty:
                        upstream_instruction_df = upstream_instruction_df[upstream_instruction_df["item_id"].isin(predecessor_item_ids)]
                    if predecessor_order_ids and not upstream_instruction_df.empty:
                        upstream_instruction_df = upstream_instruction_df[
                            pd.to_numeric(upstream_instruction_df["experiment_order_id"], errors="coerce").isin(predecessor_order_ids)
                        ]
                    default_upstream_instruction_row = None
                    if preferred_order_id and not upstream_instruction_df.empty:
                        upstream_instruction_match = upstream_instruction_df[
                            pd.to_numeric(upstream_instruction_df["experiment_order_id"], errors="coerce") == int(preferred_order_id)
                        ].sort_values("experiment_instruction_id", ascending=False)
                        if not upstream_instruction_match.empty:
                            default_upstream_instruction_row = upstream_instruction_match.iloc[0]
                    default_upstream_instruction_id = (
                        int(selected_instruction_detail.get("upstream_instruction_id"))
                        if selected_instruction_detail.get("upstream_instruction_id")
                        else int(default_upstream_instruction_row["experiment_instruction_id"])
                        if default_upstream_instruction_row is not None
                        else None
                    )
                    upstream_instruction_options = (
                        [(_upstream_instruction_pick_label(row), int(row["experiment_instruction_id"])) for _, row in upstream_instruction_df.iterrows()]
                        if not upstream_instruction_df.empty else []
                    )
                    post_c1, post_c2, post_c3 = st.columns([0.9, 1.4, 1.0])
                    with post_c1:
                        execution_mode = st.selectbox("실행방식", options=execution_mode_options, index=execution_mode_options.index(execution_mode), key=f"post_execution_mode_{selected_order_id}_{instruction_widget_suffix}")
                    execution_mode_value = _execution_mode_storage_value(execution_mode)
                    with post_c2:
                        selected_upstream_instruction_id = None
                        selected_upstream_instruction_code = ""
                        if preferred_source_mode == "기존실험요구":
                            st.caption("요구 기준 전공정: 실험")
                            upstream_instruction_label = st.selectbox(
                                "전공정 지시",
                                options=[""] + [label for label, _ in upstream_instruction_options],
                                index=(
                                    1 + [iid for _, iid in upstream_instruction_options].index(int(default_upstream_instruction_id))
                                    if default_upstream_instruction_id and any(iid == int(default_upstream_instruction_id) for _, iid in upstream_instruction_options)
                                    else 0
                                ) if upstream_instruction_options else 0,
                                key=f"post_upstream_instruction_{selected_order_id}_{instruction_widget_suffix}",
                            )
                            selected_upstream_instruction_id = dict(upstream_instruction_options).get(upstream_instruction_label) if upstream_instruction_label else None
                            selected_instruction_source_row = (
                                upstream_instruction_df[upstream_instruction_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].iloc[0]
                                if selected_upstream_instruction_id and not upstream_instruction_df.empty and not upstream_instruction_df[upstream_instruction_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].empty
                                else None
                            )
                            selected_upstream_instruction_code = str(selected_instruction_source_row["instruction_code"]) if selected_instruction_source_row is not None else ""
                            linked_upstream_sample_row = (
                                samples_df[samples_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].sort_values("sample_id", ascending=False).iloc[0]
                                if selected_upstream_instruction_id and not samples_df.empty and not samples_df[samples_df["experiment_instruction_id"] == int(selected_upstream_instruction_id)].empty
                                else None
                            )
                            selected_upstream_sample_id = int(linked_upstream_sample_row["sample_id"]) if linked_upstream_sample_row is not None else None
                            selected_upstream_sample_code = str(linked_upstream_sample_row["sample_code"]) if linked_upstream_sample_row is not None else selected_upstream_instruction_code
                            if not upstream_instruction_options:
                                st.warning(f"이 메타 요구에 연결된 전공정 실험지시가 없습니다. 먼저 해당 전공정 지시를 생성한 뒤 {process_type} 지시를 저장해 주세요.")
                        else:
                            st.caption("요구 기준 전공정: 재고사용" if preferred_source_mode == "재고품" else "전공정 샘플")
                            upstream_sample_label = st.selectbox(
                                "전공정 샘플",
                                options=[""] + [label for label, _ in upstream_sample_options],
                                index=(1 + [sid for _, sid in upstream_sample_options].index(int(preferred_sample_id)) if preferred_sample_id and any(sid == int(preferred_sample_id) for _, sid in upstream_sample_options) else 0),
                                key=f"post_upstream_sample_{selected_order_id}_{instruction_widget_suffix}",
                            )
                            selected_upstream_sample_id = dict(upstream_sample_options).get(upstream_sample_label) if upstream_sample_label else None
                            selected_upstream_sample_row = _find_sample_row_by_id(upstream_samples_df, int(selected_upstream_sample_id)) if selected_upstream_sample_id else None
                            selected_upstream_sample_code = str(selected_upstream_sample_row["sample_code"]) if selected_upstream_sample_row is not None else ""
                            selected_upstream_instruction_id = None
                            selected_upstream_instruction_code = ""
                    with post_c3:
                        expected_receipt_date = st.date_input("완료요청일", value=_safe_date_value(selected_instruction_detail.get("expected_receipt_date")) if selected_instruction_detail.get("expected_receipt_date") else None, key=f"post_expected_date_{selected_order_id}_{instruction_widget_suffix}")
                    vendor_name = st.text_input(
                        "업체",
                        value=str(selected_instruction_detail.get("vendor_name") or ("내부" if execution_mode_value == "내부" else "")),
                        disabled=execution_mode_value == "내부",
                        key=f"post_vendor_name_{selected_order_id}_{instruction_widget_suffix}",
                    )
                    reselection_requirement_type = selected_instruction_detail.get("reselection_requirement_type", selected_instruction_detail.get("reselection_requirement", "없음"))
                    reselection_requirement_type = st.selectbox("업체 재선정", options=VENDOR_RESELECTION_OPTIONS, index=_select_index(VENDOR_RESELECTION_OPTIONS, reselection_requirement_type), key=f"post_vendor_reselection_{selected_order_id}_{instruction_widget_suffix}")
                    reselection_requirement = st.text_input("업체 재선정 기타", value=selected_instruction_detail.get("reselection_requirement_extra", ""), disabled=reselection_requirement_type != "기타", key=f"post_vendor_reselection_extra_{selected_order_id}_{instruction_widget_suffix}")
                    if order_detail.get("color_required") or order_detail.get("masking_position"):
                        render_section_title(f"{process_type} 요구 반영")
                        req_c1, req_c2, req_c3 = st.columns(3)
                        with req_c1:
                            st.text_input("색상샘플", value=order_detail.get("color_sample_exists", "없음"), disabled=True)
                        with req_c2:
                            color_nuance = st.text_input("지시 확정 뉴앙스", value=selected_instruction_detail.get("color_nuance", order_detail.get("color_nuance", "")), key=f"post_color_nuance_{selected_order_id}_{instruction_widget_suffix}")
                        with req_c3:
                            masking_position_note = st.text_input("마스킹 위치 확인", value=selected_instruction_detail.get("masking_position_note", order_detail.get("masking_position", "")), key=f"post_masking_position_note_{selected_order_id}_{instruction_widget_suffix}")
                    else:
                        color_nuance = selected_instruction_detail.get("color_nuance", "")
                        masking_position_note = ""
                    mold_label = ""
                    film_label = ""
                    if order_detail.get("other_request"):
                        st.text_area("기타 요구", value=order_detail.get("other_request", ""), height=70, disabled=True)
                    detail_payload.update(
                        {
                            "execution_mode": execution_mode_value,
                            "upstream_source_mode": preferred_source_mode or ("기존실험요구" if selected_upstream_instruction_id else "재고품" if selected_upstream_sample_id else ""),
                            "upstream_order_id": int(preferred_order_id) if preferred_order_id else None,
                            "upstream_instruction_id": int(selected_upstream_instruction_id) if selected_upstream_instruction_id else None,
                            "upstream_instruction_code": selected_upstream_instruction_code,
                            "upstream_sample_id": int(selected_upstream_sample_id) if selected_upstream_sample_id else None,
                            "upstream_sample_code": selected_upstream_sample_code,
                            "color_sample_exists": order_detail.get("color_sample_exists", "없음"),
                            "color_nuance": color_nuance,
                            "vendor_name": "내부" if execution_mode_value == "내부" else vendor_name.strip(),
                            "reselection_requirement_type": reselection_requirement_type,
                            "reselection_requirement_extra": reselection_requirement,
                            "reselection_requirement": reselection_requirement if reselection_requirement_type == "기타" else reselection_requirement_type,
                            "expected_receipt_date": str(expected_receipt_date) if expected_receipt_date else None,
                            "masking_position_note": masking_position_note,
                        }
                    )
                    if preferred_source_mode == "기존실험요구" and not selected_upstream_instruction_id:
                        st.caption("전공정 실험지시를 먼저 선택해야 저장할 수 있습니다.")
                else:
                    render_section_title("조립 지시")
                    assy_c1, assy_c2 = st.columns(2)
                    with assy_c1:
                        vendor_name = st.text_input("업체", value=selected_instruction_detail.get("vendor_name", ""))
                    with assy_c2:
                        expected_receipt_date = st.date_input("입고일", value=_safe_date_value(selected_instruction_detail.get("expected_receipt_date")) if selected_instruction_detail.get("expected_receipt_date") else None)
                    reselection_requirement_type = selected_instruction_detail.get("reselection_requirement_type", selected_instruction_detail.get("reselection_requirement", "없음"))
                    reselection_requirement_type = st.selectbox("업체 재선정", options=VENDOR_RESELECTION_OPTIONS, index=_select_index(VENDOR_RESELECTION_OPTIONS, reselection_requirement_type), key=f"assy_vendor_reselection_{selected_order_id}")
                    reselection_requirement = st.text_input("업체 재선정 기타", value=selected_instruction_detail.get("reselection_requirement_extra", ""), disabled=reselection_requirement_type != "기타", key=f"assy_vendor_reselection_extra_{selected_order_id}")
                    if order_detail.get("assembly_function") or order_detail.get("backing_spec") or order_detail.get("sub_material_other"):
                        render_section_title("조립 요구 반영")
                        req_c1, req_c2 = st.columns(2)
                        with req_c1:
                            st.text_area("기능 요구", value=order_detail.get("assembly_function", ""), height=80, disabled=True)
                            st.text_input("바킹 규격", value=order_detail.get("backing_spec", ""), disabled=True)
                        with req_c2:
                            st.text_area("부재료 기타", value=order_detail.get("sub_material_other", ""), height=80, disabled=True)
                            assembly_note = st.text_area("지시 확인 메모", height=80, value=selected_instruction_detail.get("assembly_note", ""))
                    else:
                        assembly_note = ""
                    mold_label = ""
                    film_label = ""
                    color_nuance = ""
                    if order_detail.get("other_request"):
                        st.text_area("기타 요구", value=order_detail.get("other_request", ""), height=70, disabled=True)
                    detail_payload.update(
                        {
                            "vendor_name": vendor_name,
                            "reselection_requirement_type": reselection_requirement_type,
                            "reselection_requirement_extra": reselection_requirement,
                            "reselection_requirement": reselection_requirement if reselection_requirement_type == "기타" else reselection_requirement_type,
                            "expected_receipt_date": str(expected_receipt_date) if expected_receipt_date else None,
                            "assembly_note": assembly_note,
                        }
                    )

                requirement_completed = st.checkbox(
                    "요구완료",
                    value=bool(selected_instruction_row["requirement_completed"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["requirement_completed"]) else False,
                    key=f"general_instruction_requirement_completed_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
                )
                action_defs = [
                    ("저장", "save_general_instruction_button", selected_instruction_row is None),
                    ("수정", "update_general_instruction_button", selected_instruction_row is not None and not instruction_view_only),
                    ("삭제", "delete_general_instruction_button", selected_instruction_row is not None and not instruction_view_only),
                ]
                save_clicked, update_clicked, delete_clicked = render_page_actions(action_defs)
                if delete_clicked and selected_instruction_row is not None:
                    ok, message = delete_experiment_instruction(int(selected_instruction_row["experiment_instruction_id"]))
                    if ok:
                        clear_instruction_return_state()
                        flash_success(message)
                        st.rerun()
                    st.error(message)
                elif save_clicked or update_clicked:
                    if process_type in ("인쇄", "후가공", "사상"):
                        upstream_source_mode = str(detail_payload.get("upstream_source_mode") or "")
                        if upstream_source_mode == "기존실험요구" and not detail_payload.get("upstream_instruction_id"):
                            st.error("전공정 실험지시를 먼저 선택해 주세요.")
                            return
                        if upstream_source_mode == "재고품" and not detail_payload.get("upstream_sample_id"):
                            st.error("전공정 재고 샘플을 먼저 선택해 주세요.")
                            return
                    instruction_payload: ExperimentInstructionPayload = {
                        "experiment_order_id": int(selected_order_id),
                        "project_id": int(selected_order_row["project_id"]),
                        "item_id": int(selected_item_id),
                        "process_type": process_type,
                        "required_sample_qty": selected_order_total_required_qty,
                        "requested_finish_date": detail_payload.get("expected_receipt_date"),
                        "machine_no": "",
                        "machine_ton": "",
                        "requirement_completed": bool(requirement_completed),
                        "detail_payload": detail_payload,
                    }
                    saved_instruction = _save_instruction_safely(
                        selected_instruction_row,
                        payload=instruction_payload,
                        current_user_name=current_user()["user_name"],
                    )
                    if saved_instruction is None:
                        return
                    _, instruction_code, mb_request_code = saved_instruction
                    clear_instruction_return_state()
                    success_message = f"실험지시를 저장했습니다. 코드: {instruction_code}"
                    if mb_request_code:
                        success_message += f" | MB의뢰 코드: {mb_request_code}"
                    flash_success(success_message)
                    st.rerun()

    project_history_df = samples_df[samples_df["project_code"] == project_code] if project_code else samples_df.iloc[0:0]
    if not project_history_df.empty:
        display_df = project_history_df.copy()
        display_df["실험세부항목"] = display_df["instruction_checks_json"].apply(lambda raw: ", ".join(json.loads(raw)) if raw else "")
        render_history_panel("이력 보기", display_df[["sample_code", "order_code", "project_code", "item_code", "item_name", "sample_name", "variation_note", "mb_request_code", "customer_delivery_date", "customer_result_date", "customer_result", "customer_result_notes", "실험세부항목", "mold_code", "film_code", "status"]])


def render_op_page(page_name: str = "실험", injection_only: bool = False) -> None:
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = list_project_options()
    instructions_df = list_experiment_instructions()
    samples_df = list_experiment_samples()
    orders_df = list_experiment_orders()
    mb_requests_df = list_mb_requests()
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1, 1.2])
        with pick_c1:
            project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="op_project_label_injection" if injection_only else "op_project_label")
        project_code = project_label.split(" | ")[0] if project_label else ""
        project_molds = list_mold_options_for_project(project_code) if project_code else []
        item_choices = list_item_options_for_project(project_code) if project_code else []
        if injection_only:
            item_choices = [(label, iid) for label, iid in item_choices if infer_process_type_from_item(get_item_row(iid)) == "사출"]
        with pick_c2:
            item_label = st.selectbox("공정품", options=[""] + [label for label, _ in item_choices], key="op_item_label_injection" if injection_only else "op_item_label")
        selected_item_id = dict(item_choices).get(item_label) if item_label else None
        selected_item_row = get_item_row(selected_item_id) if selected_item_id else None
        selected_item_process = infer_process_type_from_item(selected_item_row) if selected_item_row is not None else ""
        filtered_samples = samples_df[samples_df["project_code"] == project_code] if project_code else samples_df.iloc[0:0]
        if selected_item_id:
            filtered_samples = filtered_samples[filtered_samples["item_id"] == selected_item_id]
        if injection_only and not filtered_samples.empty:
            filtered_samples = filtered_samples[filtered_samples["process_type"] == "사출"]
        filtered_instructions = instructions_df[instructions_df["project_code"] == project_code] if project_code else instructions_df.iloc[0:0]
        if selected_item_id:
            filtered_instructions = filtered_instructions[filtered_instructions["item_id"] == selected_item_id]
        if not filtered_instructions.empty:
            filtered_instructions = filtered_instructions[filtered_instructions["process_type"] == "사출"]
        sample_labels = filtered_samples.apply(lambda row: _sample_pick_label(row, orders_df), axis=1).tolist()
        instruction_labels = filtered_instructions.apply(_instruction_pick_label, axis=1).tolist()
        with pick_c3:
            if selected_item_process == "사출":
                instruction_label = st.selectbox("실험지시", options=[""] + instruction_labels, key="op_instruction_pick_injection" if injection_only else "op_instruction_pick")
                sample_label = ""
            else:
                sample_label = st.selectbox("실험", options=[""] + sample_labels, key="op_review_sample_injection" if injection_only else "op_review_sample")
                instruction_label = ""
    else:
        sample_label = ""
        sample_labels = []
        instruction_label = ""
        selected_item_row = None
        selected_item_process = ""

    if can_edit(page_name) and selected_item_process == "사출" and instruction_label:
        selected_instruction_row = filtered_instructions[filtered_instructions.apply(_instruction_pick_label, axis=1) == instruction_label].iloc[0]
        instruction_id = int(selected_instruction_row["experiment_instruction_id"])
        order_id = int(selected_instruction_row["experiment_order_id"])
        item_id = int(selected_instruction_row["item_id"])
        process_type = "사출"
        matched_samples = filtered_samples[filtered_samples["experiment_instruction_id"] == instruction_id] if not filtered_samples.empty and "experiment_instruction_id" in filtered_samples.columns else filtered_samples.iloc[0:0]
        matched_samples = matched_samples.sort_values("sample_id", ascending=True) if not matched_samples.empty else matched_samples
        sample_row = matched_samples.iloc[0] if not matched_samples.empty else None
        selected_row = sample_row
        defaults = latest_op_payload(item_id, process_type)
        instruction_detail = parse_json_text(selected_instruction_row["instruction_detail_json"])
        order_match = orders_df[orders_df["experiment_order_id"] == order_id] if not orders_df.empty else orders_df
        order_row = order_match.iloc[0] if not order_match.empty else None
        order_detail = parse_json_text(order_row["requirement_detail_json"]) if order_row is not None else {}
        _, display_label = _get_requirement_identity(
            order_detail,
            str(selected_instruction_row.get("item_code") or ""),
            str(selected_instruction_row.get("item_name") or ""),
        )
        if display_label:
            st.caption(display_label)
        render_product_drawing_reference(item_id)
        linked_mb_request_row = None
        if not mb_requests_df.empty:
            matched_mb_requests = mb_requests_df[mb_requests_df["experiment_order_id"] == order_id]
            if not matched_mb_requests.empty:
                linked_mb_request_row = matched_mb_requests.iloc[0]
        saved_instruction_mold_id = (
            int(sample_row["used_mold_id"])
            if sample_row is not None and "used_mold_id" in sample_row.index and pd.notna(sample_row["used_mold_id"])
            else int(instruction_detail.get("mold_id"))
            if instruction_detail.get("mold_id")
            else int(selected_item_row["primary_mold_id"])
            if selected_item_row is not None and "primary_mold_id" in selected_item_row.index and pd.notna(selected_item_row["primary_mold_id"])
            else None
        )
        candidate_project_molds, mold_filter_note = _candidate_mold_options_for_item(
            selected_item_row,
            project_molds,
            preferred_mold_id=saved_instruction_mold_id,
        )
        candidate_mold_map = dict(candidate_project_molds)
        candidate_mold_labels = [""] + [label for label, _ in candidate_project_molds]
        selected_instruction_mold_label = next(
            (label for label, mold_id in candidate_mold_map.items() if mold_id == saved_instruction_mold_id),
            "",
        )
        with st.expander("지시 보기", expanded=False):
            render_section_title("지시 요약")
            _render_injection_instruction_summary(
                instruction_code=str(selected_instruction_row["instruction_code"] or ""),
                instruction_date=str(selected_instruction_row.get("instruction_date") or ""),
                requested_date=str(selected_instruction_row["requested_finish_date"] or ""),
                sample_qty=str(selected_instruction_row["required_sample_qty"] or ""),
                mold_code=str(
                    (
                        sample_row["mold_code"]
                        if sample_row is not None and "mold_code" in sample_row.index and pd.notna(sample_row["mold_code"])
                        else instruction_detail.get("mold_code")
                        or (selected_item_row.get("primary_mold_code", "") if selected_item_row is not None else "")
                    )
                    or ""
                ),
                raw_material_label=str(instruction_detail.get("raw_material_label") or (selected_item_row.get("base_material_label", "") if selected_item_row is not None else "") or ""),
                mb_request_code=str(linked_mb_request_row["request_code"]) if linked_mb_request_row is not None and pd.notna(linked_mb_request_row["request_code"]) else (str(sample_row["mb_request_code"]) if sample_row is not None and "mb_request_code" in sample_row.index and pd.notna(sample_row["mb_request_code"]) else ""),
                machine_no=str(selected_instruction_row["machine_no"] or ""),
                machine_ton=str(selected_instruction_row["machine_ton"] or ""),
                key_prefix=f"op_injection_instruction_{instruction_id}",
            )
        st.caption("실험지시를 기준으로 실험을 저장하면 샘플이 생성되거나 갱신됩니다.")
        render_section_title("사출")
        color_plan_rows = instruction_detail.get("color_plan_rows", instruction_detail.get("mb_ratio_plan_rows", []))
        material_tab, condition_tab, measurement_tab, color_sample_tab = st.tabs(["자재/중량", "조건표", "즉시측정", "색상샘플"])
        with material_tab:
            render_section_title("사출 자재/중량")
            use_color_sample_tab = bool(order_detail.get("color_required") and color_plan_rows)
            material_col_spec = [1, 1, 1] if use_color_sample_tab else [1, 1, 1, 0.8]
            material_cols = st.columns(material_col_spec)
            mat_c1, mat_c2, mat_c3 = material_cols[0], material_cols[1], material_cols[2]
            with mat_c1:
                with st.container(border=True):
                    st.caption("설비정보")
                    machine_no_for_op = st.text_input(
                        "호기",
                        value=str(defaults.get("machine_no") or selected_instruction_row["machine_no"] or ""),
                        key=f"inj_machine_no_{instruction_id}",
                    )
                    machine_ton_for_op = st.text_input(
                        "톤수",
                        value=str(defaults.get("machine_ton") or selected_instruction_row["machine_ton"] or ""),
                        key=f"inj_machine_ton_{instruction_id}",
                    )
                    selected_mold_label_for_op = st.selectbox(
                        "금형코드",
                        options=candidate_mold_labels,
                        index=candidate_mold_labels.index(selected_instruction_mold_label)
                        if selected_instruction_mold_label in candidate_mold_labels
                        else 0,
                        key=f"inj_mold_label_{instruction_id}",
                    )
                    if mold_filter_note:
                        st.caption(mold_filter_note)
            with mat_c2:
                with st.container(border=True):
                    st.caption("투입원자재")
                    raw_c1, raw_c2 = st.columns(2)
                    with raw_c1:
                        used_raw_material_label = st.text_input(
                            "원료명",
                            value=str(defaults.get("used_raw_material_label") or instruction_detail.get("raw_material_label") or (selected_item_row.get("base_material_label", "") if selected_item_row is not None else "")),
                            key=f"inj_used_raw_material_label_{instruction_id}",
                        )
                    with raw_c2:
                        raw_material_used_g = st.number_input("투입량", value=float(defaults.get("raw_material_used_g", 0.0)), key=f"inj_raw_material_used_g_{instruction_id}")
                    used_mb_name = st.text_input(
                        "MB명",
                        value=str(defaults.get("used_mb_name") or (linked_mb_request_row["request_code"] if linked_mb_request_row is not None and pd.notna(linked_mb_request_row["request_code"]) else "")),
                        key=f"inj_used_mb_name_{instruction_id}",
                    )
                    mb_c1, mb_c2 = st.columns(2)
                    with mb_c1:
                        mb_used_g = st.number_input("투입량", value=float(defaults.get("mb_used_g", 0.0)), key=f"inj_mb_used_g_{instruction_id}")
                    with mb_c2:
                        mb_ratio_pct = st.number_input("%", value=float(defaults.get("mb_ratio_pct", 0.0)), key=f"inj_mb_ratio_pct_{instruction_id}")
            with mat_c3:
                with st.container(border=True):
                    st.caption("중량")
                    runner_weight = st.number_input("런너중량", value=float(defaults.get("runner_weight", 0.0)), key=f"inj_runner_weight_{instruction_id}")
                    st.caption("제품중량")
                    weight_values = []
                    weight_cols_top = st.columns(4)
                    weight_cols_bottom = st.columns(4)
                    for i in range(1, 5):
                        with weight_cols_top[i - 1]:
                            weight_values.append(st.text_input(str(i), value=str(defaults.get(f"product_weight_{i}", "")), key=f"inj_product_weight_{instruction_id}_{i}"))
                    for i in range(5, 9):
                        with weight_cols_bottom[i - 5]:
                            weight_values.append(st.text_input(str(i), value=str(defaults.get(f"product_weight_{i}", "")), key=f"inj_product_weight_{instruction_id}_{i}"))
            color_sample_rows: list[dict] = []
            produced_sample_qty = _safe_int_value(defaults.get("produced_sample_qty", selected_instruction_row["required_sample_qty"] if pd.notna(selected_instruction_row["required_sample_qty"]) else 1), 1)
            if not use_color_sample_tab:
                with material_cols[3]:
                    with st.container(border=True):
                        st.caption("실제생산수량")
                        produced_sample_qty = int(
                            st.number_input(
                                "재고 생성 수량",
                                min_value=1,
                                step=1,
                                value=produced_sample_qty,
                                key=f"inj_produced_sample_qty_{instruction_id}",
                            )
                        )
            expected_issue = st.text_input("예상문제", value=str(defaults.get("expected_issue", "")), key=f"inj_expected_issue_{instruction_id}")
        with condition_tab:
            render_section_title("사출 조건표")
            condition_values = render_injection_condition_inputs(defaults)
        with measurement_tab:
            render_section_title("즉시 측정값")
            immediate_values = render_measurement_inputs(
                defaults,
                "즉시",
                {slot: str(instruction_detail.get(f"measurement_title_{slot}", "") or "") for slot in ["A", "B", "C"]},
                {slot: str(instruction_detail.get(f"measurement_spec_{slot}", "") or "") for slot in ["A", "B", "C"]},
                single_card=True,
                card_title="즉시측정값",
            )
            render_section_title("OP 검토")
            op_review_values = render_injection_op_review_inputs(defaults)
        with color_sample_tab:
            render_section_title("색상샘플")
            existing_color_plan_map = {
                str(row.get("label") or ""): row
                for row in defaults.get("color_samples", [])
                if isinstance(row, dict)
            }
            if use_color_sample_tab:
                existing_sample_map = {
                    str(row.get("sample_name") or ""): row
                    for _, row in matched_samples.iterrows()
                } if not matched_samples.empty else {}
                existing_codes = set(samples_df["sample_code"].dropna().astype(str).tolist())
                plan_cols = st.columns(4)
                for idx, ratio_row in enumerate(color_plan_rows[:4], start=1):
                    ratio_value = float(ratio_row.get("ratio", 0.0) or 0.0)
                    label = str(ratio_row.get("label") or f"{idx}안")
                    existing_sample = existing_sample_map.get(label)
                    planned_code = str(existing_sample["sample_code"]) if existing_sample is not None and pd.notna(existing_sample["sample_code"]) else make_sample_code(
                        str(selected_instruction_row["instruction_code"]).replace("IN-", "EX-", 1),
                        idx,
                        ratio_value,
                        existing_codes,
                    )
                    with plan_cols[idx - 1]:
                        st.text_input("구분", value=label, disabled=True, key=f"inj_plan_label_{instruction_id}_{idx}")
                        st.text_input("농도(%)", value=f"{ratio_value:.1f}", disabled=True, key=f"inj_plan_ratio_{instruction_id}_{idx}")
                        planned_qty = int(
                            st.number_input(
                                "실제생산수량",
                                min_value=1,
                                step=1,
                                value=int(existing_color_plan_map.get(label, {}).get("sample_qty", 1) or 1),
                                key=f"inj_plan_qty_{instruction_id}_{idx}",
                            )
                        )
                        st.text_input("샘플코드", value=planned_code, disabled=True, key=f"inj_plan_code_{instruction_id}_{idx}")
                    color_sample_rows.append(
                        {
                            "label": label,
                            "ratio": ratio_value,
                            "sample_code": planned_code,
                            "sample_qty": planned_qty,
                        }
                    )
            else:
                st.caption("색상샘플 계획이 없으면 1개 샘플로 저장됩니다.")
        detail_payload = {
            "machine_no": machine_no_for_op,
            "machine_ton": machine_ton_for_op,
            "mold_id": candidate_mold_map.get(selected_mold_label_for_op) if selected_mold_label_for_op else None,
            "mold_code": selected_mold_label_for_op.split(" | ")[0].strip() if selected_mold_label_for_op else "",
            "used_raw_material_label": used_raw_material_label,
            "used_mb_name": used_mb_name,
            "raw_material_used_g": raw_material_used_g,
            "mb_used_g": mb_used_g,
            "mb_ratio_pct": mb_ratio_pct,
            "expected_issue": expected_issue,
            "runner_weight": runner_weight,
            "produced_sample_qty": produced_sample_qty,
            "color_samples": color_sample_rows,
            **{f"product_weight_{i}": weight_values[i - 1] for i in range(1, 9)},
            **condition_values,
            **immediate_values,
            **op_review_values,
        }
        condition_input = json.dumps(condition_values, ensure_ascii=False)
        inspection_plan = inspection_plan_from_details(instruction_detail, order_detail)
        immediate_values = add_check_id_results(immediate_values, inspection_plan, timing="immediate")
        first_measurement = json.dumps(immediate_values, ensure_ascii=False)
        first_action = ""
        (save_clicked,) = render_page_actions([("실험 내용 저장", "save_injection_op_review", True)])
        if save_clicked:
            base_instruction_code = str(selected_instruction_row["instruction_code"])
            base_sample_code = base_instruction_code.replace("IN-", "EX-", 1)
            color_plan_rows = instruction_detail.get("color_plan_rows", instruction_detail.get("mb_ratio_plan_rows", []))
            existing_sample_map = {
                str(row.get("sample_name") or ""): row
                for _, row in matched_samples.iterrows()
            } if not matched_samples.empty else {}
            existing_codes = set(samples_df["sample_code"].dropna().astype(str).tolist())
            sample_targets = color_sample_rows if color_sample_rows else [{"label": "1차", "ratio": None, "sample_qty": produced_sample_qty}]
            last_saved_sample_id = None
            for idx, target in enumerate(sample_targets, start=1):
                label = str(target.get("label") or ("1차" if not color_plan_rows else f"{idx}안"))
                ratio_value = target.get("ratio", None)
                target_sample_row = existing_sample_map.get(label)
                sample_code = (
                    str(target_sample_row["sample_code"])
                    if target_sample_row is not None and pd.notna(target_sample_row["sample_code"])
                    else make_sample_code(base_sample_code, idx, float(ratio_value) if ratio_value is not None else None, existing_codes)
                )
                existing_codes.add(sample_code)
                sample_seq = int(target_sample_row["sample_seq"]) if target_sample_row is not None and pd.notna(target_sample_row["sample_seq"]) else idx
                current_instruction_detail = dict(instruction_detail)
                if ratio_value is not None:
                    current_instruction_detail["mb_ratio"] = float(ratio_value)
                current_instruction_detail["planned_sample_qty"] = int(target.get("sample_qty") or produced_sample_qty or 1)
                sample_payload: ExperimentSamplePayload = {
                    "order_id": order_id,
                    "experiment_instruction_id": instruction_id,
                    "sample_code": sample_code,
                    "sample_seq": sample_seq,
                    "sample_name": label,
                    "variation_note": "",
                    "mold_label": selected_mold_label_for_op,
                    "film_label": "",
                    "customer_delivery_date": str(target_sample_row["customer_delivery_date"]) if target_sample_row is not None and pd.notna(target_sample_row["customer_delivery_date"]) else None,
                    "customer_result_date": str(target_sample_row["customer_result_date"]) if target_sample_row is not None and pd.notna(target_sample_row["customer_result_date"]) else None,
                    "customer_result": str(target_sample_row["customer_result"]) if target_sample_row is not None and pd.notna(target_sample_row["customer_result"]) else "",
                    "customer_result_notes": str(target_sample_row["customer_result_notes"]) if target_sample_row is not None and pd.notna(target_sample_row["customer_result_notes"]) else "",
                    "instruction_checks": [],
                    "detail_payload": current_instruction_detail,
                    "process_type": process_type,
                    "order_detail": order_detail,
                    "mb_nuance": "",
                    "mb_supplier_name": "",
                    "mb_expected_receipt_date": None,
                    "mb_sample_received": False,
                    "mold_dispatch_note": "",
                    "mold_sample_request_date": None,
                    "drawing_receipt_status": str(order_row["drawing_receipt_status"]) if order_row is not None and "drawing_receipt_status" in order_row.index else "",
                    "base_drawing_revision": str(order_row["base_drawing_revision"]) if order_row is not None and "base_drawing_revision" in order_row.index else "",
                }
                last_saved_sample_id = save_experiment_sample(
                    target_sample_row,
                    payload=sample_payload,
                    linked_mb_request_row=None,
                    linked_mold_dispatch_row=None,
                    project_molds=project_molds,
                    project_films=[],
                    current_user_name=current_user()["user_name"],
                )
                op_payload: OpReviewPayload = {
                    "sample_id": int(last_saved_sample_id),
                    "mold_ready": False,
                    "material_ready": False,
                    "film_ready": False,
                    "drawing_ready": False,
                    "condition_input": condition_input,
                    "first_measurement": first_measurement,
                    "detail_payload": detail_payload,
                    "first_action": first_action,
                }
                save_op_review(payload=op_payload, current_user_name=current_user()["user_name"])
            flash_success("실험 내용을 저장했습니다.")
            st.rerun()
    elif can_edit(page_name) and sample_label:
        sample_row = filtered_samples[filtered_samples.apply(lambda row: _sample_pick_label(row, orders_df), axis=1) == sample_label].iloc[0]
        sample_id = int(sample_row["sample_id"])
        process_type = sample_row["process_type"]
        item_id = int(sample_row["item_id"])
        defaults = latest_op_payload(item_id, process_type)
        instruction_detail = parse_json_text(sample_row["instruction_detail_json"])
        order_match = orders_df[orders_df["order_code"] == str(sample_row["order_code"])] if not orders_df.empty else orders_df
        order_row = order_match.iloc[0] if not order_match.empty else None
        order_detail = parse_json_text(order_row["requirement_detail_json"]) if order_row is not None else {}
        _, display_label = _get_requirement_identity(order_detail, str(sample_row.get("item_code") or ""), str(sample_row.get("item_name") or ""))
        if display_label:
            st.caption(display_label)
        render_product_drawing_reference(item_id)
        with st.expander("지시 보기", expanded=False):
            if process_type == "사출":
                linked_mb_request_row = None
                if order_row is not None and not mb_requests_df.empty:
                    matched_mb_requests = mb_requests_df[mb_requests_df["experiment_order_id"] == int(order_row["experiment_order_id"])]
                    if not matched_mb_requests.empty:
                        linked_mb_request_row = matched_mb_requests.iloc[0]
                render_section_title("지시 요약")
                _render_injection_instruction_summary(
                    instruction_code=str(sample_row.get("instruction_code") or sample_row["order_code"] or ""),
                    instruction_date=str(sample_row.get("instruction_date") or ""),
                    requested_date=str(sample_row.get("target_due_date") or ""),
                    sample_qty=str(defaults.get("produced_sample_qty") or sample_row.get("required_sample_qty") or ""),
                    mold_code=str(sample_row.get("mold_code") or ""),
                    raw_material_label=str(instruction_detail.get("raw_material_label") or ""),
                    mb_request_code=str(sample_row.get("mb_request_code") or (linked_mb_request_row["request_code"] if linked_mb_request_row is not None and pd.notna(linked_mb_request_row["request_code"]) else "") or ""),
                    machine_no=str(defaults.get("machine_no") or ""),
                    machine_ton=str(defaults.get("machine_ton") or ""),
                    key_prefix=f"legacy_op_injection_instruction_{sample_id}",
                )
            elif process_type == "인쇄":
                _render_process_instruction_summary(
                    "인쇄",
                    instruction_code=str(sample_row.get("instruction_code") or ""),
                    instruction_date=str(sample_row.get("instruction_date") or ""),
                    requested_date=str(instruction_detail.get("expected_receipt_date") or sample_row.get("target_due_date") or ""),
                    execution_mode=str(instruction_detail.get("execution_mode") or "내부"),
                    upstream_sample_code=str(instruction_detail.get("upstream_sample_code") or ""),
                    vendor_name=str(instruction_detail.get("vendor_name") or ""),
                    note_1=str(instruction_detail.get("color_nuance") or ""),
                    note_2=str(instruction_detail.get("print_position_note") or ""),
                    milestone_name=str(sample_row["milestone_name"] or ""),
                    extra_label_1="원화",
                    extra_value_1=str(sample_row["film_code"] or ""),
                )
            elif process_type in ("후가공", "사상"):
                _render_process_instruction_summary(
                    str(process_type),
                    instruction_code=str(sample_row.get("instruction_code") or ""),
                    instruction_date=str(sample_row.get("instruction_date") or ""),
                    requested_date=str(instruction_detail.get("expected_receipt_date") or sample_row.get("target_due_date") or ""),
                    execution_mode=str(instruction_detail.get("execution_mode") or "내부"),
                    upstream_sample_code=str(instruction_detail.get("upstream_sample_code") or ""),
                    vendor_name=str(instruction_detail.get("vendor_name") or ""),
                    note_1=str(instruction_detail.get("color_nuance") or ""),
                    note_2=str(instruction_detail.get("masking_position_note") or ""),
                    milestone_name=str(sample_row["milestone_name"] or ""),
                )
            else:
                sum_c1, sum_c2, sum_c3, sum_c4 = st.columns(4)
                with sum_c1:
                    st.text_input("업체", value=instruction_detail.get("vendor_name", "-") or "-", disabled=True, key="op_assy_vendor")
                with sum_c2:
                    st.text_input("지시 납기일", value=instruction_detail.get("expected_receipt_date", "-") or "-", disabled=True, key="op_assy_expected_date")
                with sum_c3:
                    st.text_input("조립 확인", value=instruction_detail.get("assembly_note", "-") or "-", disabled=True, key="op_assy_note")
                with sum_c4:
                    st.text_input("고객요구 마일스톤", value=sample_row["milestone_name"] or "-", disabled=True, key="op_assy_milestone")
                st.text_input("고객요구 완료일", value=sample_row["target_due_date"] or "-", disabled=True, key="op_assy_due_date")
        st.caption(f"직전 같은 공정품 입력값을 초기값으로 사용합니다.")
        detail_payload = {}
        if process_type == "사출":
            render_section_title("사출")
            material_tab, condition_tab, measurement_tab, color_sample_tab = st.tabs(["자재/중량", "조건표", "즉시측정", "색상샘플"])
            ratio_rows = instruction_detail.get("mb_ratio_plan_rows", [])
            if not ratio_rows and instruction_detail.get("mb_ratio"):
                ratio_rows = [{"label": sample_row["sample_name"] or "1안", "ratio": instruction_detail.get("mb_ratio", 0.0)}]
            with material_tab:
                render_section_title("사출 자재/중량")
                use_color_sample_tab = bool(ratio_rows)
                material_col_spec = [1, 1, 1] if use_color_sample_tab else [1, 1, 1, 0.8]
                material_cols = st.columns(material_col_spec)
                mat_c1, mat_c2, mat_c3 = material_cols[0], material_cols[1], material_cols[2]
                with mat_c1:
                    with st.container(border=True):
                        st.caption("설비정보")
                        machine_no_for_op = st.text_input(
                            "호기",
                            value=str(defaults.get("machine_no") or sample_row.get("machine_no") or ""),
                            key=f"legacy_inj_machine_no_{sample_id}",
                        )
                        machine_ton_for_op = st.text_input(
                            "톤수",
                            value=str(defaults.get("machine_ton") or sample_row.get("machine_ton") or ""),
                            key=f"legacy_inj_machine_ton_{sample_id}",
                        )
                with mat_c2:
                    with st.container(border=True):
                        st.caption("투입원자재")
                        raw_c1, raw_c2 = st.columns(2)
                        with raw_c1:
                            used_raw_material_label = st.text_input(
                                "원료명",
                                value=str(defaults.get("used_raw_material_label") or instruction_detail.get("raw_material_label") or ""),
                                key=f"legacy_inj_used_raw_material_label_{sample_id}",
                            )
                        with raw_c2:
                            raw_material_used_g = st.number_input("투입량", value=float(defaults.get("raw_material_used_g", 0.0)))
                        used_mb_name = st.text_input(
                            "MB명",
                            value=str(defaults.get("used_mb_name") or sample_row.get("mb_request_code") or ""),
                            key=f"legacy_inj_used_mb_name_{sample_id}",
                        )
                        mb_c1, mb_c2 = st.columns(2)
                        with mb_c1:
                            mb_used_g = st.number_input("투입량", value=float(defaults.get("mb_used_g", 0.0)))
                        with mb_c2:
                            mb_ratio_pct = st.number_input("%", value=float(defaults.get("mb_ratio_pct", 0.0)))
                with mat_c3:
                    with st.container(border=True):
                        st.caption("중량")
                        runner_weight = st.number_input("런너중량", value=float(defaults.get("runner_weight", 0.0)))
                        st.caption("제품중량")
                        weight_values = []
                        weight_cols_top = st.columns(4)
                        weight_cols_bottom = st.columns(4)
                        for i in range(1, 5):
                            with weight_cols_top[i - 1]:
                                weight_values.append(st.text_input(str(i), value=str(defaults.get(f"product_weight_{i}", "")), key=f"product_weight_{i}"))
                        for i in range(5, 9):
                            with weight_cols_bottom[i - 5]:
                                weight_values.append(st.text_input(str(i), value=str(defaults.get(f"product_weight_{i}", "")), key=f"product_weight_{i}"))
                produced_sample_qty = int(defaults.get("produced_sample_qty", 1) or 1)
                if not use_color_sample_tab:
                    with material_cols[3]:
                        with st.container(border=True):
                            st.caption("실제생산수량")
                            produced_sample_qty = int(
                                st.number_input(
                                    "재고 생성 수량",
                                    min_value=1,
                                    step=1,
                                    value=produced_sample_qty,
                                    key=f"legacy_inj_produced_sample_qty_{sample_id}",
                                )
                            )
                expected_issue = st.text_input("예상문제", value=str(defaults.get("expected_issue", "")))
            with condition_tab:
                render_section_title("사출 조건표")
                condition_values = render_injection_condition_inputs(defaults)
            with measurement_tab:
                render_section_title("즉시 측정값")
                immediate_values = render_measurement_inputs(
                    defaults,
                    "즉시",
                    {
                        slot: str(instruction_detail.get(f"measurement_title_{slot}", "") or "")
                        for slot in ["A", "B", "C"]
                    },
                    {
                        slot: str(instruction_detail.get(f"measurement_spec_{slot}", "") or "")
                        for slot in ["A", "B", "C"]
                    },
                    single_card=True,
                    card_title="즉시측정값",
                )
                render_section_title("OP 검토")
                op_review_values = render_injection_op_review_inputs(defaults)
            with color_sample_tab:
                render_section_title("색상샘플")
                existing_color_samples = defaults.get("color_samples", [])
                existing_sample_map = {
                    str(row.get("label") or f"{idx + 1}안"): row
                    for idx, row in enumerate(existing_color_samples)
                    if isinstance(row, dict)
                }
                base_instruction_code = sample_row["order_code"].replace("RQ-", "EX-", 1) if str(sample_row["order_code"]).startswith("RQ-") else f"EX-{sample_row['order_code']}"
                existing_codes = set(samples_df["sample_code"].dropna().astype(str).tolist())
                color_sample_rows = []
                generated_codes: list[str] = []
                if ratio_rows:
                    for idx, ratio_row in enumerate(ratio_rows, start=1):
                        ratio_value = float(ratio_row.get("ratio", 0.0) or 0.0)
                        if ratio_value <= 0:
                            continue
                        label = str(ratio_row.get("label") or f"{idx}안")
                        saved_row = existing_sample_map.get(label, {})
                        row_c1, row_c2, row_c3, row_c4 = st.columns([1, 1, 1, 1.4])
                        with row_c1:
                            st.text_input("구분", value=label, disabled=True, key=f"op_color_label_{sample_id}_{idx}")
                        with row_c2:
                            st.text_input("농도(%)", value=f"{ratio_value:.1f}", disabled=True, key=f"op_color_ratio_{sample_id}_{idx}")
                        with row_c3:
                            sample_qty = int(
                                st.number_input(
                                    "실제생산수량",
                                    min_value=1,
                                    step=1,
                                    value=int(saved_row.get("sample_qty", 1) or 1),
                                    key=f"op_color_qty_{sample_id}_{idx}",
                                )
                            )
                        with row_c4:
                            make_sample = st.checkbox(
                                "샘플제작",
                                value=bool(saved_row.get("created", False)),
                                key=f"op_color_make_{sample_id}_{idx}",
                            )
                        generated_code = str(saved_row.get("sample_code") or "")
                        if make_sample and not generated_code:
                            generated_code = make_sample_code(
                                base_instruction_code,
                                idx,
                                ratio_value,
                                existing_codes | set(generated_codes),
                            )
                            generated_codes.append(generated_code)
                        with row_c4:
                            st.text_input("샘플코드", value=generated_code if make_sample else "", disabled=True, key=f"op_color_code_{sample_id}_{idx}")
                        color_sample_rows.append(
                            {
                                "label": label,
                                "ratio": ratio_value,
                                "sample_qty": sample_qty,
                                "created": make_sample,
                                "sample_code": generated_code if make_sample else "",
                            }
                        )
                else:
                    st.caption("지시에 등록된 농도안이 없습니다.")
            detail_payload = {
                "machine_no": machine_no_for_op,
                "machine_ton": machine_ton_for_op,
                "used_raw_material_label": used_raw_material_label,
                "used_mb_name": used_mb_name,
                "raw_material_used_g": raw_material_used_g,
                "mb_used_g": mb_used_g,
                "mb_ratio_pct": mb_ratio_pct,
                "expected_issue": expected_issue,
                "runner_weight": runner_weight,
                "produced_sample_qty": produced_sample_qty,
                "color_samples": color_sample_rows,
                **{f"product_weight_{i}": weight_values[i - 1] for i in range(1, 9)},
                **condition_values,
                **immediate_values,
                **op_review_values,
            }
        elif process_type == "조립":
            render_section_title("조립")
            expected_man_hour = st.number_input("예상인시생산값", value=float(defaults.get("expected_man_hour", 0.0)), key="assembly_expected_man_hour")
            expected_issue = st.text_area("예상문제", value=str(defaults.get("expected_issue", "")), height=80, key="assembly_expected_issue")
            change_request = st.text_area("수정요청사항", value=str(defaults.get("change_request", "")), height=80, key="assembly_change_request")
            measure_checks = st.multiselect("측정항목 체크", ["분리", "기능규격", "간섭", "체결력"], default=defaults.get("measure_checks", []), key="assembly_measure_checks")
            measure_values = st.text_area("측정값 입력", value=str(defaults.get("measure_values", "")), height=80, key="assembly_measure_values")
            detail_payload = {
                "expected_man_hour": expected_man_hour,
                "expected_issue": expected_issue,
                "change_request": change_request,
                "measure_checks": measure_checks,
                "measure_values": measure_values,
            }
            st.info("조립도면은 위 도면 참조 영역에서 확인합니다.")
        else:
            render_section_title("인쇄")
            st.caption(f"지시 원화: {sample_row['film_code'] or '-'}")
            st.caption(f"색상샘플 유무: {instruction_detail.get('color_sample_exists', '-')}")
            color_target = st.text_input("색상 기준", value=str(defaults.get("color_target", "")), key="print_color_target")
            print_position = st.text_input("인쇄 위치", value=str(defaults.get("print_position", "")), key="print_position")
            expected_issue = st.text_area("예상문제", value=str(defaults.get("expected_issue", "")), height=80, key="print_expected_issue")
            request_change = st.text_area("수정요청사항", value=str(defaults.get("request_change", "")), height=80, key="print_request_change")
            measure_values = st.text_area("측정/체크 결과", value=str(defaults.get("measure_values", "")), height=80, key="print_measure_values")
            detail_payload = {
                "color_target": color_target,
                "print_position": print_position,
                "expected_issue": expected_issue,
                "request_change": request_change,
                "measure_values": measure_values,
            }
        condition_input = json.dumps(condition_values, ensure_ascii=False) if process_type == "사출" else ""
        inspection_plan = inspection_plan_from_details(instruction_detail, order_detail)
        immediate_values = add_check_id_results(immediate_values, inspection_plan, timing="immediate") if process_type == "사출" else immediate_values
        first_measurement = json.dumps(immediate_values, ensure_ascii=False) if process_type == "사출" else ""
        first_action = ""
        (save_clicked,) = render_page_actions([("실험 내용 저장", "save_op_review", True)])
        if save_clicked:
            op_payload: OpReviewPayload = {
                "sample_id": sample_id,
                "mold_ready": False,
                "material_ready": False,
                "film_ready": False,
                "drawing_ready": False,
                "condition_input": condition_input,
                "first_measurement": first_measurement,
                "detail_payload": detail_payload,
                "first_action": first_action,
            }
            save_op_review(
                payload=op_payload,
                current_user_name=current_user()["user_name"],
            )
            flash_success("실험 내용을 저장했습니다.")
            st.rerun()
    workflow_df = list_sample_workflow()
    if not workflow_df.empty:
        history_df = workflow_df.copy()
        if project_code:
            history_df = history_df[history_df["project_code"] == project_code]
        if selected_item_id:
            history_df = history_df[history_df["item_id"] == selected_item_id]
        render_history_panel("이력 보기", history_df[["sample_code", "order_code", "item_name", "process_type", "status"]])


def render_quality_page() -> None:
    page_name = "품질검토"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = list_project_options()
    samples_df = list_experiment_samples()
    orders_df = list_experiment_orders()
    workflow_df = list_sample_workflow()
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1, 1.2])
        with pick_c1:
            project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="quality_project_label")
        project_code = project_label.split(" | ")[0] if project_label else ""
        item_choices = list_item_options_for_project(project_code) if project_code else []
        with pick_c2:
            item_label = st.selectbox("공정품", options=[""] + [label for label, _ in item_choices], key="quality_item_label")
        selected_item_id = dict(item_choices).get(item_label) if item_label else None
        if selected_item_id:
            render_product_drawing_reference(selected_item_id)
        filtered_samples = samples_df[samples_df["project_code"] == project_code] if project_code else samples_df.iloc[0:0]
        if selected_item_id:
            filtered_samples = filtered_samples[filtered_samples["item_id"] == selected_item_id]
        sample_labels = filtered_samples.apply(lambda row: _sample_pick_label(row, orders_df), axis=1).tolist()
        with pick_c3:
            sample_label = st.selectbox("실험", options=[""] + sample_labels, key="quality_review_sample")
    else:
        sample_label = ""
        sample_labels = []
    if can_edit(page_name) and sample_label:
        st.caption("실험 결과를 기준도면, 24시간 후 값, 품질의견 중심으로 검토합니다.")
        selected_basic_row = filtered_samples[filtered_samples.apply(lambda row: _sample_pick_label(row, orders_df), axis=1) == sample_label].iloc[0]
        sample_id = int(selected_basic_row["sample_id"])
        workflow_match = workflow_df[workflow_df["sample_id"] == sample_id] if not workflow_df.empty else workflow_df
        workflow_row = workflow_match.iloc[0] if not workflow_match.empty else None
        op_detail = parse_json_text(workflow_row["op_detail_json"]) if workflow_row is not None and pd.notna(workflow_row["op_detail_json"]) else {}
        instruction_detail = parse_json_text(selected_basic_row["instruction_detail_json"])
        order_match = orders_df[orders_df["order_code"] == str(selected_basic_row["order_code"])] if not orders_df.empty else orders_df
        order_row = order_match.iloc[0] if not order_match.empty else None
        order_detail = parse_json_text(order_row["requirement_detail_json"]) if order_row is not None else {}
        _, display_label = _get_requirement_identity(order_detail, str(selected_basic_row.get("item_code") or ""), str(selected_basic_row.get("item_name") or ""))
        if display_label:
            st.caption(display_label)
        with st.expander("지시 보기", expanded=False):
            if selected_basic_row["process_type"] == "사출":
                info_c1, info_c2, info_c3, info_c4, info_c5 = st.columns(5)
                with info_c1:
                    st.text_input("샘플코드", value=selected_basic_row.get("sample_code") or "-", disabled=True, key="quality_sample_code")
                with info_c2:
                    experiment_date_text = (
                        str(selected_basic_row.get("experiment_date") or "")
                        or str(selected_basic_row.get("instruction_date") or "")
                        or "-"
                    )
                    st.text_input("실험일", value=experiment_date_text, disabled=True, key="quality_instruction_date")
                with info_c3:
                    st.text_input("금형코드", value=selected_basic_row.get("mold_code") or "-", disabled=True, key="quality_instruction_mold_code")
                with info_c4:
                    st.text_input(
                        "원료명",
                        value=op_detail.get("used_raw_material_label") or instruction_detail.get("raw_material_label") or "-",
                        disabled=True,
                        key="quality_instruction_raw_material",
                    )
                with info_c5:
                    st.text_input(
                        "MB코드",
                        value=op_detail.get("used_mb_name") or selected_basic_row.get("mb_request_code") or "-",
                        disabled=True,
                        key="quality_instruction_mb_code",
                    )
                req_c1, req_c2, req_c3, req_c4, req_c5 = st.columns(5)
                with req_c1:
                    st.text_input("의뢰코드", value=selected_basic_row.get("order_code") or "-", disabled=True, key="quality_order_code")
                with req_c2:
                    st.text_input("샘플요청일", value=selected_basic_row.get("target_due_date") or "-", disabled=True, key="quality_sample_request_due")
                with req_c3:
                    st.text_input("금형수정여부", value="있음" if order_detail.get("mold_dispatch_required") else "없음", disabled=True, key="quality_mold_dispatch_required")
                with req_c4:
                    st.text_input("색상실험여부", value="있음" if order_detail.get("color_required") else "없음", disabled=True, key="quality_color_required")
                with req_c5:
                    st.text_input("원료실험여부", value="있음" if order_detail.get("raw_material_experiment_required") else "없음", disabled=True, key="quality_raw_material_required")
            elif selected_basic_row["process_type"] in ("인쇄", "후가공", "사상"):
                _render_process_instruction_summary(
                    str(selected_basic_row["process_type"]),
                    instruction_code=str(selected_basic_row.get("instruction_code") or ""),
                    instruction_date=str(selected_basic_row.get("instruction_date") or ""),
                    requested_date=str(instruction_detail.get("expected_receipt_date") or selected_basic_row.get("target_due_date") or ""),
                    execution_mode=str(instruction_detail.get("execution_mode") or "내부"),
                    upstream_sample_code=str(instruction_detail.get("upstream_sample_code") or ""),
                    vendor_name=str(instruction_detail.get("vendor_name") or ""),
                    note_1=str(instruction_detail.get("color_nuance") or ""),
                    note_2=str(
                        instruction_detail.get("print_position_note")
                        if selected_basic_row["process_type"] == "인쇄"
                        else instruction_detail.get("masking_position_note")
                        or ""
                    ),
                    milestone_name=str(selected_basic_row["milestone_name"] or ""),
                    extra_label_1="원화" if selected_basic_row["process_type"] == "인쇄" else "",
                    extra_value_1=str(selected_basic_row["film_code"] or "") if selected_basic_row["process_type"] == "인쇄" else "",
                )
            else:
                info_c1, info_c2, info_c3, info_c4 = st.columns(4)
                with info_c1:
                    st.text_input("금형/원화", value=selected_basic_row["mold_code"] or selected_basic_row["film_code"] or "-", disabled=True, key="quality_instruction_tool")
                with info_c2:
                    st.text_input("원료/업체", value=instruction_detail.get("raw_material_label", "-") or instruction_detail.get("vendor_name", "-"), disabled=True, key="quality_instruction_material")
                with info_c3:
                    st.text_input("조건", value=instruction_detail.get("assembly_note", "-") or "-", disabled=True, key="quality_instruction_mb")
                with info_c4:
                    st.text_input("고객요구 마일스톤", value=selected_basic_row["milestone_name"] or "-", disabled=True, key="quality_instruction_milestone")
                due_c1, due_c2 = st.columns(2)
                with due_c1:
                    st.text_input("고객요구 완료일", value=selected_basic_row["target_due_date"] or "-", disabled=True, key="quality_instruction_due_date")
                with due_c2:
                    instruction_due = instruction_detail.get("expected_receipt_date") or "-"
                    st.text_input("지시 납기일", value=instruction_due, disabled=True, key="quality_instruction_expected_due")
        sample_row = workflow_row if workflow_row is not None else workflow_df[workflow_df["sample_id"] == sample_id].iloc[0]
        inspection_plan = inspection_plan_from_details(instruction_detail, order_detail)
        inspection_plan_map = {str(item.get("check_id")): item for item in inspection_plan}
        quality_defaults = {
            "second_measurement": sample_row["second_measurement"],
            "after_24h_measurement": sample_row["after_24h_measurement"],
            "quality_comment": sample_row["quality_comment"],
            **{
                f"instruction_measure_title_{slot}": instruction_detail.get(f"measurement_title_{slot}", "") or inspection_plan_map.get(f"DIM-{slot}", {}).get("name", "")
                for slot in ("A", "B", "C")
            },
            **{
                f"instruction_measure_spec_{slot}": instruction_detail.get(f"measurement_spec_{slot}", "") or inspection_plan_map.get(f"DIM-{slot}", {}).get("spec", "")
                for slot in ("A", "B", "C")
            },
        }
        render_section_title("품질검토 입력")
        if sample_row["process_type"] == "사출":
            second_measurement, after_24h_measurement, quality_comment = render_injection_quality_review_inputs(quality_defaults)
            post_process_review = ""
            assembly_review = ""
        elif sample_row["process_type"] == "조립":
            second_measurement, after_24h_measurement, quality_comment = render_assembly_quality_review_inputs(quality_defaults)
            post_process_review = ""
            assembly_review = second_measurement
        else:
            second_measurement, after_24h_measurement, quality_comment = render_print_quality_review_inputs(quality_defaults)
            post_process_review = second_measurement
            assembly_review = ""
        if sample_row["process_type"] == "사출":
            after_24h_detail = add_check_id_results(
                parse_inspection_dict(after_24h_measurement),
                inspection_plan,
                timing="24h",
            )
            after_24h_measurement = json.dumps(after_24h_detail, ensure_ascii=False)
        (save_clicked,) = render_page_actions([("품질검토 저장", "save_quality_review", True)])
        if save_clicked:
            quality_payload: QualityReviewPayload = {
                "sample_id": sample_id,
                "second_measurement": second_measurement,
                "after_24h_measurement": after_24h_measurement,
                "post_process_review": post_process_review,
                "assembly_review": assembly_review,
                "quality_comment": quality_comment,
            }
            save_quality_review(
                payload=quality_payload,
                current_user_name=current_user()["user_name"],
            )
            flash_success("품질검토를 저장했습니다.")
            st.rerun()
    if not workflow_df.empty:
        render_history_panel("이력 보기", workflow_df[["sample_code", "status", "customer_delivery_date", "customer_result_date", "customer_result", "after_24h_measurement", "quality_comment"]])


def render_final_page() -> None:
    page_name = "최종검토"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = list_project_options()
    samples_df = list_experiment_samples()
    orders_df = list_experiment_orders()
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1, 1.2])
        with pick_c1:
            project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="final_project_label")
        project_code = project_label.split(" | ")[0] if project_label else ""
        item_choices = list_item_options_for_project(project_code) if project_code else []
        with pick_c2:
            item_label = st.selectbox("공정품", options=[""] + [label for label, _ in item_choices], key="final_item_label")
        selected_item_id = dict(item_choices).get(item_label) if item_label else None
        filtered_samples = samples_df[samples_df["project_code"] == project_code] if project_code else samples_df.iloc[0:0]
        if selected_item_id:
            filtered_samples = filtered_samples[filtered_samples["item_id"] == selected_item_id]
        sample_labels = filtered_samples.apply(lambda row: _sample_pick_label(row, orders_df), axis=1).tolist()
        with pick_c3:
            sample_label = st.selectbox("실험", options=[""] + sample_labels, key="final_review_sample")
    else:
        sample_label = ""
        sample_labels = []
    if can_edit(page_name) and sample_label:
        st.caption("최종검토는 확정 여부와 후속 조치를 정리하는 단계입니다.")
        sample_row = filtered_samples[filtered_samples.apply(lambda row: _sample_pick_label(row, orders_df), axis=1) == sample_label].iloc[0]
        sample_id = int(sample_row["sample_id"])
        item_id = int(sample_row["item_id"])
        item_row = get_item_row(item_id)
        final_mold_code = str(
            (
                sample_row["mold_code"]
                if "mold_code" in sample_row.index and pd.notna(sample_row["mold_code"])
                else item_row.get("primary_mold_code", "") if item_row is not None else ""
            )
            or ""
        )
        instruction_detail = parse_json_text(sample_row["instruction_detail_json"])
        workflow_df = list_sample_workflow()
        workflow_match = workflow_df[workflow_df["sample_id"] == sample_id] if not workflow_df.empty else workflow_df
        workflow_row = workflow_match.iloc[0] if not workflow_match.empty else None
        op_detail = parse_json_text(workflow_row["op_detail_json"]) if workflow_row is not None and pd.notna(workflow_row["op_detail_json"]) else {}
        order_match = orders_df[orders_df["order_code"] == str(sample_row["order_code"])] if not orders_df.empty else orders_df
        order_row = order_match.iloc[0] if not order_match.empty else None
        order_detail = parse_json_text(order_row["requirement_detail_json"]) if order_row is not None else {}
        process_type = str(sample_row["process_type"] or "")
        change_label = "원화변경" if process_type == "인쇄" else "도면변경"
        change_required = (
            bool(order_detail.get("film_change_required"))
            if process_type == "인쇄"
            else bool(order_detail.get("product_drawing_change_required"))
        )
        mold_dispatch_required = bool(order_detail.get("mold_dispatch_required"))
        color_required = bool(order_detail.get("color_required"))
        raw_material_required = bool(order_detail.get("raw_material_experiment_required"))
        requirement_raw_name = " / ".join(
            [value for value in [order_detail.get("raw_material_1_label", ""), order_detail.get("raw_material_2_label", "")] if value]
        )
        requirement_change_source = _review_text(order_detail.get("drawing_change_source"), "-") if (change_required or mold_dispatch_required) else "없음"
        requirement_color_sample = _review_text(order_detail.get("color_sample_exists"), "-") if color_required else "없음"
        requirement_raw_display = _review_text(requirement_raw_name) if raw_material_required else "없음"
        instruction_mold_code = _review_text(
            instruction_detail.get("mold_code")
            or final_mold_code,
        )
        instruction_raw_name = _review_text(instruction_detail.get("raw_material_label"))
        instruction_mb_code = _review_text(sample_row.get("mb_request_code"))
        instruction_mb_ratio = (
            f"{float(instruction_detail.get('mb_ratio', 0.0)):.1f}%"
            if instruction_detail.get("mb_ratio") not in (None, "", "None")
            else "미입력"
        )
        experiment_mold_code = _review_text(sample_row.get("mold_code") or op_detail.get("mold_code"))
        experiment_raw_name = _review_text(op_detail.get("used_raw_material_label"))
        experiment_mb_code = _review_text(op_detail.get("used_mb_name") or sample_row.get("mb_request_code"))
        experiment_mb_ratio = (
            f"{float(op_detail.get('mb_ratio_pct', 0.0)):.1f}%"
            if op_detail.get("mb_ratio_pct") not in (None, "", "None")
            else "미입력"
        )
        _, display_label = _get_requirement_identity(order_detail, str(sample_row.get("item_code") or ""), str(sample_row.get("item_name") or ""))
        if display_label:
            st.caption(display_label)
        with st.expander("도면", expanded=False):
            _render_product_drawing_reference_body(item_id)
        with st.expander("요구요약", expanded=False):
            req_c1, req_c2, req_c3, req_c4 = st.columns(4)
            with req_c1:
                st.text_input("요구코드", value=_review_text(sample_row.get("order_code")), disabled=True, key="final_requirement_order_code")
            with req_c2:
                st.text_input("마일스톤", value=_review_text(sample_row.get("milestone_name")), disabled=True, key="final_requirement_milestone")
            with req_c3:
                st.text_input("납기일", value=_review_text(sample_row.get("target_due_date")), disabled=True, key="final_requirement_due_date")
            with req_c4:
                st.text_input("수량", value=_review_text(order_row["required_sample_qty"] if order_row is not None and "required_sample_qty" in order_row.index else ""), disabled=True, key="final_requirement_qty")
            req2_c1, req2_c2, req2_c3, req2_c4 = st.columns(4)
            with req2_c1:
                st.text_input("금형수정", value="있음" if mold_dispatch_required else "없음", disabled=True, key="final_requirement_mold_dispatch")
            with req2_c2:
                st.text_input("색상실험", value="있음" if color_required else "없음", disabled=True, key="final_requirement_color_required")
            with req2_c3:
                st.text_input("원료실험", value="있음" if raw_material_required else "없음", disabled=True, key="final_requirement_raw_required")
            with req2_c4:
                st.text_input(change_label, value="있음" if change_required else "없음", disabled=True, key="final_requirement_change_required")
            req3_c1, req3_c2, req3_c3 = st.columns(3)
            with req3_c1:
                st.text_input("도면/그외", value=requirement_change_source, disabled=True, key="final_requirement_drawing_source")
            with req3_c2:
                st.text_input("색상샘플", value=requirement_color_sample, disabled=True, key="final_requirement_color_sample")
            with req3_c3:
                st.text_input("원료명", value=requirement_raw_display, disabled=True, key="final_requirement_raw_names")
        with st.expander("실험/지시요약", expanded=False):
            top_c1, top_c2, top_c3 = st.columns(3)
            with top_c1:
                st.text_input("샘플코드", value=_review_text(sample_row.get("sample_code")), disabled=True, key="final_summary_sample_code")
            with top_c2:
                st.text_input("실험일", value=_review_text(sample_row.get("experiment_date")), disabled=True, key="final_summary_experiment_date")
            with top_c3:
                quality_review_date = workflow_row["quality_review_date"] if workflow_row is not None and "quality_review_date" in workflow_row.index else ""
                st.text_input("품질검토일", value=_review_text(quality_review_date), disabled=True, key="final_summary_quality_review_date")
            inst_c0, inst_c1, inst_c2, inst_c3, inst_c4 = st.columns([0.8, 1, 1, 1, 0.8])
            with inst_c0:
                st.text_input("구분", value="지시", disabled=True, key="final_instruction_row_label")
            with inst_c1:
                st.text_input("금형코드", value=instruction_mold_code, disabled=True, key="final_instruction_mold_code")
            with inst_c2:
                st.text_input("원료명", value=instruction_raw_name, disabled=True, key="final_instruction_raw_name")
            with inst_c3:
                st.text_input("MB코드", value=instruction_mb_code, disabled=True, key="final_instruction_mb_code")
            with inst_c4:
                st.text_input("%", value=instruction_mb_ratio, disabled=True, key="final_instruction_mb_ratio")
            exp_c0, exp_c1, exp_c2, exp_c3, exp_c4 = st.columns([0.8, 1, 1, 1, 0.8])
            with exp_c0:
                st.text_input("구분", value="실험", disabled=True, key="final_experiment_row_label")
            with exp_c1:
                st.text_input("금형코드", value=experiment_mold_code, disabled=True, key="final_experiment_mold_code")
            with exp_c2:
                st.text_input("원료명", value=experiment_raw_name, disabled=True, key="final_experiment_raw_name")
            with exp_c3:
                st.text_input("MB코드", value=experiment_mb_code, disabled=True, key="final_experiment_mb_code")
            with exp_c4:
                st.text_input("%", value=experiment_mb_ratio, disabled=True, key="final_experiment_mb_ratio")
        if sample_row["drawing_receipt_status"] == "미입수":
            st.warning("도면 미입수 상태입니다. 최종 상태는 '확정'으로 저장할 수 없습니다.")
        render_section_title("최종검토 입력")
        saved_final_comment = str(workflow_row["final_comment"]) if workflow_row is not None and pd.notna(workflow_row["final_comment"]) else ""
        saved_final_action = str(workflow_row["final_action"]) if workflow_row is not None and pd.notna(workflow_row["final_action"]) else ""
        saved_approval_status = str(workflow_row["approval_status"]) if workflow_row is not None and pd.notna(workflow_row["approval_status"]) else "검토중"
        final_c1, final_c2 = st.columns([1.2, 1])
        with final_c1:
            final_comment = st.text_area("문제점 및 현상", value=saved_final_comment, height=110, key="final_comment")
            final_action = st.text_area("개선사항", value=saved_final_action, height=110, key="final_action")
        with final_c2:
            final_status_options = ["검토중", "재실험", "수정지시", "표준후보", "확정"]
            approval_status = st.selectbox(
                "최종 상태",
                final_status_options,
                index=final_status_options.index(saved_approval_status) if saved_approval_status in final_status_options else 0,
                key="approval_status",
            )
        (save_clicked,) = render_page_actions([("최종검토 저장", "save_final_review", True)])
        if save_clicked:
            if sample_row["drawing_receipt_status"] == "미입수" and approval_status == "확정":
                st.error("도면 입수완료 전에는 최종 상태를 '확정'으로 저장할 수 없습니다.")
                return
            if approval_status == "확정":
                experiment_date_value = sample_row.get("experiment_date")
                checked_at_value = workflow_row.get("checked_at") if workflow_row is not None else None
                experiment_completed = bool(
                    (pd.notna(experiment_date_value) and str(experiment_date_value).strip())
                    or (pd.notna(checked_at_value) and str(checked_at_value).strip())
                )
                quality_completed = bool(
                    workflow_row is not None
                    and pd.notna(workflow_row.get("quality_review_date"))
                )
                if not experiment_completed:
                    st.error("실험 완료 전에는 최종 상태를 '확정'으로 저장할 수 없습니다.")
                    return
                if not quality_completed:
                    st.error("품질검토 완료 전에는 최종 상태를 '확정'으로 저장할 수 없습니다.")
                    return
                inspection_plan = inspection_plan_from_details(instruction_detail, order_detail)
                missing_results = required_result_issues(
                    inspection_plan,
                    parse_inspection_dict(workflow_row.get("first_measurement") if workflow_row is not None else ""),
                    parse_inspection_dict(workflow_row.get("after_24h_measurement") if workflow_row is not None else ""),
                )
                if missing_results:
                    st.error(f"필수 검사결과를 입력해 주세요: {', '.join(missing_results)}")
                    return
            final_payload: FinalReviewPayload = {
                "sample_id": sample_id,
                "final_comment": final_comment,
                "final_action": final_action,
                "approval_status": approval_status,
            }
            save_final_review(
                payload=final_payload,
                current_user_name=current_user()["user_name"],
            )
            flash_success("최종검토를 저장했습니다.")
            st.rerun()

        if sample_row["process_type"] == "사출":
            render_section_title("고객 발송")
            product_code = item_row.get("product_code", "") if item_row is not None else ""
            project_row = get_project_by_code(sample_row["project_code"])
            condition_detail = parse_json_text(workflow_row["condition_input"]) if workflow_row is not None and "condition_input" in workflow_row.index and pd.notna(workflow_row["condition_input"]) else {}
            after_24h_detail = parse_json_text(workflow_row["after_24h_measurement"]) if workflow_row is not None and pd.notna(workflow_row["after_24h_measurement"]) else {}
            second_measurement_detail = parse_json_text(workflow_row["second_measurement"]) if workflow_row is not None and pd.notna(workflow_row["second_measurement"]) else {}
            quality_comment_detail = parse_json_text(workflow_row["quality_comment"]) if workflow_row is not None and pd.notna(workflow_row["quality_comment"]) else {}
            experiment_date_text = (
                str(workflow_row["checked_at"]).split("T")[0]
                if workflow_row is not None and "checked_at" in workflow_row.index and pd.notna(workflow_row["checked_at"])
                else (sample_row["customer_delivery_date"] or "")
            )
            experimenter_text = (
                str(workflow_row["checked_by"])
                if workflow_row is not None and "checked_by" in workflow_row.index and pd.notna(workflow_row["checked_by"])
                else str(current_user().get("login_id") or current_user().get("user_name") or "")
            )
            requirement_df = list_experiment_orders()
            requirement_match = requirement_df[requirement_df["order_code"] == sample_row["order_code"]] if not requirement_df.empty else requirement_df
            requirement_row = requirement_match.iloc[0] if not requirement_match.empty else None
            requirement_detail = parse_json_text(requirement_row["requirement_detail_json"]) if requirement_row is not None and pd.notna(requirement_row["requirement_detail_json"]) else {}
            preview_html = _build_injection_customer_form_preview_html(
                sample_row=sample_row,
                item_row=item_row,
                project_row=project_row,
                experiment_date_text=experiment_date_text,
                experimenter_text=experimenter_text,
                requirement_detail=requirement_detail,
                instruction_detail=instruction_detail,
                condition_detail=condition_detail,
                op_detail=op_detail,
                after_24h_detail=after_24h_detail,
                second_measurement_detail=second_measurement_detail,
                quality_comment_detail=quality_comment_detail,
                approval_status=approval_status,
                final_comment=final_comment,
                final_action=final_action,
            )
            with st.expander("미리보기 열기", expanded=True):
                components.html(preview_html, height=1600, scrolling=True)
            report_state_key = f"customer_report_pdf_path_{sample_id}"
            pdf_name = build_injection_customer_report_pdf_filename(sample_row["sample_code"], product_code)
            if st.button("파일 저장하기(PDF)", key="final_make_customer_pdf", use_container_width=True):
                output_path = create_injection_customer_report_pdf_from_preview_html(
                    preview_html=preview_html,
                    file_name=pdf_name,
                )
                st.session_state[report_state_key] = str(output_path)
                flash_success("고객 발송용 PDF를 만들었습니다.")
                st.rerun()
            report_path = st.session_state.get(report_state_key, "")
            if report_path:
                report_file = Path(report_path)
                if report_file.exists():
                    st.caption(str(report_file))
                    with report_file.open("rb") as fp:
                        st.download_button(
                            "PDF 다운로드",
                            data=fp.read(),
                            file_name=pdf_name,
                            mime="application/pdf",
                            key=f"download_customer_pdf_{sample_id}",
                            use_container_width=True,
                        )
            with st.expander("보내기", expanded=False):
                send_c1, send_c2 = st.columns(2)
                with send_c1:
                    st.text_area(
                        "메일 본문 초안",
                        value=(
                            f"[{sample_row['sample_code']}] 사출실험 결과 전달드립니다.\n\n"
                            f"- 제품코드: {product_code or '-'}\n"
                            f"- 품명: {sample_row['item_name'] or '-'}\n"
                            f"- 금형번호: {final_mold_code or '-'}\n"
                            f"- 원료: {instruction_detail.get('raw_material_label', '-') or '-'}\n"
                            f"- MB 함량: {float(instruction_detail.get('mb_ratio', 0.0)):.1f}%\n"
                            f"- 고객 결과: {sample_row['customer_result'] or '-'}\n"
                            f"- 최종 상태: {approval_status}\n"
                        ),
                        height=180,
                        key="final_customer_mail_draft",
                    )
                with send_c2:
                    st.text_area(
                        "카톡 전달 문구",
                        value=(
                            f"{sample_row['sample_code']} / {product_code or '-'} / "
                            f"{sample_row['item_name'] or '-'} / "
                            f"MB {float(instruction_detail.get('mb_ratio', 0.0)):.1f}% / "
                            f"상태 {approval_status}"
                        ),
                        height=180,
                        key="final_customer_kakao_draft",
                    )
                st.caption("실제 메일/카톡 전송 연결은 다음 단계에서 붙입니다.")
    workflow_df = list_sample_workflow()
    if not workflow_df.empty:
        render_history_panel("이력 보기", workflow_df[["sample_code", "order_code", "item_name", "status", "customer_result", "first_action", "quality_comment", "final_action", "approval_status"]])


def render_injection_experiment_page() -> None:
    render_op_page("사출실험", True)


def render_item_requirements_page() -> None:
    render_customer_requirements_page("공정품")


def render_assembly_requirements_page() -> None:
    render_customer_requirements_page("조립품")


def render_injection_instruction_page() -> None:
    render_sample_instructions_page("사출")


def render_process_instruction_page() -> None:
    render_sample_instructions_page("공정품")


def render_assembly_instruction_page() -> None:
    page_name = "조립 실험지시"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = list_project_options()
    orders_df = list_experiment_orders()
    instructions_df = list_experiment_instructions()
    samples_df = list_experiment_samples()
    moves_df = operations_service.list_postprocess_item_moves()
    inventory_df = operations_service.list_sample_inventory()
    if not can_edit(page_name):
        return

    entry_source = str(st.session_state.get("menu_entry_source_dev") or "direct")
    restore_context = st.session_state.get("assembly_return_context")
    restore_payload = _get_assembly_restore_context()
    restore_order_id = restore_payload.get("order_id")
    restore_instruction_id = restore_payload.get("instruction_id")
    restore_item_id = restore_payload.get("item_id")
    restore_tree_node = restore_payload.get("tree_node")
    direct_visit_key = "assembly_direct_visit_token"
    current_menu_visit_token = st.session_state.get("menu_visit_token_dev")
    _log_return_context_state()
    _append_nav_trace(
        "assembly_page_entry_before_clear",
        current_menu=st.session_state.get("current_menu"),
        entry_source=entry_source,
        restore_context=restore_context,
        restore_order_id=restore_order_id,
        restore_instruction_id=restore_instruction_id,
        restore_item_id=restore_item_id,
        restore_tree_node=restore_tree_node,
        assembly_return_context=st.session_state.get("assembly_return_context"),
        assembly_restore_context=st.session_state.get("assembly_restore_context"),
        pending_nav_dev=st.session_state.get("pending_nav_dev"),
    )
    if entry_source != "pending_nav":
        if st.session_state.get(direct_visit_key) != current_menu_visit_token:
            clear_assembly_ui_state()
            clear_assembly_return_state()
            restore_context = None
            restore_payload = {}
            restore_order_id = None
            restore_instruction_id = None
            restore_item_id = None
            restore_tree_node = None
            st.session_state[direct_visit_key] = current_menu_visit_token
    elif isinstance(restore_context, dict):
        restore_project_label = restore_payload.get("project_label") or restore_context.get("project_label")
        restore_product_label = restore_payload.get("product_label") or restore_context.get("product_label")
        restore_tree_mode_value = restore_payload.get("tree_mode") or restore_context.get("tree_mode")
        restore_meta_label = restore_payload.get("meta_label") or restore_context.get("meta_label")
        restore_mode_value = restore_payload.get("mode") or restore_context.get("mode")
        if restore_project_label:
            st.session_state["assembly_instruction_project_label"] = str(restore_project_label)
        if restore_product_label:
            st.session_state["assembly_instruction_product_label"] = str(restore_product_label)
        if restore_tree_mode_value:
            st.session_state["assembly_instruction_tree_mode"] = str(restore_tree_mode_value)
        if restore_meta_label:
            st.session_state["assembly_instruction_meta_label"] = str(restore_meta_label)
        if restore_mode_value:
            st.session_state["assembly_instruction_mode"] = str(restore_mode_value)
        st.session_state[direct_visit_key] = current_menu_visit_token
        _log_return_context_state()
        clear_return_context()
        _log_return_context_state()
    _log_return_context_state()
    _append_nav_trace(
        "assembly_page_entry_after_restore",
        current_menu=st.session_state.get("current_menu"),
        entry_source=entry_source,
        restore_context=restore_context,
        restore_order_id=restore_order_id,
        restore_instruction_id=restore_instruction_id,
        restore_item_id=restore_item_id,
        restore_tree_node=restore_tree_node,
        assembly_instruction_project_label=st.session_state.get("assembly_instruction_project_label"),
        assembly_instruction_product_label=st.session_state.get("assembly_instruction_product_label"),
        assembly_instruction_tree_mode=st.session_state.get("assembly_instruction_tree_mode"),
        assembly_instruction_meta_label=st.session_state.get("assembly_instruction_meta_label"),
        assembly_instruction_mode=st.session_state.get("assembly_instruction_mode"),
        assembly_instruction_order_label=st.session_state.get("assembly_instruction_order_label"),
        assembly_instruction_pick=st.session_state.get("assembly_instruction_pick"),
        assembly_restore_context=st.session_state.get("assembly_restore_context"),
    )

    top_c1, top_c2, top_c3, top_c4, top_c5, top_c6 = st.columns([1.0, 1.0, 0.8, 1.4, 0.9, 1.4])
    assembly_project_options = [""] + [label for label, _ in projects]
    _clear_invalid_selectbox_value("assembly_instruction_project_label", assembly_project_options)
    with top_c1:
        project_label = st.selectbox("프로젝트", options=assembly_project_options, key="assembly_instruction_project_label")
    project_code = project_label.split(" | ")[0] if project_label else ""
    print(
        "[ASSEMBLY] project_selection",
        {
            "project_label_raw": project_label,
            "project_code_used": project_code,
            "project_label_repr": repr(project_label),
            "project_code_repr": repr(project_code),
        },
    )
    project_row = get_project_by_code(project_code) if project_code else None
    product_options = list_product_options_for_project(project_code) if project_code else []
    print(
        "[ASSEMBLY] product_query_result",
        {
            "project_code_used": project_code,
            "products_len": len(product_options),
            "product_options": product_options,
        },
    )
    assembly_product_options = [""] + [label for label, _ in product_options]
    active_product_id = st.session_state.get("assembly_active_product_id")
    current_product_label = str(st.session_state.get("assembly_instruction_product_label", "") or "")
    print(
        "[ASSEMBLY] product_sync",
        {
            "project_code": project_code,
            "products_len": len(product_options),
            "current_product_label": current_product_label,
            "active_product_id": active_product_id,
        },
    )
    active_product_label = next(
        (label for label, pid in product_options if active_product_id and int(pid) == int(active_product_id)),
        "",
    )
    if active_product_label and (not current_product_label or current_product_label not in assembly_product_options):
        st.session_state["assembly_instruction_product_label"] = active_product_label
    elif current_product_label and current_product_label not in assembly_product_options:
        st.session_state.pop("assembly_instruction_product_label", None)
    _clear_invalid_selectbox_value("assembly_instruction_product_label", assembly_product_options)
    with top_c2:
        product_label = st.selectbox("상품", options=assembly_product_options, key="assembly_instruction_product_label")
    selected_product_id = dict(product_options).get(product_label) if product_label else None
    print(
        "[ASSEMBLY] before_product_guard",
        {
            "project_code": project_code,
            "product_label": product_label,
            "selected_product_id": selected_product_id,
            "product_options": product_options,
        },
    )
    if selected_product_id:
        st.session_state["assembly_active_product_id"] = int(selected_product_id)
    else:
        st.session_state.pop("assembly_active_product_id", None)
    print(
        "[ASSEMBLY] product_sync_after",
        {
            "product_label": st.session_state.get("assembly_instruction_product_label"),
            "active_product_id": st.session_state.get("assembly_active_product_id"),
        },
    )
    assembly_tree_mode_options = ["기본", "조합"]
    _clear_invalid_selectbox_value("assembly_instruction_tree_mode", assembly_tree_mode_options)
    with top_c3:
        tree_mode = st.selectbox("구성 방식", options=assembly_tree_mode_options, key="assembly_instruction_tree_mode")
    meta_rows = list_meta_requirements_for_context(
        int(project_row["project_id"]) if project_row is not None and pd.notna(project_row.get("project_id")) else None,
        int(selected_product_id) if selected_product_id else None,
        tree_mode,
    ) if project_code and selected_product_id else []
    meta_options = [f"{row['meta_code']} | {row['title'] or row['tree_mode']}" for row in meta_rows]
    _clear_invalid_selectbox_value("assembly_instruction_meta_label", [""] + meta_options)
    with top_c4:
        meta_label = st.selectbox("메타", options=[""] + meta_options, key="assembly_instruction_meta_label")
    selected_meta_row = next((row for row in meta_rows if f"{row['meta_code']} | {row['title'] or row['tree_mode']}" == meta_label), None)
    selected_meta_id = int(selected_meta_row["meta_requirement_id"]) if selected_meta_row is not None else None
    assembly_mode_options = ["신규", "수정"]
    _clear_invalid_selectbox_value("assembly_instruction_mode", assembly_mode_options)
    with top_c5:
        instruction_mode = st.selectbox("모드", options=assembly_mode_options, key="assembly_instruction_mode")

    if project_code and not selected_product_id:
        st.info("상품을 먼저 선택하면 조립 메타와 지시 선택이 열립니다.")
        return
    if project_code and selected_product_id and not meta_rows:
        st.info("선택한 상품/구성 방식에 조립 메타가 없습니다. 먼저 조립품 요구를 저장해 주세요.")
        return
    if not selected_meta_id:
        st.info("조립 메타를 선택하면 상태트리와 조립 지시가 열립니다.")
        return

    active_meta_row = get_meta_requirement_row(selected_meta_id)
    root_item_id = int(active_meta_row["root_item_id"]) if active_meta_row is not None and pd.notna(active_meta_row["root_item_id"]) else None
    root_item_row = get_item_row(root_item_id) if root_item_id else None
    meta_lines = list_meta_requirement_lines(selected_meta_id)
    meta_lines_df = pd.DataFrame(meta_lines)
    root_orders_df = orders_df[
        (pd.to_numeric(orders_df["meta_requirement_id"], errors="coerce") == int(selected_meta_id))
        & (pd.to_numeric(orders_df["item_id"], errors="coerce") == int(root_item_id))
        & (orders_df["process_type"] == "조립")
    ].copy() if root_item_id and not orders_df.empty else orders_df.iloc[0:0]
    if root_orders_df.empty:
        st.warning("선택한 메타에 연결된 최종 조립 요구가 없습니다. 먼저 조립품 요구를 확인해 주세요.")
        return

    selected_order_row = None
    selected_instruction_row = None
    if instruction_mode == "신규":
        root_order_option_rows: list[tuple[str, int, tuple]] = []
        for _, row in root_orders_df.iterrows():
            order_id = int(row["experiment_order_id"])
            if not instructions_df.empty and not instructions_df[
                pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == order_id
            ].empty:
                continue
            label = _order_pick_label(row)
            sort_key = (
                str(row.get("target_due_date") or "9999-12-31"),
                str(row.get("order_code") or ""),
            )
            root_order_option_rows.append((label, order_id, sort_key))
        root_order_option_rows = sorted(root_order_option_rows, key=lambda pair: pair[2])
        root_order_options = [(label, oid) for label, oid, _ in root_order_option_rows]
        restore_order_label = next(
            (label for label, oid in root_order_options if restore_order_id and int(oid) == int(restore_order_id)),
            "",
        )
        if restore_order_label:
            st.session_state["assembly_instruction_order_label"] = restore_order_label
        _clear_invalid_selectbox_value("assembly_instruction_order_label", [""] + [label for label, _ in root_order_options])
        with top_c6:
            root_order_label = st.selectbox("조립요구", options=[""] + [label for label, _ in root_order_options], key="assembly_instruction_order_label")
        selected_order_id = dict(root_order_options).get(root_order_label) if root_order_label else None
        if not selected_order_id and restore_order_id:
            fallback_order_match = root_orders_df[pd.to_numeric(root_orders_df["experiment_order_id"], errors="coerce") == int(restore_order_id)]
            if not fallback_order_match.empty:
                selected_order_id = int(restore_order_id)
        if selected_order_id:
            order_match = root_orders_df[pd.to_numeric(root_orders_df["experiment_order_id"], errors="coerce") == int(selected_order_id)]
            selected_order_row = order_match.iloc[0] if not order_match.empty else None
    else:
        root_instruction_df = instructions_df[
            pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce").isin(
                pd.to_numeric(root_orders_df["experiment_order_id"], errors="coerce")
            )
        ].copy() if not instructions_df.empty else instructions_df
        root_instruction_options = {
            _instruction_pick_label(row): int(row["experiment_instruction_id"])
            for _, row in root_instruction_df.iterrows()
        } if not root_instruction_df.empty else {}
        restore_instruction_pick = next(
            (label for label, iid in root_instruction_options.items() if restore_instruction_id and int(iid) == int(restore_instruction_id)),
            "",
        )
        if restore_instruction_pick:
            st.session_state["assembly_instruction_pick"] = restore_instruction_pick
        _clear_invalid_selectbox_value("assembly_instruction_pick", [""] + list(root_instruction_options.keys()))
        with top_c6:
            selected_instruction_pick = st.selectbox("조립지시", options=[""] + list(root_instruction_options.keys()), key="assembly_instruction_pick")
        selected_instruction_id = root_instruction_options.get(selected_instruction_pick) if selected_instruction_pick else None
        if not selected_instruction_id and restore_instruction_id:
            fallback_instruction_match = root_instruction_df[
                pd.to_numeric(root_instruction_df["experiment_instruction_id"], errors="coerce") == int(restore_instruction_id)
            ] if not root_instruction_df.empty else root_instruction_df
            if not fallback_instruction_match.empty:
                selected_instruction_id = int(restore_instruction_id)
        if selected_instruction_id:
            instruction_match = root_instruction_df[root_instruction_df["experiment_instruction_id"] == selected_instruction_id]
            selected_instruction_row = instruction_match.iloc[0] if not instruction_match.empty else None
        if selected_instruction_row is not None:
            selected_order_id = int(selected_instruction_row["experiment_order_id"])
            order_match = root_orders_df[pd.to_numeric(root_orders_df["experiment_order_id"], errors="coerce") == selected_order_id]
            selected_order_row = order_match.iloc[0] if not order_match.empty else None

    if selected_order_row is None:
        st.info("조립요구 또는 조립지시를 선택하면 조립 실험지시가 열립니다.")
        return

    order_detail = parse_json_text(selected_order_row["requirement_detail_json"])
    selected_instruction_detail = parse_json_text(selected_instruction_row["instruction_detail_json"]) if selected_instruction_row is not None else {}

    left_col, right_col = st.columns([0.8, 2.2])
    with left_col:
        render_section_title("상태트리")
        if meta_lines_df.empty or "item_id" not in meta_lines_df.columns:
            st.info("메타에 연결된 공정품 구성이 없습니다.")
            all_child_ready = False
        else:
            if tree_mode == "조합" and active_meta_row is not None and active_meta_row["meta_code"]:
                root_tree_label = str(active_meta_row["meta_code"])
            else:
                root_tree_label = str(root_item_row.get("item_code") or "루트 조립품") if root_item_row is not None else "루트 조립품"
            root_sample_row = None
            if selected_instruction_row is not None and not samples_df.empty:
                root_samples = samples_df[
                    pd.to_numeric(samples_df["experiment_instruction_id"], errors="coerce") == int(selected_instruction_row["experiment_instruction_id"])
                ].sort_values("sample_id", ascending=False)
                root_sample_row = root_samples.iloc[0] if not root_samples.empty else None
            if root_sample_row is not None:
                root_status_text = "샘플완료"
            elif selected_instruction_row is not None:
                root_status_text = "지시완료"
            else:
                root_status_text = "지시필요"
            line_rows = meta_lines_df[pd.to_numeric(meta_lines_df["item_id"], errors="coerce") != int(root_item_id)].copy()
            if line_rows.empty:
                st.caption("체크 | 공정품코드 | 상태 | 입력")
                root_c1, root_c2, root_c3, root_c4 = st.columns([0.22, 1.2, 0.85, 0.55])
                with root_c1:
                    st.checkbox(
                        "선택",
                        value=True,
                        disabled=True,
                        key=f"assembly_instruction_root_checked_{int(selected_meta_id)}",
                        label_visibility="collapsed",
                    )
                with root_c2:
                    st.write(root_tree_label)
                with root_c3:
                    st.caption(root_status_text)
                with root_c4:
                    if st.button("입력", key=f"assembly_instruction_root_edit_{int(selected_meta_id)}", use_container_width=True):
                        st.rerun()
                st.caption("하위 공정품이 없습니다.")
                all_child_ready = False
            else:
                st.caption("체크 | 공정품코드 | 상태 | 입력")
                all_child_ready = True
                root_c1, root_c2, root_c3, root_c4 = st.columns([0.22, 1.2, 0.85, 0.55])
                with root_c1:
                    st.checkbox(
                        "선택",
                        value=True,
                        disabled=True,
                        key=f"assembly_instruction_root_checked_{int(selected_meta_id)}",
                        label_visibility="collapsed",
                    )
                with root_c2:
                    st.write(root_tree_label)
                with root_c3:
                    st.caption(root_status_text)
                with root_c4:
                    if st.button("입력", key=f"assembly_instruction_root_edit_{int(selected_meta_id)}", use_container_width=True):
                        st.rerun()
                parent_meta_line_map = {
                    int(row["meta_line_id"]): int(row["parent_meta_line_id"])
                    for _, row in line_rows.iterrows()
                    if pd.notna(row.get("meta_line_id")) and pd.notna(row.get("parent_meta_line_id"))
                }
                stock_target_parent_ids: set[int] = set()
                sorted_line_rows = line_rows.sort_values(["level_no", "line_order", "meta_line_id"])
                for _, line_row in sorted_line_rows.iterrows():
                    meta_line_id = int(line_row["meta_line_id"])
                    ancestor_meta_line_id = parent_meta_line_map.get(meta_line_id)
                    is_excluded = False
                    while ancestor_meta_line_id is not None:
                        if int(ancestor_meta_line_id) in stock_target_parent_ids:
                            is_excluded = True
                            break
                        ancestor_meta_line_id = parent_meta_line_map.get(int(ancestor_meta_line_id))
                    if is_excluded:
                        line_status = {
                            "status": "미사용",
                            "is_ready": True,
                            "is_experiment_target": False,
                            "is_stock_target": False,
                            "blocks_descendants": False,
                            "order_row": None,
                            "instruction_row": None,
                        }
                    else:
                        line_status = _assembly_line_status_info(
                            meta_line_row=line_row,
                            orders_df=orders_df,
                            instructions_df=instructions_df,
                            samples_df=samples_df,
                            moves_df=moves_df,
                            inventory_df=inventory_df,
                            meta_requirement_id=int(selected_meta_id),
                        )
                        if bool(line_status.get("blocks_descendants")) and line_status["order_row"] is not None:
                            stock_target_parent_ids.add(meta_line_id)
                    all_child_ready = all_child_ready and bool(line_status["is_ready"])
                    indent = "  " * max(int(line_row.get("level_no", 0) or 0) - 1, 0)
                    item_code_label = f"{indent}{str(line_row.get('item_code') or '-')}"
                    row_c1, row_c2, row_c3, row_c4 = st.columns([0.22, 1.2, 0.85, 0.55])
                    with row_c1:
                        st.checkbox(
                            "선택",
                            value=True,
                            disabled=True,
                            key=f"assembly_instruction_line_checked_{int(line_row['meta_line_id'])}",
                            label_visibility="collapsed",
                        )
                    with row_c2:
                        st.write(item_code_label)
                    with row_c3:
                        st.caption(str(line_status["status"]))
                    with row_c4:
                        if line_status["is_experiment_target"] and line_status["order_row"] is not None:
                            existing_instruction_locked = bool(
                                line_status["instruction_row"] is not None
                            )
                            button_label = "열기" if existing_instruction_locked else "입력"
                            if st.button(
                                button_label,
                                key=f"assembly_instruction_line_edit_{int(line_row['meta_line_id'])}",
                                use_container_width=True,
                                disabled=False,
                            ):
                                child_item_row = get_item_row(int(line_row["item_id"]))
                                child_process_type = infer_process_type_from_item(child_item_row)
                                target_instruction_scope = "사출" if child_process_type == "사출" else "공정품"
                                target_instruction_menu = "사출 실험지시" if child_process_type == "사출" else "공정품 실험지시"
                                target_keys = _instruction_scoped_keys(target_instruction_scope)
                                st.session_state["assembly_return_context"] = {
                                    "group": "개발진행",
                                    "menu": "조립 실험지시",
                                    "project_label": project_label,
                                    "product_label": product_label,
                                    "tree_mode": tree_mode,
                                    "meta_label": meta_label,
                                    "mode": instruction_mode,
                                    "order_label": root_order_label if instruction_mode == "신규" else "",
                                    "instruction_pick": selected_instruction_pick if instruction_mode == "수정" else "",
                                    "order_id": int(selected_order_id) if selected_order_id else None,
                                    "instruction_id": int(selected_instruction_row["experiment_instruction_id"]) if selected_instruction_row is not None else None,
                                    "item_id": int(line_row["item_id"]),
                                    "selected_tree_node": int(line_row["meta_line_id"]),
                                }
                                st.session_state[target_keys["entry_mode"]] = "from_assembly"
                                st.session_state["menu_entry_source_dev"] = "pending_nav"
                                st.session_state["instruction_jump_request"] = {
                                    "requirement_row_id": int(line_row["meta_line_id"]),
                                    "scope": target_instruction_scope,
                                    "instruction_mode": "수정" if line_status["instruction_row"] is not None else "신규",
                                    "read_only": bool(existing_instruction_locked),
                                }
                                st.session_state["pending_nav_dev"] = {
                                    "group": "개발진행",
                                    "menu": target_instruction_menu,
                                }
                                st.rerun()
                            if existing_instruction_locked:
                                st.caption("조회 전용 · 수정은 해당 지시 화면에서 진행")
                        elif line_status["is_stock_target"]:
                            st.caption("WMS")
                        else:
                            st.caption("-")

    with right_col:
        render_section_title("조립 지시")
        if root_item_id:
            render_product_drawing_reference(root_item_id)
        else:
            st.caption("도면 정보가 없습니다.")
        with st.expander("요구요약", expanded=True):
            summary_df = pd.DataFrame(
                [
                    {
                        "납기일": str(selected_order_row["target_due_date"] or "-"),
                        "수량": str(selected_order_row["required_sample_qty"] or "-"),
                        "마일스톤": str(selected_order_row["milestone_name"] or "-"),
                        "요구코드": str(selected_order_row["order_code"] or "-"),
                        "요구내용": _build_requirement_content_summary("조립", order_detail, selected_order_row) or "-",
                        "메타": str(active_meta_row["meta_code"]) if active_meta_row is not None else "-",
                    }
                ]
            )
            st.dataframe(summary_df, use_container_width=True, hide_index=True)
        st.caption(
            " | ".join(
                [
                    part
                    for part in [
                        str(active_meta_row["meta_code"]) if active_meta_row is not None else "",
                        str(active_meta_row["tree_mode"]) if active_meta_row is not None else "",
                        str(root_item_row.get("item_code") or "") if root_item_row is not None else "",
                        str(root_item_row.get("item_name") or "") if root_item_row is not None else "",
                    ]
                    if part
                ]
            )
            or "-"
        )
        assembly_execution_mode_ui = _execution_mode_ui_value(str(selected_instruction_detail.get("execution_mode") or "내부"))
        mode_c1, mode_c2 = st.columns([0.9, 1.4])
        with mode_c1:
            assembly_execution_mode_ui = st.selectbox(
                "실행방식",
                options=["내부", "외부"],
                index=["내부", "외부"].index(assembly_execution_mode_ui),
                key=f"assembly_root_execution_mode_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
            )
        assembly_execution_mode = _execution_mode_storage_value(assembly_execution_mode_ui)
        with mode_c2:
            vendor_name = st.text_input(
                "업체",
                value=str(selected_instruction_detail.get("vendor_name") or ("내부" if assembly_execution_mode == "내부" else "")),
                disabled=assembly_execution_mode == "내부",
                key=f"assembly_root_vendor_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
            )
        expected_receipt_date = st.date_input(
            "완료요청일",
            value=_safe_date_value(selected_instruction_detail.get("expected_receipt_date")) if selected_instruction_detail.get("expected_receipt_date") else (_safe_date_value(selected_order_row["target_due_date"]) if selected_order_row["target_due_date"] else None),
            key=f"assembly_root_expected_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
        )
        reselection_requirement_type = selected_instruction_detail.get("reselection_requirement_type", selected_instruction_detail.get("reselection_requirement", "없음"))
        reselection_requirement_type = st.selectbox(
            "업체 재선정",
            options=VENDOR_RESELECTION_OPTIONS,
            index=_select_index(VENDOR_RESELECTION_OPTIONS, reselection_requirement_type),
            key=f"assembly_root_vendor_reselection_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
        )
        reselection_requirement = st.text_input(
            "업체 재선정 기타",
            value=str(selected_instruction_detail.get("reselection_requirement_extra", "")),
            disabled=reselection_requirement_type != "기타",
            key=f"assembly_root_vendor_reselection_extra_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
        )
        if order_detail.get("assembly_function") or order_detail.get("backing_spec") or order_detail.get("sub_material_other"):
            req_c1, req_c2 = st.columns(2)
            with req_c1:
                st.text_area("기능 요구", value=str(order_detail.get("assembly_function", "")), height=88, disabled=True)
                st.text_input("바킹 규격", value=str(order_detail.get("backing_spec", "")), disabled=True)
            with req_c2:
                st.text_area("부재료 기타", value=str(order_detail.get("sub_material_other", "")), height=88, disabled=True)
        assembly_note = st.text_area(
            "지시 확인 메모",
            height=88,
            value=str(selected_instruction_detail.get("assembly_note", "")),
            key=f"assembly_root_note_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
        )
        if not all_child_ready:
            st.caption("체크된 하위 공정품이 모두 `지시완료` 또는 `출고대기/완료` 상태여야 요구완료를 체크할 수 있습니다.")
        requirement_completed = st.checkbox(
            "요구완료",
            value=bool(selected_instruction_row["requirement_completed"]) if selected_instruction_row is not None and pd.notna(selected_instruction_row["requirement_completed"]) and all_child_ready else False,
            disabled=not all_child_ready,
            key=f"assembly_root_requirement_completed_{selected_order_id}_{selected_instruction_row['experiment_instruction_id'] if selected_instruction_row is not None else 'new'}",
        )
        action_defs = [
            ("저장", "save_assembly_instruction_button", selected_instruction_row is None),
            ("수정", "update_assembly_instruction_button", selected_instruction_row is not None),
            ("삭제", "delete_assembly_instruction_button", selected_instruction_row is not None),
        ]
        save_clicked, update_clicked, delete_clicked = render_page_actions(action_defs)
        if delete_clicked and selected_instruction_row is not None:
            ok, message = delete_experiment_instruction(int(selected_instruction_row["experiment_instruction_id"]))
            if ok:
                clear_instruction_return_state()
                flash_success(message)
                st.rerun()
            st.error(message)
            return
        if save_clicked or update_clicked:
            instruction_payload: ExperimentInstructionPayload = {
                "experiment_order_id": int(selected_order_row["experiment_order_id"]),
                "project_id": int(selected_order_row["project_id"]),
                "item_id": int(root_item_id),
                "process_type": "조립",
                "required_sample_qty": _safe_int_value(selected_order_row["required_sample_qty"], 1),
                "requested_finish_date": str(expected_receipt_date) if expected_receipt_date else None,
                "machine_no": "",
                "machine_ton": "",
                "requirement_completed": bool(requirement_completed),
                "detail_payload": {
                    "execution_mode": assembly_execution_mode,
                    "vendor_name": "내부" if assembly_execution_mode == "내부" else vendor_name.strip(),
                    "reselection_requirement_type": reselection_requirement_type,
                    "reselection_requirement_extra": reselection_requirement,
                    "reselection_requirement": reselection_requirement if reselection_requirement_type == "기타" else reselection_requirement_type,
                    "expected_receipt_date": str(expected_receipt_date) if expected_receipt_date else None,
                    "assembly_note": assembly_note,
                    "meta_requirement_id": int(selected_meta_id),
                },
            }
            saved_instruction = _save_instruction_safely(
                selected_instruction_row,
                payload=instruction_payload,
                current_user_name=current_user()["user_name"],
            )
            if saved_instruction is None:
                return
            _, instruction_code, mb_request_code = saved_instruction
            clear_instruction_return_state()
            success_message = f"조립 실험지시를 저장했습니다. 코드: {instruction_code}"
            if mb_request_code:
                success_message += f" | MB의뢰 코드: {mb_request_code}"
            flash_success(success_message)
            st.rerun()


DEVELOPMENT_PAGE_RENDERERS = {
    "공정품 요구": render_item_requirements_page,
    "조립품 요구": render_assembly_requirements_page,
    "사출 실험지시": render_injection_instruction_page,
    "공정품 실험지시": render_process_instruction_page,
    "조립 실험지시": render_assembly_instruction_page,
    "실험지시": render_process_instruction_page,
    "실험": render_op_page,
    "사출실험": render_injection_experiment_page,
    "품질검토": render_quality_page,
    "최종검토": render_final_page,
}


def render_development_page(menu: str) -> bool:
    renderer = DEVELOPMENT_PAGE_RENDERERS.get(menu)
    if renderer is None:
        return False
    renderer()
    return True
