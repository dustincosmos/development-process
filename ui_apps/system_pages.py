from __future__ import annotations

from datetime import datetime
from html import escape
import json
import sqlite3

import pandas as pd
import streamlit as st

from db.runtime import execute, get_connection, hash_password, try_delete
from domain.constants import ROLE_LABELS, ROLE_MENU_GROUPS
from services.development_service import list_experiment_instructions, list_integrated_board_rows
from services.reference_data_service import (
    get_experiment_orders,
    get_experiment_samples,
    get_item_bom,
    get_items,
    get_mold_drawings,
    get_molds,
    get_print_films,
    get_products,
    get_product_drawings,
    get_projects,
    get_role_menu_permissions,
    get_roles,
    get_sample_workflow,
    get_users,
    reset_cache,
)
from services.shell_service import (
    can_edit,
    current_user,
    flash_success,
    render_dataframe,
    render_history_panel,
    render_page_actions,
    role_label_map,
    role_options,
    show_permission_hint,
)


def _board_target_scope(process_type: str) -> str:
    process_text = str(process_type or "").strip()
    if process_text == "사출":
        return "사출"
    if process_text == "조립":
        return "조립"
    return "공정품"


def _board_target_menu(process_type: str) -> str:
    scope = _board_target_scope(process_type)
    if scope == "사출":
        return "사출 실험지시"
    if scope == "조립":
        return "조립 실험지시"
    return "공정품 실험지시"


def _open_instruction_from_board(requirement_row_id: int, process_type: str) -> None:
    st.session_state["instruction_jump_request"] = {
        "requirement_row_id": int(requirement_row_id),
        "scope": _board_target_scope(process_type),
    }
    st.session_state["pending_nav_dev"] = {
        "group": "개발진행",
        "menu": _board_target_menu(process_type),
    }
    st.rerun()


def _timeline_date(value: object) -> pd.Timestamp | pd.NaT:
    if value in (None, "", "None"):
        return pd.NaT
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        return parsed.normalize() if pd.notna(parsed) else pd.NaT
    except Exception:
        return pd.NaT


def _timeline_text(value: object, default: str = "-") -> str:
    raw = "" if value is None else str(value).strip()
    return raw or default


def _timeline_flag_text(value: object) -> str:
    text = str(value or "").strip()
    if text in {"1", "True", "true", "Y", "예", "있음"}:
        return "있음"
    if text in {"0", "False", "false", "N", "아니오", "없음"}:
        return "없음"
    return text or "없음"


def _timeline_display_status(
    *,
    has_instruction: bool,
    has_sample: bool,
    experiment_date: pd.Timestamp | pd.NaT,
    quality_review_date: pd.Timestamp | pd.NaT,
    final_review_date: pd.Timestamp | pd.NaT,
    approval_status: object = None,
) -> str:
    if not has_instruction:
        return "지시 대기"
    if has_instruction and not has_sample:
        return "지시 생성"
    if has_sample and pd.isna(experiment_date):
        return "실험 대기"
    if pd.notna(experiment_date) and pd.isna(quality_review_date):
        return "품질 검토 대기"
    if pd.notna(quality_review_date) and pd.isna(final_review_date):
        return "최종검토 대기"
    status_text = str(approval_status or "").strip()
    return status_text or "최종검토"


def _timeline_status_class(status: str) -> str:
    mapping = {
        "지시 대기": "pending",
        "지시 생성": "created",
        "실험 대기": "waiting",
        "품질 검토 대기": "quality",
        "최종검토 대기": "final-wait",
        "검토중": "final-review",
        "재실험": "retest",
        "수정지시": "revise",
        "표준후보": "candidate",
        "확정": "confirmed",
        "최종검토": "final-review",
    }
    return mapping.get(str(status or "").strip(), "default")


def _build_dashboard_timeline_rows(
    project_code: str,
    product_id: int | None,
) -> tuple[list[dict[str, object]], pd.Timestamp | pd.NaT, pd.Timestamp | pd.NaT]:
    items_df = get_items()
    orders_df = get_experiment_orders()
    instructions_df = list_experiment_instructions()
    workflow_df = get_sample_workflow()

    if items_df.empty or orders_df.empty:
        return [], pd.NaT, pd.NaT

    item_filter = items_df[items_df["project_code"].astype(str) == str(project_code)].copy()
    if product_id is not None and "product_id" in item_filter.columns:
        item_filter = item_filter[pd.to_numeric(item_filter["product_id"], errors="coerce") == int(product_id)].copy()
    if item_filter.empty:
        return [], pd.NaT, pd.NaT

    valid_item_ids = set(pd.to_numeric(item_filter["item_id"], errors="coerce").dropna().astype(int).tolist())
    orders_df = orders_df[
        (orders_df["project_code"].astype(str) == str(project_code))
        & (pd.to_numeric(orders_df["item_id"], errors="coerce").isin(valid_item_ids))
    ].copy()
    if orders_df.empty:
        return [], pd.NaT, pd.NaT

    instructions_df = instructions_df[
        (instructions_df["project_code"].astype(str) == str(project_code))
        & (pd.to_numeric(instructions_df["item_id"], errors="coerce").isin(valid_item_ids))
    ].copy()
    workflow_df = workflow_df[
        (workflow_df["project_code"].astype(str) == str(project_code))
        & (pd.to_numeric(workflow_df["item_id"], errors="coerce").isin(valid_item_ids))
    ].copy()

    item_display_map = {
        int(row["item_id"]): f"{_timeline_text(row.get('item_code'))} | {_timeline_text(row.get('item_name'))}"
        for _, row in item_filter.dropna(subset=["item_id"]).iterrows()
    }

    rows: list[dict[str, object]] = []
    all_dates: list[pd.Timestamp] = []

    orders_df = orders_df.sort_values(
        by=["item_code", "requirement_date", "target_due_date", "experiment_order_id"],
        ascending=[True, True, True, True],
    )

    for item_id, item_orders in orders_df.groupby("item_id", sort=False):
        item_id_int = int(item_id)
        rows.append(
            {
                "kind": "item",
                "label": item_display_map.get(item_id_int, f"공정품 {item_id_int}"),
            }
        )
        for _, order_row in item_orders.iterrows():
            order_id = int(order_row["experiment_order_id"])
            order_code = _timeline_text(order_row.get("order_code"))
            requirement_date = _timeline_date(order_row.get("requirement_date")) or _timeline_date(order_row.get("created_at"))
            target_due_date = _timeline_date(order_row.get("target_due_date"))
            if pd.notna(requirement_date):
                all_dates.append(requirement_date)
            if pd.notna(target_due_date):
                all_dates.append(target_due_date)
            requirement_detail = {}
            raw_detail = order_row.get("requirement_detail_json")
            if raw_detail not in (None, "", "None"):
                try:
                    requirement_detail = json.loads(raw_detail) if isinstance(raw_detail, str) else dict(raw_detail)
                except Exception:
                    requirement_detail = {}

            rows.append(
                {
                    "kind": "order",
                    "label": order_code,
                }
            )

            order_instructions = instructions_df[
                pd.to_numeric(instructions_df["experiment_order_id"], errors="coerce") == order_id
            ].sort_values(by=["instruction_date", "experiment_instruction_id"], ascending=[True, True])

            if order_instructions.empty:
                display_status = _timeline_display_status(
                    has_instruction=False,
                    has_sample=False,
                    experiment_date=pd.NaT,
                    quality_review_date=pd.NaT,
                    final_review_date=pd.NaT,
                )
                rows.append(
                    {
                        "kind": "sample",
                        "label": "실험 미생성",
                        "display_status": display_status,
                        "requirement_start": requirement_date,
                        "requirement_end": target_due_date,
                        "instruction_date": pd.NaT,
                        "planned_date": pd.NaT,
                        "experiment_date": pd.NaT,
                        "requirement_hover": (
                            f"요구코드: {order_code}\n"
                            f"요구일: {_timeline_text(order_row.get('requirement_date'))}\n"
                            f"납기일: {_timeline_text(order_row.get('target_due_date'))}\n"
                            f"수량: {_timeline_text(order_row.get('required_sample_qty'))}\n"
                            f"마일스톤: {_timeline_text(order_row.get('milestone_name'))}\n"
                            f"금형수정: {_timeline_flag_text(requirement_detail.get('mold_change_required') or order_row.get('mold_pre_update'))}\n"
                            f"색상실험: {_timeline_flag_text(requirement_detail.get('color_required'))}\n"
                            f"원료실험: {_timeline_flag_text(requirement_detail.get('raw_material_experiment_required'))}\n"
                            f"현재상태: {display_status}"
                        ),
                        "instruction_hover": "지시 미생성",
                        "experiment_hover": "실험 미생성",
                    }
                )
                continue

            for _, instruction_row in order_instructions.iterrows():
                instruction_id = int(instruction_row["experiment_instruction_id"])
                instruction_code = _timeline_text(instruction_row.get("instruction_code"))
                instruction_date = _timeline_date(instruction_row.get("instruction_date")) or _timeline_date(instruction_row.get("created_at"))
                planned_date = _timeline_date(instruction_row.get("requested_finish_date"))
                if pd.notna(instruction_date):
                    all_dates.append(instruction_date)
                if pd.notna(planned_date):
                    all_dates.append(planned_date)

                rows.append(
                    {
                        "kind": "instruction",
                        "label": instruction_code,
                    }
                )

                instruction_samples = workflow_df[
                    pd.to_numeric(workflow_df["experiment_instruction_id"], errors="coerce") == instruction_id
                ].sort_values(by=["experiment_date", "sample_id"], ascending=[True, True])

                if instruction_samples.empty:
                    display_status = _timeline_display_status(
                        has_instruction=True,
                        has_sample=False,
                        experiment_date=pd.NaT,
                        quality_review_date=pd.NaT,
                        final_review_date=pd.NaT,
                    )
                    rows.append(
                        {
                            "kind": "sample",
                            "label": "실험 미생성",
                            "display_status": display_status,
                            "requirement_start": requirement_date,
                            "requirement_end": target_due_date,
                            "instruction_date": instruction_date,
                            "planned_date": planned_date,
                            "experiment_date": pd.NaT,
                            "requirement_hover": (
                                f"요구코드: {order_code}\n"
                                f"요구일: {_timeline_text(order_row.get('requirement_date'))}\n"
                                f"납기일: {_timeline_text(order_row.get('target_due_date'))}\n"
                                f"수량: {_timeline_text(order_row.get('required_sample_qty'))}\n"
                                f"마일스톤: {_timeline_text(order_row.get('milestone_name'))}\n"
                                f"현재상태: {display_status}"
                            ),
                            "instruction_hover": (
                                f"지시코드: {instruction_code}\n"
                                f"지시일: {_timeline_text(instruction_row.get('instruction_date'))}\n"
                                f"실험예정일: {_timeline_text(instruction_row.get('requested_finish_date'))}\n"
                                f"상태: {_timeline_text(instruction_row.get('status'))}"
                            ),
                            "experiment_hover": "실험 미생성",
                        }
                    )
                    continue

                for _, sample_row in instruction_samples.iterrows():
                    experiment_date = _timeline_date(sample_row.get("experiment_date"))
                    quality_review_date = _timeline_date(sample_row.get("quality_review_date"))
                    final_review_date = _timeline_date(sample_row.get("final_review_date"))
                    approval_status = sample_row.get("approval_status")
                    display_status = _timeline_display_status(
                        has_instruction=True,
                        has_sample=True,
                        experiment_date=experiment_date,
                        quality_review_date=quality_review_date,
                        final_review_date=final_review_date,
                        approval_status=approval_status,
                    )
                    if pd.notna(experiment_date):
                        all_dates.append(experiment_date)
                    if pd.notna(quality_review_date):
                        all_dates.append(quality_review_date)
                    if pd.notna(final_review_date):
                        all_dates.append(final_review_date)
                    rows.append(
                        {
                            "kind": "sample",
                            "label": _timeline_text(sample_row.get("sample_code")),
                            "display_status": display_status,
                            "requirement_start": requirement_date,
                            "requirement_end": target_due_date,
                            "instruction_date": instruction_date,
                            "planned_date": planned_date,
                            "experiment_date": experiment_date,
                            "requirement_hover": (
                                f"요구코드: {order_code}\n"
                                f"요구일: {_timeline_text(order_row.get('requirement_date'))}\n"
                                f"납기일: {_timeline_text(order_row.get('target_due_date'))}\n"
                                f"수량: {_timeline_text(order_row.get('required_sample_qty'))}\n"
                                f"마일스톤: {_timeline_text(order_row.get('milestone_name'))}\n"
                                f"금형수정: {_timeline_flag_text(requirement_detail.get('mold_change_required') or order_row.get('mold_pre_update'))}\n"
                                f"색상실험: {_timeline_flag_text(requirement_detail.get('color_required'))}\n"
                                f"원료실험: {_timeline_flag_text(requirement_detail.get('raw_material_experiment_required'))}\n"
                                f"현재상태: {display_status}"
                            ),
                            "instruction_hover": (
                                f"지시코드: {instruction_code}\n"
                                f"지시일: {_timeline_text(instruction_row.get('instruction_date'))}\n"
                                f"실험예정일: {_timeline_text(instruction_row.get('requested_finish_date'))}\n"
                                f"상태: {_timeline_text(instruction_row.get('status'))}\n"
                                f"현재단계: {display_status}"
                            ),
                            "experiment_hover": (
                                f"샘플코드: {_timeline_text(sample_row.get('sample_code'))}\n"
                                f"실험일: {_timeline_text(sample_row.get('experiment_date'))}\n"
                                f"품질검토일: {_timeline_text(sample_row.get('quality_review_date'))}\n"
                                f"최종검토일: {_timeline_text(sample_row.get('final_review_date'))}\n"
                                f"상태: {_timeline_text(sample_row.get('status'))}\n"
                                f"현재단계: {display_status}"
                            ),
                        }
                    )

    if not all_dates:
        return rows, pd.NaT, pd.NaT

    min_date = min(all_dates)
    max_date = max(all_dates)
    if min_date == max_date:
        min_date = min_date - pd.Timedelta(days=3)
        max_date = max_date + pd.Timedelta(days=3)
    else:
        min_date = min_date - pd.Timedelta(days=1)
        max_date = max_date + pd.Timedelta(days=1)
    return rows, min_date, max_date


def _timeline_percent(value: pd.Timestamp | pd.NaT, min_date: pd.Timestamp, max_date: pd.Timestamp) -> float:
    if pd.isna(value):
        return 0.0
    total = max((max_date - min_date).days, 1)
    return max(0.0, min(100.0, ((value - min_date).days / total) * 100.0))


def _project_milestones_from_row(project_row: pd.Series | None) -> list[dict[str, object]]:
    if project_row is None:
        return []
    mappings = [
        ("T0", project_row.get("t0_date")),
        ("T1", project_row.get("t1_date")),
        ("생산계획", project_row.get("production_plan_date")),
        ("신제품시험", project_row.get("new_product_test_due_date")),
        ("표준획득", project_row.get("standard_due_date")),
        ("출시", project_row.get("launch_date")),
        ("포장", project_row.get("packaging_date")),
    ]
    milestones: list[dict[str, object]] = []
    for label, raw_value in mappings:
        ts = _timeline_date(raw_value)
        if pd.notna(ts):
            milestones.append(
                {
                    "label": label,
                    "date": ts,
                    "text": _timeline_text(raw_value),
                }
            )
    return milestones


def _project_period_from_row(project_row: pd.Series | None) -> dict[str, object] | None:
    if project_row is None:
        return None
    start_date = _timeline_date(project_row.get("t0_date"))
    end_date = _timeline_date(project_row.get("launch_date"))
    if pd.isna(start_date) or pd.isna(end_date):
        return None
    return {
        "label": _timeline_text(project_row.get("project_code")),
        "start": start_date,
        "end": end_date,
        "hover": (
            f"프로젝트: {_timeline_text(project_row.get('project_code'))}\n"
            f"T0일: {_timeline_text(project_row.get('t0_date'))}\n"
            f"T1일: {_timeline_text(project_row.get('t1_date'))}\n"
            f"생산계획일: {_timeline_text(project_row.get('production_plan_date'))}\n"
            f"신제품시험 목표일: {_timeline_text(project_row.get('new_product_test_due_date'))}\n"
            f"표준획득 목표일: {_timeline_text(project_row.get('standard_due_date'))}\n"
            f"포장일: {_timeline_text(project_row.get('packaging_date'))}\n"
            f"출시일: {_timeline_text(project_row.get('launch_date'))}"
        ),
    }


def _render_dashboard_timeline(
    rows: list[dict[str, object]],
    min_date: pd.Timestamp,
    max_date: pd.Timestamp,
    project_milestones: list[dict[str, object]] | None = None,
    project_period: dict[str, object] | None = None,
) -> None:
    if not rows or pd.isna(min_date) or pd.isna(max_date):
        st.info("표시할 진행 데이터가 없습니다.")
        return

    tick_dates = pd.date_range(min_date, max_date, periods=8)
    axis_html = "".join(
        f"<div class='tick' style='left:{_timeline_percent(ts, min_date, max_date):.2f}%'><span>{escape(ts.strftime('%m/%d'))}</span></div>"
        for ts in tick_dates
    )
    project_milestones = project_milestones or []
    row_html_parts: list[str] = []
    if project_period and pd.notna(project_period.get("start")) and pd.notna(project_period.get("end")):
        project_start_pct = _timeline_percent(project_period["start"], min_date, max_date)
        project_end_pct = _timeline_percent(project_period["end"], min_date, max_date)
        project_width_pct = max(project_end_pct - project_start_pct, 1.2)
        period_hover = escape(str(project_period.get("hover") or "")).replace("\n", "&#10;")
        milestone_markers = "".join(
            (
                f"<span class='marker marker-project' title='{escape(str(ms['label']))}: {escape(str(ms['text']))}' "
                f"style='left:{_timeline_percent(ms['date'], min_date, max_date):.2f}%'></span>"
            )
            for ms in project_milestones
            if pd.notna(ms.get("date"))
        )
        row_html_parts.append(
            "<div class='tl-row tl-project'>"
            "<div class='tl-label'>프로젝트</div>"
            "<div class='tl-track'>"
            f"<div class='project-bar' title='{period_hover}' style='left:{project_start_pct:.2f}%; width:{project_width_pct:.2f}%'></div>"
            f"{milestone_markers}"
            "</div>"
            "</div>"
        )
    for row in rows:
        kind = str(row.get("kind") or "")
        label = escape(str(row.get("label") or ""))
        if kind == "item":
            row_html_parts.append(
                f"<div class='tl-row tl-item'><div class='tl-label'>{label}</div><div class='tl-track'></div></div>"
            )
            continue
        if kind == "order":
            row_html_parts.append(
                f"<div class='tl-row tl-order'><div class='tl-label'>{label}</div><div class='tl-track'></div></div>"
            )
            continue
        if kind == "instruction":
            row_html_parts.append(
                f"<div class='tl-row tl-instruction'><div class='tl-label'>{label}</div><div class='tl-track'></div></div>"
            )
            continue

        display_status = str(row.get("display_status") or "").strip()
        status_class = _timeline_status_class(display_status)
        start = row.get("requirement_start")
        end = row.get("requirement_end")
        start_pct = _timeline_percent(start, min_date, max_date)
        end_pct = _timeline_percent(end, min_date, max_date)
        width_pct = max(end_pct - start_pct, 1.2 if pd.notna(start) and pd.notna(end) else 0.0)
        requirement_hover = escape(str(row.get("requirement_hover") or "")).replace("\n", "&#10;")
        instruction_hover = escape(str(row.get("instruction_hover") or "")).replace("\n", "&#10;")
        experiment_hover = escape(str(row.get("experiment_hover") or "")).replace("\n", "&#10;")

        markers = []
        instruction_date = row.get("instruction_date")
        planned_date = row.get("planned_date")
        experiment_date = row.get("experiment_date")
        if pd.notna(instruction_date):
            markers.append(
                f"<span class='marker marker-inst' title='{instruction_hover}' style='left:{_timeline_percent(instruction_date, min_date, max_date):.2f}%'></span>"
            )
        if pd.notna(planned_date):
            markers.append(
                f"<span class='marker marker-plan' title='{instruction_hover}' style='left:{_timeline_percent(planned_date, min_date, max_date):.2f}%'></span>"
            )
        if pd.notna(experiment_date):
            markers.append(
                f"<span class='marker marker-exp' title='{experiment_hover}' style='left:{_timeline_percent(experiment_date, min_date, max_date):.2f}%'></span>"
            )
        row_html_parts.append(
            "<div class='tl-row tl-sample'>"
            "<div class='tl-label'>"
            f"<span class='sample-code'>{label}</span>"
            f"<span class='state-badge state-{status_class}'>{escape(display_status or '-')}</span>"
            "</div>"
            "<div class='tl-track'>"
            f"<div class='req-bar' title='{requirement_hover}' style='left:{start_pct:.2f}%; width:{width_pct:.2f}%'></div>"
            f"{''.join(markers)}"
            "</div>"
            "</div>"
        )

    html = f"""
    <style>
      .timeline-wrap {{
        border: 1px solid #d9dee8;
        border-radius: 14px;
        background: #ffffff;
        padding: 14px 14px 10px 14px;
      }}
      .timeline-scroll {{
        overflow-x: auto;
      }}
      .timeline-inner {{
        min-width: 1100px;
      }}
      .tl-axis {{
        position: relative;
        margin-left: 340px;
        height: 34px;
        border-bottom: 1px solid #e5e7eb;
        margin-bottom: 8px;
      }}
      .tl-axis .tick {{
        position: absolute;
        top: 0;
        transform: translateX(-50%);
        height: 100%;
        border-left: 1px dashed #d1d5db;
      }}
      .tl-axis .tick span {{
        position: absolute;
        top: 0;
        left: 4px;
        font-size: 11px;
        color: #6b7280;
        white-space: nowrap;
      }}
      .tl-row {{
        display: grid;
        grid-template-columns: 340px 1fr;
        align-items: center;
        min-height: 30px;
      }}
      .tl-label {{
        padding: 4px 10px 4px 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .tl-item .tl-label {{
        font-weight: 700;
        color: #111827;
        padding-top: 12px;
      }}
      .tl-order .tl-label {{
        padding-left: 18px;
        font-weight: 600;
        color: #374151;
      }}
      .tl-instruction .tl-label {{
        padding-left: 36px;
        color: #4b5563;
      }}
      .tl-sample .tl-label {{
        padding-left: 56px;
        color: #1f2937;
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 8px;
      }}
      .sample-code {{
        min-width: 0;
      }}
      .state-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        white-space: nowrap;
      }}
      .state-pending {{ background:#f3f4f6; color:#374151; }}
      .state-created {{ background:#dbeafe; color:#1d4ed8; }}
      .state-waiting {{ background:#fef3c7; color:#92400e; }}
      .state-quality {{ background:#dcfce7; color:#166534; }}
      .state-final-wait {{ background:#ede9fe; color:#6d28d9; }}
      .state-final-review {{ background:#e0e7ff; color:#3730a3; }}
      .state-retest {{ background:#fee2e2; color:#b91c1c; }}
      .state-revise {{ background:#ffedd5; color:#c2410c; }}
      .state-candidate {{ background:#d1fae5; color:#065f46; }}
      .state-confirmed {{ background:#dbeafe; color:#0f172a; }}
      .state-default {{ background:#f3f4f6; color:#374151; }}
      .tl-project .tl-label {{
        font-weight: 700;
        color: #4c1d95;
        padding-bottom: 6px;
      }}
      .tl-track {{
        position: relative;
        height: 28px;
      }}
      .tl-project .tl-track {{
        height: 34px;
      }}
      .tl-sample .tl-track {{
        border-bottom: 1px solid #f3f4f6;
      }}
      .project-bar {{
        position: absolute;
        top: 12px;
        height: 10px;
        border-radius: 999px;
        background: linear-gradient(90deg, #ddd6fe 0%, #a78bfa 100%);
      }}
      .req-bar {{
        position: absolute;
        top: 10px;
        height: 8px;
        border-radius: 999px;
        background: linear-gradient(90deg, #d1d5db 0%, #9ca3af 100%);
      }}
      .marker {{
        position: absolute;
        top: 6px;
        transform: translateX(-50%);
      }}
      .marker-inst {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: #2563eb;
        box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18);
      }}
      .marker-plan {{
        width: 0;
        height: 0;
        border-left: 6px solid transparent;
        border-right: 6px solid transparent;
        border-bottom: 10px solid #f59e0b;
      }}
      .marker-exp {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: #16a34a;
        box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.18);
      }}
      .marker-project {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: #7c3aed;
        box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.18);
        top: 9px;
      }}
      .legend {{
        display: flex;
        gap: 18px;
        align-items: center;
        font-size: 12px;
        color: #4b5563;
        margin: 0 0 10px 340px;
        flex-wrap: wrap;
      }}
      .legend-dot, .legend-bar, .legend-tri {{
        display: inline-block;
        vertical-align: middle;
        margin-right: 6px;
      }}
      .legend-bar {{
        width: 24px;
        height: 8px;
        border-radius: 999px;
        background: #9ca3af;
      }}
      .legend-dot.blue {{
        width: 10px; height: 10px; border-radius: 999px; background: #2563eb;
      }}
      .legend-dot.green {{
        width: 10px; height: 10px; border-radius: 999px; background: #16a34a;
      }}
      .legend-dot.purple {{
        width: 10px; height: 10px; border-radius: 999px; background: #7c3aed;
      }}
      .legend-tri {{
        width: 0; height: 0;
        border-left: 6px solid transparent;
        border-right: 6px solid transparent;
        border-bottom: 10px solid #f59e0b;
      }}
    </style>
    <div class="timeline-wrap">
      <div class="timeline-scroll">
        <div class="timeline-inner">
          <div class="legend">
            <span><span class="legend-bar" style="background:#a78bfa;"></span>프로젝트 기간</span>
            <span><span class="legend-dot purple"></span>프로젝트 일정</span>
            <span><span class="legend-bar"></span>요구구간</span>
            <span><span class="legend-dot blue"></span>지시</span>
            <span><span class="legend-tri"></span>실험예정</span>
            <span><span class="legend-dot green"></span>실험완료</span>
          </div>
          <div class="tl-axis">{axis_html}</div>
          {''.join(row_html_parts)}
        </div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_dashboard() -> None:
    page_name = "대시보드"
    st.subheader("현황조회")
    show_permission_hint(page_name)
    projects = get_projects()
    if projects.empty:
        st.info("등록된 프로젝트가 없습니다.")
        return

    project_options = [""] + projects.apply(lambda row: f"{row['project_code']} | {row['product_name']}", axis=1).tolist()
    top_c1, top_c2 = st.columns([1.2, 1.2])
    with top_c1:
        selected_project_label = st.selectbox("프로젝트", options=project_options, key="integrated_board_project_label")
    selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
    if not selected_project_code:
        st.info("프로젝트를 선택하면 진행 현황 그래프가 표시됩니다.")
        return

    products_df = get_products()
    project_row = projects[projects["project_code"].astype(str) == selected_project_code]
    selected_project_id = int(project_row.iloc[0]["project_id"]) if not project_row.empty and "project_id" in project_row.columns else None
    if selected_project_id is not None and not products_df.empty:
        product_candidates = products_df[pd.to_numeric(products_df["project_id"], errors="coerce") == selected_project_id].copy()
    else:
        product_candidates = pd.DataFrame()

    product_filter_options = [""]
    product_map: dict[str, int] = {}
    if not product_candidates.empty:
        for _, row in product_candidates.sort_values(["product_code", "product_name"]).iterrows():
            label = f"{_timeline_text(row.get('product_code'))} | {_timeline_text(row.get('product_name'))}"
            product_filter_options.append(label)
            product_map[label] = int(row["product_id"])
    with top_c2:
        selected_product_filter = st.selectbox("상품", options=product_filter_options, key="integrated_board_product_label")
    selected_product_id = product_map.get(selected_product_filter) if selected_product_filter else None
    selected_project_title = selected_project_label or selected_project_code
    selected_project_detail = project_row.iloc[0] if not project_row.empty else None
    project_milestones = _project_milestones_from_row(selected_project_detail)
    project_period = _project_period_from_row(selected_project_detail)

    rows, min_date, max_date = _build_dashboard_timeline_rows(
        project_code=selected_project_code,
        product_id=selected_product_id,
    )
    if not rows:
        st.info("현재 선택 범위에 표시할 요구/지시/실험 데이터가 없습니다.")
        return
    if project_period and pd.notna(project_period.get("start")) and pd.notna(project_period.get("end")):
        min_date = project_period["start"] - pd.Timedelta(days=1)
        max_date = project_period["end"] + pd.Timedelta(days=1)
    elif project_milestones:
        milestone_dates = [ms["date"] for ms in project_milestones if pd.notna(ms.get("date"))]
        if milestone_dates:
            milestone_min = min(milestone_dates)
            milestone_max = max(milestone_dates)
            if pd.isna(min_date) or milestone_min < min_date:
                min_date = milestone_min - pd.Timedelta(days=1)
            if pd.isna(max_date) or milestone_max > max_date:
                max_date = milestone_max + pd.Timedelta(days=1)
    _render_dashboard_timeline(
        rows,
        min_date,
        max_date,
        project_milestones=project_milestones,
        project_period=project_period,
    )


def render_structure_page() -> None:
    page_name = "구조조회"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects_df = get_projects()
    products_df = get_products()
    if projects_df.empty:
        st.info("등록된 프로젝트가 없습니다.")
        return

    project_labels = projects_df.apply(lambda row: f"{row['project_code']} | {row['product_name']}", axis=1).tolist()
    selected_label = st.selectbox("프로젝트 선택", options=project_labels)
    project_row = projects_df[projects_df.apply(lambda row: f"{row['project_code']} | {row['product_name']}", axis=1) == selected_label].iloc[0]
    project_code = project_row["project_code"]
    project_products = products_df[products_df["project_id"] == project_row["project_id"]].copy() if not products_df.empty else pd.DataFrame()
    product_code_text = ", ".join(
        sorted(
            {
                str(row["product_code"]).strip()
                for _, row in project_products.iterrows()
                if str(row.get("product_code") or "").strip()
            }
        )
    ) or "-"

    st.markdown("**프로젝트 개요**")
    overview = pd.DataFrame(
        [
            {
                "프로젝트코드": project_row["project_code"],
                "상품코드": product_code_text,
                "고객": project_row["customer_name"],
                "제품명": project_row["product_name"],
                "개발형태": project_row["development_type"],
                "상태": project_row["status"],
                "영업": project_row["sales_owner"],
                "개발": project_row["developer_owner"],
            }
        ]
    )
    render_dataframe(overview)

    drawings = get_product_drawings()
    mold_drawings = get_mold_drawings()
    molds = get_molds()
    items = get_items()
    bom = get_item_bom()
    films = get_print_films()
    orders = get_experiment_orders()
    samples = get_experiment_samples()
    workflow = get_sample_workflow()

    section1, section2 = st.columns(2)
    with section1:
        st.markdown("**제품도면**")
        df = drawings[drawings["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**금형도면**")
        df = mold_drawings[mold_drawings["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**금형**")
        df = molds[molds["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

    with section2:
        st.markdown("**공정품**")
        df = items[items["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**제품구성**")
        df = bom[bom["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**원화**")
        df = films[films["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**고객요구**")
        df = orders[orders["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**실험지시**")
        df = samples[samples["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df)

        st.markdown("**검토 진행상태**")
        df = workflow[workflow["project_code"] == project_code]
        if df.empty:
            st.caption("등록 없음")
        else:
            render_dataframe(df[["sample_code", "status", "first_action", "quality_comment", "final_action", "approval_status"]])


def render_users_page() -> None:
    page_name = "사용자관리"
    st.subheader(page_name)
    show_permission_hint(page_name)
    df = get_users()
    role_choice_pairs = role_options(include_inactive=True)
    role_choice_codes = [code for code, _ in role_choice_pairs]
    role_labels = role_label_map()
    if can_edit(page_name):
        labels = ["신규 등록"]
        if not df.empty:
            labels += df.apply(lambda row: f"{row['login_id']} | {row['user_name']}", axis=1).tolist()
        selected_label = st.selectbox("사용자 선택", options=labels, key="user_pick_label")
        selected_row = None
        if selected_label != "신규 등록":
            selected_row = df[df.apply(lambda row: f"{row['login_id']} | {row['user_name']}", axis=1) == selected_label].iloc[0]
        with st.form("user_form"):
            c1, c2 = st.columns(2)
            with c1:
                login_id = st.text_input("로그인 ID", value=selected_row["login_id"] if selected_row is not None else "")
                user_name = st.text_input("이름", value=selected_row["user_name"] if selected_row is not None else "")
                password = st.text_input("초기 비밀번호", type="password")
            with c2:
                department = st.text_input("부서", value=selected_row["department"] if selected_row is not None and pd.notna(selected_row["department"]) else "")
                selected_role_codes = []
                if selected_row is not None and "role_codes" in selected_row.index and pd.notna(selected_row["role_codes"]) and str(selected_row["role_codes"]).strip():
                    selected_role_codes = [code for code in str(selected_row["role_codes"]).split(",") if code in role_choice_codes]
                elif selected_row is not None and selected_row["role_code"] in role_choice_codes:
                    selected_role_codes = [selected_row["role_code"]]
                role_codes = st.multiselect(
                    "역할",
                    options=role_choice_codes,
                    default=selected_role_codes,
                    format_func=lambda x: role_labels.get(x, x),
                )
                is_active = st.checkbox("사용 여부", value=bool(selected_row["is_active"]) if selected_row is not None and pd.notna(selected_row["is_active"]) else True)
            save_clicked = st.form_submit_button("사용자 저장")
            delete_clicked = st.form_submit_button("삭제") if selected_row is not None else False
            if delete_clicked and selected_row is not None:
                ok, message = try_delete("DELETE FROM users WHERE user_id = ?", (int(selected_row["user_id"]),))
                if ok:
                    reset_cache()
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                login_id = login_id.strip()
                user_name = user_name.strip()
                department = department.strip()
                if not login_id or not user_name:
                    st.error("로그인 ID와 이름은 필수입니다.")
                elif not role_codes:
                    st.error("역할을 하나 이상 선택해 주세요.")
                else:
                    target_user_id = int(selected_row["user_id"]) if selected_row is not None else None
                    with get_connection() as conn:
                        duplicate_row = conn.execute(
                            "SELECT user_id FROM users WHERE login_id = ?",
                            (login_id,),
                        ).fetchone()
                    if duplicate_row is not None and (target_user_id is None or int(duplicate_row["user_id"]) != target_user_id):
                        st.error("로그인 ID는 이미 사용 중입니다.")
                    elif selected_row is None and not password:
                        st.error("신규 사용자는 초기 비밀번호가 필요합니다.")
                    else:
                        try:
                            if selected_row is None:
                                created_at = datetime.now().isoformat(timespec="seconds")
                                execute(
                                    """
                                    INSERT INTO users (login_id, user_name, password_hash, role_code, department, is_active, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        login_id,
                                        user_name,
                                        hash_password(password),
                                        role_codes[0],
                                        department,
                                        1 if is_active else 0,
                                        created_at,
                                    ),
                                )
                                with get_connection() as conn:
                                    created_row = conn.execute(
                                        "SELECT user_id FROM users WHERE login_id = ?",
                                        (login_id,),
                                    ).fetchone()
                                if created_row is None:
                                    st.error("사용자 저장 후 조회에 실패했습니다.")
                                    return
                                target_user_id = int(created_row["user_id"])
                            else:
                                if password:
                                    execute(
                                        """
                                        UPDATE users
                                        SET login_id = ?, user_name = ?, password_hash = ?, role_code = ?, department = ?, is_active = ?
                                        WHERE user_id = ?
                                        """,
                                        (
                                            login_id,
                                            user_name,
                                            hash_password(password),
                                            role_codes[0],
                                            department,
                                            1 if is_active else 0,
                                            target_user_id,
                                        ),
                                    )
                                else:
                                    execute(
                                        """
                                        UPDATE users
                                        SET login_id = ?, user_name = ?, role_code = ?, department = ?, is_active = ?
                                        WHERE user_id = ?
                                        """,
                                        (
                                            login_id,
                                            user_name,
                                            role_codes[0],
                                            department,
                                            1 if is_active else 0,
                                            target_user_id,
                                        ),
                                    )

                            execute("DELETE FROM user_roles WHERE user_id = ?", (target_user_id,))
                            for role_code in role_codes:
                                execute(
                                    "INSERT OR IGNORE INTO user_roles (user_id, role_code, created_at) VALUES (?, ?, ?)",
                                    (target_user_id, role_code, datetime.now().isoformat(timespec="seconds")),
                                )
                            reset_cache()
                            flash_success("사용자를 저장했습니다." if selected_row is None else "사용자를 수정했습니다.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("로그인 ID는 이미 사용 중입니다.")
    if not df.empty:
        render_dataframe(df)


def render_role_management_page() -> None:
    page_name = "역할관리"
    st.subheader(page_name)
    show_permission_hint(page_name)
    if st.session_state.pop("role_manage_reset_pending", False):
        st.session_state["role_manage_mode"] = "신규 등록"
        st.session_state.pop("role_manage_selected_code", None)
        st.session_state.pop("role_manage_role_code", None)
        st.session_state.pop("role_manage_role_name", None)
        st.session_state.pop("role_manage_is_active", None)
    roles_df = get_roles()
    permissions_df = get_role_menu_permissions()
    if not can_edit(page_name):
        st.info("역할관리는 관리자만 수정할 수 있습니다.")
        if not roles_df.empty:
            render_dataframe(roles_df)
        return

    mode_options = ["신규 등록", "기존 역할 수정"]
    top_c1, top_c2, top_c3 = st.columns([1, 1.3, 0.8])
    with top_c1:
        role_manage_mode = st.radio("등록 모드", mode_options, key="role_manage_mode", horizontal=True)

    role_pairs = role_options(include_inactive=True)
    role_labels = role_label_map()
    selected_role_code = ""
    selected_role_row = None
    with top_c2:
        if role_manage_mode == "기존 역할 수정" and role_pairs:
            selected_role_code = st.selectbox(
                "역할 선택",
                options=[code for code, _ in role_pairs],
                format_func=lambda code: f"{code} | {role_labels.get(code, code)}",
                key="role_manage_selected_code",
            )
        else:
            st.selectbox("역할 선택", options=[""], disabled=True, key="role_manage_selected_code_disabled")
    if selected_role_code and not roles_df.empty:
        matched = roles_df[roles_df["role_code"].astype(str) == str(selected_role_code)]
        if not matched.empty:
            selected_role_row = matched.iloc[0]
    with top_c3:
        status_label = "기존 수정" if selected_role_row is not None else "신규 등록"
        st.text_input("등록 상태", value=status_label, disabled=True, key="role_manage_status")

    default_role_code = str(selected_role_row["role_code"]) if selected_role_row is not None else ""
    default_role_name = str(selected_role_row["role_name"]) if selected_role_row is not None else ""
    default_is_active = bool(selected_role_row["is_active"]) if selected_role_row is not None and pd.notna(selected_role_row["is_active"]) else True
    info_c1, info_c2, info_c3 = st.columns(3)
    with info_c1:
        role_code = st.text_input("역할코드", value=default_role_code, disabled=selected_role_row is not None, key="role_manage_role_code")
    with info_c2:
        role_name = st.text_input("역할명", value=default_role_name, key="role_manage_role_name")
    with info_c3:
        is_active = st.checkbox("사용 여부", value=default_is_active, key="role_manage_is_active")

    current_enabled = set()
    if selected_role_code and not permissions_df.empty:
        current_enabled = {
            (str(row["menu_group"]), str(row["menu_name"]))
            for _, row in permissions_df[
                (permissions_df["role_code"].astype(str) == str(selected_role_code))
                & (permissions_df["is_enabled"] == 1)
            ].iterrows()
        }
    bulk_selection_state = st.session_state.pop("role_menu_bulk_state", None)
    if bulk_selection_state == "all":
        current_enabled = {
            (menu_group, menu_name)
            for menu_group, menu_names in ROLE_MENU_GROUPS.items()
            for menu_name in menu_names
        }
    elif bulk_selection_state == "none":
        current_enabled = set()

    st.markdown("**메뉴 권한**")
    header_c1, header_c2, header_c3 = st.columns([1.1, 1.7, 0.6])
    with header_c1:
        st.caption("메뉴그룹")
    with header_c2:
        st.caption("메뉴명")
    with header_c3:
        st.caption("활성화")

    selected_menu_pairs: list[tuple[str, str]] = []
    for menu_group, menu_names in ROLE_MENU_GROUPS.items():
        for menu_name in menu_names:
            row_c1, row_c2, row_c3 = st.columns([1.1, 1.7, 0.6])
            with row_c1:
                st.write(menu_group)
            with row_c2:
                st.write(menu_name)
            with row_c3:
                checked = st.checkbox(
                    "활성화",
                    value=(menu_group, menu_name) in current_enabled,
                    key=f"role_menu_enabled_{menu_group}_{menu_name}",
                    label_visibility="collapsed",
                )
            if checked:
                selected_menu_pairs.append((menu_group, menu_name))

    bulk_c1, bulk_c2 = st.columns(2)
    with bulk_c1:
        if st.button("전체 선택", key="role_menu_select_all", use_container_width=True):
            st.session_state["role_menu_bulk_state"] = "all"
            st.rerun()
    with bulk_c2:
        if st.button("전체 해제", key="role_menu_clear_all", use_container_width=True):
            st.session_state["role_menu_bulk_state"] = "none"
            st.rerun()

    action_defs = [
        ("저장", "role_manage_save", selected_role_row is None),
        ("수정", "role_manage_update", selected_role_row is not None),
        ("삭제", "role_manage_delete", selected_role_row is not None and str(selected_role_code) != "admin"),
    ]
    save_clicked, update_clicked, delete_clicked = render_page_actions(action_defs)

    if delete_clicked and selected_role_row is not None:
        with get_connection() as conn:
            users_role_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS cnt FROM users WHERE role_code = ?",
                    (selected_role_code,),
                ).fetchone()["cnt"]
            )
            user_roles_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS cnt FROM user_roles WHERE role_code = ?",
                    (selected_role_code,),
                ).fetchone()["cnt"]
            )
        if users_role_count > 0 or user_roles_count > 0:
            st.error("사용자에게 할당된 역할은 삭제할 수 없습니다.")
        else:
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM roles WHERE role_code = ?", (selected_role_code,))
                    conn.commit()
                    remaining_count = int(
                        conn.execute(
                            "SELECT COUNT(*) AS cnt FROM roles WHERE role_code = ?",
                            (selected_role_code,),
                        ).fetchone()["cnt"]
                    )
                    ok = int(cur.rowcount or 0) > 0 and remaining_count == 0
                    message = "역할을 삭제했습니다." if ok else "역할 삭제에 실패했습니다."
            except sqlite3.IntegrityError:
                ok = False
                message = "연결된 데이터가 있어서 삭제할 수 없습니다."
            if ok:
                st.session_state["role_manage_reset_pending"] = True
                reset_cache()
                flash_success("역할을 삭제했습니다.")
                st.rerun()
            st.error(message)

    if save_clicked or update_clicked:
        role_code = role_code.strip()
        role_name = role_name.strip()
        if not role_code or not role_name:
            st.error("역할코드와 역할명은 필수입니다.")
        else:
            duplicate_role = roles_df[roles_df["role_code"].astype(str) == role_code] if not roles_df.empty else pd.DataFrame()
            if save_clicked and not duplicate_role.empty:
                st.error("이미 존재하는 역할코드입니다.")
            else:
                created_at = datetime.now().isoformat(timespec="seconds")
                if save_clicked:
                    execute(
                        "INSERT INTO roles (role_code, role_name, is_active) VALUES (?, ?, ?)",
                        (role_code, role_name, 1 if is_active else 0),
                    )
                else:
                    execute(
                        "UPDATE roles SET role_name = ?, is_active = ? WHERE role_code = ?",
                        (role_name, 1 if is_active else 0, role_code),
                    )
                execute("DELETE FROM role_menu_permissions WHERE role_code = ?", (role_code,))
                for menu_group, menu_name in selected_menu_pairs:
                    execute(
                        """
                        INSERT OR REPLACE INTO role_menu_permissions (role_code, menu_group, menu_name, is_enabled, created_at)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (role_code, menu_group, menu_name, created_at),
                    )
                reset_cache()
                flash_success("역할을 저장했습니다." if save_clicked else "역할을 수정했습니다.")
                st.rerun()

    st.caption("활성화된 메뉴만 해당 역할 사용자에게 노출됩니다. 현재 단계에서는 메뉴 노출만 관리합니다.")
    if not roles_df.empty:
        render_history_panel("역할 이력", roles_df)


SYSTEM_PAGE_RENDERERS = {
    "대시보드": render_dashboard,
    "구조조회": render_structure_page,
    "사용자관리": render_users_page,
    "역할관리": render_role_management_page,
}


def render_system_page(menu: str) -> bool:
    renderer = SYSTEM_PAGE_RENDERERS.get(menu)
    if renderer is None:
        return False
    renderer()
    return True
