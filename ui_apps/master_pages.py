from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import streamlit as st

from db.runtime import (
    format_revision,
    get_table_columns,
    latest_rows_by_code,
    parse_revision_number,
    resolve_db_path,
    save_uploaded_file,
)
from db.schema import EXPECTED_DEVELOPMENT_PROJECT_COLUMNS
from domain.constants import (
    ARTWORK_TYPE_OPTIONS,
    EXPERIMENT_PROCESS_OPTIONS,
    FILM_STATUS_OPTIONS,
    ITEM_CLASSES,
    ITEM_TYPES,
    MATERIAL_STATUS_OPTIONS,
    PROJECT_DEVELOPMENT_TYPE_OPTIONS,
    PROJECT_STATUS_OPTIONS,
    RAW_MATERIAL_TYPES,
    SUB_MATERIAL_TYPES,
)
from services import master_service
from services.reference_data_service import (
    get_item_bom,
    get_items,
    get_products,
    get_print_films,
    get_product_drawings,
    get_projects,
    infer_process_type_from_item,
    item_options,
    mold_options,
    product_drawing_options,
    project_options,
    get_raw_materials,
    raw_material_options_for_project,
    get_sub_materials,
    film_options_for_project,
    product_options,
)
from services.shell_service import (
    can_edit,
    current_user,
    flash_success,
    render_dataframe,
    render_history_panel,
    render_page_actions,
    render_section_title,
    show_permission_hint,
)


PROJECT_SAVE_DEBUG_KEY = "project_save_debug"
PROJECT_SAVE_RENDER_COUNT_KEY = "project_save_render_count"
PROJECT_SAVE_SUBMIT_COUNT_KEY = "project_save_submit_count"
PROJECT_SAVE_DEBUG_VERSION = "project-save-debug-v3"


def _drawing_revision_from_filename(file_name: str) -> str:
    """Return a valid YYMMDD revision embedded in a drawing file name."""
    match = re.search(r"(?<!\d)(?:20)?(\d{2})(\d{2})(\d{2})(?!\d)", file_name or "")
    if match is None:
        return ""
    revision_no = "".join(match.groups())
    try:
        datetime.strptime(revision_no, "%y%m%d")
    except ValueError:
        return ""
    return revision_no


def _is_valid_drawing_revision(revision_no: str) -> bool:
    if re.fullmatch(r"\d{6}", revision_no) is None:
        return False
    try:
        datetime.strptime(revision_no, "%y%m%d")
    except ValueError:
        return False
    return True


def _update_project_save_debug(*, stage: str, message: str = "", payload: dict | None = None) -> None:
    st.session_state[PROJECT_SAVE_DEBUG_KEY] = {
        "stage": stage,
        "message": message,
        "payload": payload or {},
        "db_path": str(resolve_db_path()),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    print(f"[PROJECT_SAVE_DEBUG] stage={stage} message={message} payload={payload or {}} db={resolve_db_path()}")


def _mark_project_save_submit_event() -> None:
    submit_count = int(st.session_state.get(PROJECT_SAVE_SUBMIT_COUNT_KEY, 0) or 0) + 1
    st.session_state[PROJECT_SAVE_SUBMIT_COUNT_KEY] = submit_count
    _update_project_save_debug(
        stage="submit_event",
        message=f"저장 버튼 submit 이벤트 발생 ({submit_count})",
    )


def render_projects_page() -> None:
    page_name = "프로젝트 기본정보"
    st.session_state[PROJECT_SAVE_RENDER_COUNT_KEY] = int(st.session_state.get(PROJECT_SAVE_RENDER_COUNT_KEY, 0) or 0) + 1
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = get_projects()
    actual_project_columns = get_table_columns("development_projects")
    missing_project_columns = [col for col in EXPECTED_DEVELOPMENT_PROJECT_COLUMNS.keys() if col not in actual_project_columns]
    if can_edit(page_name):
        labels = ["신규 등록"]
        if not projects.empty:
            labels += projects.apply(lambda row: f"{row['project_code']} | {row['product_name']}", axis=1).tolist()
        pick_c1, pick_c2 = st.columns([2, 1])
        with pick_c1:
            selected_label = st.selectbox("프로젝트 선택", options=labels, key="project_pick_label")
        selected_row = None
        if selected_label != "신규 등록":
            selected_row = projects[projects.apply(lambda row: f"{row['project_code']} | {row['product_name']}", axis=1) == selected_label].iloc[0]
        with pick_c2:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="project_mode")
        with st.container(border=True):
            render_section_title("기본 정보")
            basic_c1, basic_c2, basic_c3 = st.columns(3)
            with basic_c1:
                project_code = st.text_input("프로젝트 코드", value=selected_row["project_code"] if selected_row is not None else "")
            with basic_c2:
                customer_name = st.text_input("고객명", value=selected_row["customer_name"] if selected_row is not None and pd.notna(selected_row["customer_name"]) else "")
                project_name = st.text_input("프로젝트명", value=selected_row["product_name"] if selected_row is not None else "")
            with basic_c3:
                development_type = st.selectbox("개발형태", PROJECT_DEVELOPMENT_TYPE_OPTIONS, index=PROJECT_DEVELOPMENT_TYPE_OPTIONS.index(selected_row["development_type"]) if selected_row is not None and selected_row["development_type"] in PROJECT_DEVELOPMENT_TYPE_OPTIONS else 0)
                status = st.selectbox("상태", PROJECT_STATUS_OPTIONS, index=PROJECT_STATUS_OPTIONS.index(selected_row["status"]) if selected_row is not None and selected_row["status"] in PROJECT_STATUS_OPTIONS else 0)

            render_section_title("일정 정보")
            plan_c1, plan_c2, plan_c3, plan_c4 = st.columns(4)
            with plan_c1:
                launch_date = st.date_input("출시일", value=pd.to_datetime(selected_row["launch_date"]).date() if selected_row is not None and selected_row["launch_date"] else None)
            with plan_c2:
                packaging_date = st.date_input("포장일", value=pd.to_datetime(selected_row["packaging_date"]).date() if selected_row is not None and selected_row["packaging_date"] else None)
            with plan_c3:
                production_plan_date = st.date_input("생산계획일", value=pd.to_datetime(selected_row["production_plan_date"]).date() if selected_row is not None and selected_row["production_plan_date"] else None)
            with plan_c4:
                new_product_test_due_date = st.date_input("신제품시험 목표일", value=pd.to_datetime(selected_row["new_product_test_due_date"]).date() if selected_row is not None and selected_row["new_product_test_due_date"] else None)
            owner_c1, owner_c2, owner_c3, owner_c4, owner_c5 = st.columns(5)
            with owner_c1:
                standard_due_date = st.date_input("표준획득 목표일", value=pd.to_datetime(selected_row["standard_due_date"]).date() if selected_row is not None and selected_row["standard_due_date"] else None)
            with owner_c2:
                t0_date = st.date_input("T0일", value=pd.to_datetime(selected_row["t0_date"]).date() if selected_row is not None and "t0_date" in selected_row.index and selected_row["t0_date"] else None)
            with owner_c3:
                t1_date = st.date_input("T1일", value=pd.to_datetime(selected_row["t1_date"]).date() if selected_row is not None and "t1_date" in selected_row.index and selected_row["t1_date"] else None)
            with owner_c4:
                sales_owner = st.text_input("영업 담당", value=selected_row["sales_owner"] if selected_row is not None and pd.notna(selected_row["sales_owner"]) else "")
            with owner_c5:
                developer_owner = st.text_input("포장재개발팀", value=selected_row["developer_owner"] if selected_row is not None and pd.notna(selected_row["developer_owner"]) else "")
            extra_owner_c1, extra_owner_c2 = st.columns(2)
            with extra_owner_c1:
                mold_vendor_name = st.text_input("금형제작처", value=selected_row["mold_vendor_name"] if selected_row is not None and "mold_vendor_name" in selected_row.index and pd.notna(selected_row["mold_vendor_name"]) else "")
            with extra_owner_c2:
                supervisor_name = st.text_input("감리처", value=selected_row["supervisor_name"] if selected_row is not None and "supervisor_name" in selected_row.index and pd.notna(selected_row["supervisor_name"]) else "")
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None and pd.notna(selected_row["notes"]) else "")
            action_c1, action_c2 = st.columns(2)
            with action_c1:
                save_clicked = st.button("저장", key="project_form_save", use_container_width=True)
            with action_c2:
                delete_clicked = st.button("삭제", key="project_form_delete", disabled=selected_row is None, use_container_width=True)
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_project(int(selected_row["project_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                _mark_project_save_submit_event()
                normalized_project_code = project_code.strip()
                normalized_customer_name = customer_name.strip()
                normalized_project_name = project_name.strip()
                debug_payload = {
                    "selected_project_id": int(selected_row["project_id"]) if selected_row is not None else None,
                    "project_code": normalized_project_code,
                    "customer_name": normalized_customer_name,
                    "project_name": normalized_project_name,
                    "development_type": development_type,
                    "status": status,
                }
                _update_project_save_debug(stage="clicked", message="저장 버튼 클릭 감지", payload=debug_payload)
                duplicate = projects[projects["project_code"] == normalized_project_code]
                if selected_row is not None:
                    duplicate = duplicate[duplicate["project_id"] != selected_row["project_id"]]
                if not normalized_project_code or not normalized_project_name:
                    _update_project_save_debug(stage="blocked", message="프로젝트 코드/프로젝트명 필수값 누락", payload=debug_payload)
                    st.error("프로젝트 코드와 프로젝트명을 입력해 주세요.")
                elif not duplicate.empty:
                    _update_project_save_debug(stage="blocked", message="중복 프로젝트 코드", payload=debug_payload)
                    st.error("프로젝트 코드는 중복될 수 없습니다.")
                else:
                    try:
                        _update_project_save_debug(stage="saving", message="master_service.save_project 호출 직전", payload=debug_payload)
                        master_service.save_project(
                            int(selected_row["project_id"]) if selected_row is not None else None,
                            {
                                "project_code": normalized_project_code,
                                "customer_name": normalized_customer_name,
                                "project_name": normalized_project_name,
                                "development_type": development_type,
                                "launch_date": str(launch_date) if launch_date else None,
                                "packaging_date": str(packaging_date) if packaging_date else None,
                                "production_plan_date": str(production_plan_date) if production_plan_date else None,
                                "new_product_test_due_date": str(new_product_test_due_date) if new_product_test_due_date else None,
                                "standard_due_date": str(standard_due_date) if standard_due_date else None,
                                "t0_date": str(t0_date) if t0_date else None,
                                "t1_date": str(t1_date) if t1_date else None,
                                "sales_owner": sales_owner.strip(),
                                "developer_owner": developer_owner.strip(),
                                "mold_vendor_name": mold_vendor_name.strip(),
                                "supervisor_name": supervisor_name.strip(),
                                "status": status,
                                "notes": notes.strip(),
                            },
                            current_user()["user_name"],
                        )
                        print(f"[PROJECT_SAVE_DEBUG] save_clicked branch executed project_code={normalized_project_code}")
                        saved_projects = get_projects()
                        saved_row = saved_projects[saved_projects["project_code"] == normalized_project_code]
                        if saved_row.empty:
                            _update_project_save_debug(stage="verify_failed", message="저장 후 재조회 실패", payload=debug_payload)
                            st.error("프로젝트 기본정보 저장 후 DB 확인에 실패했습니다. 다시 시도해 주세요.")
                        else:
                            _update_project_save_debug(stage="saved", message="저장 및 재조회 성공", payload=debug_payload)
                            flash_success("프로젝트 기본정보를 저장했습니다." if selected_row is None else "프로젝트 기본정보를 수정했습니다.")
                            st.rerun()
                    except Exception as exc:
                        _update_project_save_debug(stage="error", message=str(exc), payload=debug_payload)
                        st.error(f"프로젝트 기본정보 저장 중 오류가 발생했습니다: {exc}")
    if not projects.empty:
        render_history_panel("이력 보기", projects)


def render_products_page() -> None:
    page_name = "상품"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = project_options()
    products_df = get_products()
    items_df = get_items()
    selected_project_code = ""
    project_products_df = products_df.iloc[0:0]
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1.2, 0.8])
        with pick_c1:
            selected_project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="product_project_label")
        selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
        project_products_df = products_df[products_df["project_code"] == selected_project_code] if selected_project_code else products_df.iloc[0:0]
        selected_row = None
        labels = ["신규 등록"]
        if not project_products_df.empty:
            labels += project_products_df.apply(lambda row: f"{row['product_code']} | {row['product_name']}", axis=1).tolist()
        with pick_c2:
            selected_label = st.selectbox("상품 선택", options=labels, key="product_pick_label")
        if selected_label != "신규 등록":
            selected_row = project_products_df[project_products_df.apply(lambda row: f"{row['product_code']} | {row['product_name']}", axis=1) == selected_label].iloc[0]
        with pick_c3:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="product_mode")
        root_items_df = items_df.sort_values(["item_code", "item_name"]).copy() if not items_df.empty else items_df.iloc[0:0]
        root_choices = [""] + root_items_df.apply(lambda row: f"{row['item_code']} | {row['item_name']}", axis=1).tolist() if not root_items_df.empty else [""]
        selected_root_label = ""
        linked_item_value = None
        if selected_row is not None:
            linked_item_value = selected_row["linked_item_id"] if "linked_item_id" in selected_row.index and pd.notna(selected_row["linked_item_id"]) else selected_row["root_item_id"]
        if linked_item_value is not None and pd.notna(linked_item_value):
            match = root_items_df[root_items_df["item_id"] == int(linked_item_value)]
            if not match.empty:
                selected_root_label = f"{match.iloc[0]['item_code']} | {match.iloc[0]['item_name']}"
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                product_code = st.text_input("상품코드", value=selected_row["product_code"] if selected_row is not None else "")
            with c2:
                product_name = st.text_input("상품명", value=selected_row["product_name"] if selected_row is not None else "")
            with c3:
                root_item_label = st.selectbox("연결 공정품", options=root_choices, index=root_choices.index(selected_root_label) if selected_root_label in root_choices else 0)
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None and pd.notna(selected_row["notes"]) else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "product_form_save", True),
                    ("삭제", "product_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_product(int(selected_row["product_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                duplicate = products_df[products_df["product_code"] == product_code]
                if selected_row is not None:
                    duplicate = duplicate[duplicate["product_id"] != selected_row["product_id"]]
                if not selected_project_label:
                    st.error("프로젝트를 먼저 선택해 주세요.")
                elif not product_code.strip() or not product_name.strip():
                    st.error("상품코드와 상품명을 입력해 주세요.")
                elif not duplicate.empty:
                    st.error("상품코드는 중복될 수 없습니다.")
                else:
                    matched_root = (
                        root_items_df[root_items_df.apply(lambda row: f"{row['item_code']} | {row['item_name']}", axis=1) == root_item_label].iloc[0]
                        if root_item_label
                        else None
                    )
                    master_service.save_product(
                        int(selected_row["product_id"]) if selected_row is not None else None,
                        {
                            "project_id": dict(projects).get(selected_project_label),
                            "product_code": product_code,
                            "product_name": product_name,
                            "linked_item_id": int(matched_root["item_id"]) if matched_root is not None else None,
                            "notes": notes,
                        },
                        current_user()["user_name"],
                    )
                    flash_success("상품을 저장했습니다." if selected_row is None else "상품을 수정했습니다.")
                    st.rerun()
    history_df = project_products_df if can_edit(page_name) and selected_project_code else products_df
    if not history_df.empty:
        render_history_panel("이력 보기", history_df)


def render_items_page() -> None:
    page_name = "공정품"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = project_options()
    items_df = get_items()
    selected_project_code = ""
    project_items_df = items_df.iloc[0:0]
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3, pick_c4 = st.columns([1, 1.2, 1.2, 0.8])
        with pick_c1:
            selected_project_label = st.selectbox("기준 프로젝트(선택)", options=[""] + [label for label, _ in projects], key="item_project_label")
        selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
        with pick_c2:
            st.text_input("등록 방식", value="독립 공정품 마스터", disabled=True, key="item_registration_mode")
        project_items_df = items_df.sort_values(["item_code", "item_name"]).copy() if not items_df.empty else items_df.iloc[0:0]
        selected_row = None
        selected_label = "신규 등록"
        labels = ["신규 등록"]
        if not project_items_df.empty:
            labels += project_items_df.apply(lambda row: f"{row['item_code']} | {row['item_name']}", axis=1).tolist()
        with pick_c3:
            selected_label = st.selectbox("공정품 선택", options=labels, key="item_pick_label")
        if selected_label != "신규 등록":
            selected_row = project_items_df[project_items_df.apply(lambda row: f"{row['item_code']} | {row['item_name']}", axis=1) == selected_label].iloc[0]
        project_drawings = [pair for pair in product_drawing_options() if pair[0].split(" | ")[0] == selected_project_code] if selected_project_code else []
        project_molds = [pair for pair in mold_options() if pair[0].split(" | ")[0] == selected_project_code] if selected_project_code else []
        project_films = film_options_for_project(selected_project_code) if selected_project_code else []
        project_raw_materials = raw_material_options_for_project(selected_project_code) if selected_project_code else []
        drawings_df = get_product_drawings()
        films_df = get_print_films()
        with pick_c4:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="item_mode")
        with st.container(border=True):
            render_section_title("기본 정보")
            base_c1, base_c2, base_c3 = st.columns(3)
            with base_c1:
                item_code = st.text_input("공정품 코드", value=selected_row["item_code"] if selected_row is not None else "")
            with base_c2:
                item_name = st.text_input("공정품명", value=selected_row["item_name"] if selected_row is not None else "")
            with base_c3:
                selected_process_type = infer_process_type_from_item(selected_row) if selected_row is not None else ""
                process_options = [""] + EXPERIMENT_PROCESS_OPTIONS
                process_type = st.selectbox(
                    "공정",
                    options=process_options,
                    index=process_options.index(selected_process_type) if selected_process_type in process_options else 0,
                    help="고객요구, 실험지시, 실험 화면은 이 공정 값을 기준으로 자동 전환됩니다.",
                )
            ref_c1, ref_c2, ref_c3 = st.columns(3)
            with ref_c1:
                item_type = st.selectbox("품목 유형", ITEM_TYPES, index=ITEM_TYPES.index(selected_row["item_type"]) if selected_row is not None and selected_row["item_type"] in ITEM_TYPES else 0)
            with ref_c2:
                if process_type == "인쇄":
                    selected_film_label = next((label for label, film_id in project_films if selected_row is not None and "base_print_film_id" in selected_row.index and film_id == selected_row["base_print_film_id"]), "")
                    film_choices = [""] + [label for label, _ in project_films]
                    film_label = st.selectbox("기준 원화", options=film_choices, index=film_choices.index(selected_film_label) if selected_film_label in film_choices else 0)
                    drawing_label = ""
                else:
                    selected_drawing_label = next((label for label, drawing_id in project_drawings if selected_row is not None and drawing_id == selected_row["product_drawing_id"]), "")
                    drawing_choices = [""] + [label for label, _ in project_drawings]
                    drawing_label = st.selectbox("기준 제품도면", options=drawing_choices, index=drawing_choices.index(selected_drawing_label) if selected_drawing_label in drawing_choices else 0)
                    film_label = ""
            with ref_c3:
                if process_type == "사출":
                    selected_mold_label = next((label for label, mold_id in project_molds if selected_row is not None and mold_id == selected_row["primary_mold_id"]), "")
                    mold_choices = [""] + [label for label, _ in project_molds]
                    mold_label = st.selectbox("대표 금형", options=mold_choices, index=mold_choices.index(selected_mold_label) if selected_mold_label in mold_choices else 0)
                else:
                    st.text_input("공정 기준", value="공정 기준정보 사용", disabled=True)
                    mold_label = ""
            base_info_c1, base_info_c2, base_info_c3 = st.columns(3)
            with base_info_c1:
                base_revision_no = st.text_input(
                    "기준 Rev",
                    value=(
                        selected_row["base_film_revision_no"]
                        if process_type == "인쇄" and selected_row is not None and "base_film_revision_no" in selected_row.index and pd.notna(selected_row["base_film_revision_no"])
                        else (
                            selected_row["product_drawing_revision_no"]
                            if selected_row is not None and "product_drawing_revision_no" in selected_row.index and pd.notna(selected_row["product_drawing_revision_no"])
                            else (selected_row["base_revision_no"] if selected_row is not None and "base_revision_no" in selected_row.index and pd.notna(selected_row["base_revision_no"]) else "")
                        )
                    ),
                    disabled=True,
                )
            with base_info_c2:
                raw_choices = [""] + [label for label, _ in project_raw_materials]
                selected_raw_label = selected_row["base_material_label"] if selected_row is not None and "base_material_label" in selected_row.index and pd.notna(selected_row["base_material_label"]) else ""
                if selected_raw_label and selected_raw_label not in raw_choices:
                    raw_choices.append(selected_raw_label)
                base_material_label = st.selectbox(
                    "기준 원료",
                    options=raw_choices,
                    index=raw_choices.index(selected_raw_label) if selected_raw_label in raw_choices else 0,
                )
            with base_info_c3:
                base_color_label = st.text_input(
                    "기준 색상",
                    value=selected_row["base_color_label"] if selected_row is not None and "base_color_label" in selected_row.index and pd.notna(selected_row["base_color_label"]) else "",
                )
            mb_note = st.text_input("MB 메모", value=selected_row["mb_note"] if selected_row is not None and pd.notna(selected_row["mb_note"]) else "")
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None and pd.notna(selected_row["notes"]) else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "item_form_save", True),
                    ("삭제", "item_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_item(int(selected_row["item_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                duplicate = items_df[items_df["item_code"] == item_code]
                if selected_row is not None:
                    duplicate = duplicate[duplicate["item_id"] != selected_row["item_id"]]
                if not item_code.strip() or not item_name.strip():
                    st.error("공정품 코드와 공정품명을 입력해 주세요.")
                elif not process_type:
                    st.error("공정을 선택해 주세요.")
                elif not duplicate.empty:
                    st.error("공정품 코드는 중복될 수 없습니다.")
                else:
                    selected_drawing_id = dict(project_drawings).get(drawing_label)
                    selected_film_id = dict(project_films).get(film_label)
                    selected_mold_id = dict(project_molds).get(mold_label)
                    if selected_row is not None:
                        if selected_drawing_id is None and pd.notna(selected_row.get("product_drawing_id")):
                            selected_drawing_id = int(selected_row["product_drawing_id"])
                        if selected_film_id is None and pd.notna(selected_row.get("base_print_film_id")):
                            selected_film_id = int(selected_row["base_print_film_id"])
                        if selected_mold_id is None and pd.notna(selected_row.get("primary_mold_id")):
                            selected_mold_id = int(selected_row["primary_mold_id"])
                    matched_drawing = drawings_df[drawings_df["product_drawing_id"] == int(selected_drawing_id)] if selected_drawing_id and not drawings_df.empty else drawings_df.iloc[0:0]
                    matched_film = films_df[films_df["print_film_id"] == int(selected_film_id)] if selected_film_id and not films_df.empty else films_df.iloc[0:0]
                    if process_type == "인쇄":
                        base_revision_no = str(matched_film.iloc[0]["revision_no"]) if not matched_film.empty and pd.notna(matched_film.iloc[0]["revision_no"]) else ""
                    else:
                        base_revision_no = str(matched_drawing.iloc[0]["revision_no"]) if not matched_drawing.empty and pd.notna(matched_drawing.iloc[0]["revision_no"]) else ""
                    master_service.save_item(
                        int(selected_row["item_id"]) if selected_row is not None else None,
                        {
                            "project_id": None,
                            "product_id": None,
                            "item_code": item_code,
                            "item_name": item_name,
                            "item_class": ITEM_CLASSES[0],
                            "item_type": item_type,
                            "process_type": process_type,
                            "product_drawing_id": selected_drawing_id,
                            "base_print_film_id": selected_film_id,
                            "primary_mold_id": selected_mold_id,
                            "base_revision_no": base_revision_no.strip(),
                            "base_material_label": base_material_label.strip(),
                            "base_color_label": base_color_label.strip(),
                            "mb_note": mb_note,
                            "notes": notes,
                        },
                        current_user()["user_name"],
                    )
                    flash_success("공정품을 저장했습니다." if selected_row is None else "공정품을 수정했습니다.")
                    st.rerun()
    history_df = project_items_df if can_edit(page_name) else items_df
    if not history_df.empty:
        render_history_panel("이력 보기", history_df)


def render_bom_page() -> None:
    page_name = "제품구성"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = project_options()
    items = item_options()
    df = get_item_bom()
    selected_project_code = ""
    project_df = df.iloc[0:0]
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1.2, 0.8])
        with pick_c1:
            selected_project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="bom_project_label")
        selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
        project_df = df[df["project_code"] == selected_project_code] if selected_project_code else df.iloc[0:0]
        selected_row = None
        selected_label = "신규 등록"
        if selected_project_code:
            labels = ["신규 등록"]
            if not project_df.empty:
                labels += project_df.apply(lambda row: f"{row['parent_item_code']} -> {row['child_item_code']}", axis=1).tolist()
            with pick_c2:
                selected_label = st.selectbox("제품구성 선택", options=labels, key="bom_pick_label")
            if selected_label != "신규 등록":
                selected_row = project_df[project_df.apply(lambda row: f"{row['parent_item_code']} -> {row['child_item_code']}", axis=1) == selected_label].iloc[0]
        with pick_c3:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="bom_mode")
        # BOM은 상품 루트에서 공정품 마스터를 연결하므로 다른 프로젝트에서
        # 최초 등록한 공용 공정품도 하위 공정품으로 선택할 수 있습니다.
        project_items = items if selected_project_code else []
        selected_parent_label = next((label for label, _ in project_items if selected_row is not None and f"| {selected_row['parent_item_code']} |" in label), "") if selected_row is not None else ""
        selected_child_label = next((label for label, _ in project_items if selected_row is not None and f"| {selected_row['child_item_code']} |" in label), "") if selected_row is not None else ""
        with st.container(border=True):
            item_labels = [""] + [label for label, _ in project_items]
            top_c1, top_c2 = st.columns(2)
            with top_c1:
                parent_label = st.selectbox("상위 공정품", options=item_labels, index=item_labels.index(selected_parent_label) if selected_parent_label in item_labels else 0)
            with top_c2:
                child_label = st.selectbox("하위 공정품", options=item_labels, index=item_labels.index(selected_child_label) if selected_child_label in item_labels else 0)
            c1, c2, c3 = st.columns(3)
            with c1:
                qty = st.number_input("수량", min_value=0.0, step=1.0, value=float(selected_row["qty"]) if selected_row is not None and pd.notna(selected_row["qty"]) else 1.0)
            with c2:
                qty_unit = st.text_input("수량 단위", value=selected_row["qty_unit"] if selected_row is not None and pd.notna(selected_row["qty_unit"]) else "ea")
            with c3:
                st.text_input("연결 형태", value="상위 공정품 -> 하위 공정품(공용 가능)", disabled=True)
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None and pd.notna(selected_row["notes"]) else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "bom_form_save", True),
                    ("삭제", "bom_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_bom(int(selected_row["bom_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                parent_id = dict(project_items).get(parent_label)
                child_id = dict(project_items).get(child_label)
                if not selected_project_label or not parent_id or not child_id:
                    st.error("프로젝트, 상위 공정품, 하위 공정품을 모두 선택해 주세요.")
                elif parent_id == child_id:
                    st.error("상위 공정품과 하위 공정품은 같을 수 없습니다.")
                else:
                    try:
                        master_service.save_bom(
                            int(selected_row["bom_id"]) if selected_row is not None else None,
                            {
                                "project_id": dict(projects).get(selected_project_label),
                                "parent_item_id": parent_id,
                                "child_item_id": child_id,
                                "qty": qty,
                                "qty_unit": qty_unit,
                                "notes": notes,
                            },
                            current_user()["user_name"],
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                        return
                    flash_success("제품구성을 저장했습니다." if selected_row is None else "제품구성을 수정했습니다.")
                    st.rerun()
    history_df = project_df if can_edit(page_name) and selected_project_code else df
    if not history_df.empty:
        render_history_panel("이력 보기", history_df)


def render_product_drawings_page() -> None:
    page_name = "제품도면"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = project_options()
    df = get_product_drawings()
    selected_project_code = ""
    project_df = df.iloc[0:0]
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1.3, 0.8])
        with pick_c1:
            selected_project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="drawing_project_label")
        selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
        project_df = df[df["project_code"] == selected_project_code] if selected_project_code else df.iloc[0:0]
        selected_row = None
        drawing_history_df = project_df.iloc[0:0]
        selected_label = "신규 등록"
        if selected_project_code:
            latest_df = latest_rows_by_code(project_df, "drawing_no", "product_drawing_id", "is_current")
            labels = ["신규 등록"]
            if not latest_df.empty:
                labels += latest_df.apply(lambda row: f"{row['drawing_no']} | {row['drawing_name']} | 최신 {row['revision_no']}", axis=1).tolist()
            with pick_c2:
                selected_label = st.selectbox("제품도면 선택", options=labels, key="drawing_pick_label")
            if selected_label != "신규 등록":
                selected_row = latest_df[latest_df.apply(lambda row: f"{row['drawing_no']} | {row['drawing_name']} | 최신 {row['revision_no']}", axis=1) == selected_label].iloc[0]
                drawing_history_df = project_df[project_df["drawing_no"] == selected_row["drawing_no"]].copy()
                if not drawing_history_df.empty:
                    drawing_history_df["_revision_num"] = drawing_history_df["revision_no"].apply(parse_revision_number)
                    drawing_history_df = drawing_history_df.sort_values(["is_current", "_revision_num", "product_drawing_id"], ascending=[False, False, False]).drop(columns=["_revision_num"])
        with pick_c3:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="drawing_mode")
        with st.container(border=True):
            top_c1, top_c2, top_c3 = st.columns(3)
            with top_c1:
                drawing_no = st.text_input("제품도면 번호", value=selected_row["drawing_no"] if selected_row is not None else "")
            with top_c2:
                drawing_name = st.text_input("제품도면명", value=selected_row["drawing_name"] if selected_row is not None else "")
            uploaded_drawing = st.file_uploader("제품도면 첨부", type=None, key="product_drawing_upload")
            with top_c3:
                create_new_revision = st.checkbox("신규 리비전 등록", value=False, disabled=selected_row is None)
                revision_key = f"product_drawing_revision_{selected_project_code}_{int(selected_row['product_drawing_id']) if selected_row is not None else 'new'}"
                upload_marker_key = f"{revision_key}_upload_name"
                default_revision = (
                    str(selected_row["revision_no"]).strip()
                    if selected_row is not None and pd.notna(selected_row["revision_no"])
                    else datetime.now().strftime("%y%m%d")
                )
                uploaded_file_name = uploaded_drawing.name if uploaded_drawing is not None else ""
                if uploaded_file_name and st.session_state.get(upload_marker_key) != uploaded_file_name:
                    extracted_revision = _drawing_revision_from_filename(uploaded_file_name)
                    if extracted_revision:
                        st.session_state[revision_key] = extracted_revision
                    st.session_state[upload_marker_key] = uploaded_file_name
                revision_no = st.text_input(
                    "리비전 (YYMMDD)",
                    value=default_revision,
                    key=revision_key,
                    help="도면 파일명의 YYYYMMDD 또는 YYMMDD를 자동으로 불러오며, 직접 수정할 수 있습니다.",
                ).strip()
            ref_c1, ref_c2 = st.columns([1.2, 1])
            with ref_c1:
                file_note = st.text_input("파일/링크 메모", value=selected_row["file_note"] if selected_row is not None else "")
            with ref_c2:
                is_current = st.checkbox("현재 유효본", value=bool(selected_row["is_current"]) if selected_row is not None else True)
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "product_drawing_form_save", True),
                    ("삭제", "product_drawing_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_product_drawing(int(selected_row["product_drawing_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                normalized_drawing_no = drawing_no.strip()
                normalized_drawing_name = drawing_name.strip()
                existing_revision = (
                    str(selected_row["revision_no"]).strip()
                    if selected_row is not None and pd.notna(selected_row["revision_no"])
                    else ""
                )
                legacy_revision_unchanged = bool(
                    selected_row is not None
                    and not create_new_revision
                    and revision_no == existing_revision
                )
                duplicate_revision = project_df[
                    (project_df["drawing_no"] == normalized_drawing_no)
                    & (project_df["revision_no"].astype(str).str.strip() == revision_no)
                ]
                if selected_row is not None and not create_new_revision:
                    duplicate_revision = duplicate_revision[
                        duplicate_revision["product_drawing_id"] != selected_row["product_drawing_id"]
                    ]
                if not normalized_drawing_no or not normalized_drawing_name:
                    st.error("제품도면 번호와 제품도면명을 입력해 주세요.")
                elif not legacy_revision_unchanged and not _is_valid_drawing_revision(revision_no):
                    st.error("리비전은 실제 날짜에 해당하는 YYMMDD 6자리로 입력해 주세요.")
                elif not duplicate_revision.empty:
                    st.error("같은 도면 번호에 동일한 리비전이 이미 등록되어 있습니다.")
                elif create_new_revision and uploaded_drawing is None:
                    st.error("신규 리비전 등록 시 도면 파일을 다시 첨부해 주세요.")
                else:
                    file_path = save_uploaded_file(uploaded_drawing, "product_drawings") if uploaded_drawing is not None else (selected_row["file_path"] if selected_row is not None else None)
                    project_id = dict(projects).get(selected_project_label)
                    master_service.save_product_drawing(
                        int(selected_row["product_drawing_id"]) if selected_row is not None else None,
                        create_new_revision=create_new_revision,
                        payload={
                            "project_id": project_id,
                            "drawing_no": normalized_drawing_no,
                            "drawing_name": normalized_drawing_name,
                            "revision_no": revision_no,
                            "file_note": file_note,
                            "file_path": file_path,
                            "is_current": is_current,
                            "notes": notes,
                        },
                        current_user_name=current_user()["user_name"],
                    )
                    flash_success(f"제품도면을 저장했습니다. 현재 리비전: {revision_no}")
                    st.rerun()
        if not drawing_history_df.empty:
            render_history_panel("선택 도면 리비전 이력", drawing_history_df[["drawing_no", "drawing_name", "revision_no", "is_current", "file_note", "notes"]])
    history_df = project_df if can_edit(page_name) and selected_project_code else df
    if not history_df.empty:
        render_history_panel("이력 보기", history_df)


def render_films_page() -> None:
    page_name = "원화"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = project_options()
    df = get_print_films()
    selected_project_code = ""
    project_df = df.iloc[0:0]
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1.3, 0.8])
        with pick_c1:
            selected_project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="film_project_label")
        selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
        project_df = df[df["project_code"] == selected_project_code] if selected_project_code else df.iloc[0:0]
        selected_row = None
        film_history_df = project_df.iloc[0:0]
        selected_label = "신규 등록"
        if selected_project_code:
            latest_df = latest_rows_by_code(project_df, "film_code", "print_film_id", "is_current")
            labels = ["신규 등록"]
            if not latest_df.empty:
                labels += latest_df.apply(lambda row: f"{row['artwork_type']} | {row['film_code']} | {row['film_name']} | 최신 {row['revision_no']}", axis=1).tolist()
            with pick_c2:
                selected_label = st.selectbox("원화 선택", options=labels, key="film_pick_label")
            if selected_label != "신규 등록":
                selected_row = latest_df[latest_df.apply(lambda row: f"{row['artwork_type']} | {row['film_code']} | {row['film_name']} | 최신 {row['revision_no']}", axis=1) == selected_label].iloc[0]
                film_history_df = project_df[project_df["film_code"] == selected_row["film_code"]].copy()
                if not film_history_df.empty:
                    film_history_df["_revision_num"] = film_history_df["revision_no"].apply(parse_revision_number)
                    film_history_df = film_history_df.sort_values(["is_current", "_revision_num", "print_film_id"], ascending=[False, False, False]).drop(columns=["_revision_num"])
        with pick_c3:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="film_mode")
        with st.container(border=True):
            top_c1, top_c2, top_c3 = st.columns(3)
            with top_c1:
                film_code = st.text_input("원화 코드", value=selected_row["film_code"] if selected_row is not None else "")
            with top_c2:
                film_name = st.text_input("원화명", value=selected_row["film_name"] if selected_row is not None else "")
            with top_c3:
                artwork_type = st.selectbox("원화 구분", ARTWORK_TYPE_OPTIONS, index=ARTWORK_TYPE_OPTIONS.index(selected_row["artwork_type"]) if selected_row is not None and selected_row["artwork_type"] in ARTWORK_TYPE_OPTIONS else 0)
            current_revision_num = parse_revision_number(selected_row["revision_no"]) if selected_row is not None else -1
            rev_c1, rev_c2, rev_c3 = st.columns(3)
            with rev_c1:
                create_new_revision = st.checkbox("신규 리비전 등록", value=False, disabled=selected_row is None)
            with rev_c2:
                revision_no = format_revision(0 if selected_row is None else current_revision_num + (1 if create_new_revision else 0))
                st.text_input("리비전", value=revision_no, disabled=True)
            related_item_label = "관련 인쇄품" if artwork_type == "인쇄" else "관련 라벨"
            with rev_c3:
                status = st.selectbox("상태", FILM_STATUS_OPTIONS, index=FILM_STATUS_OPTIONS.index(selected_row["status"]) if selected_row is not None and selected_row["status"] in FILM_STATUS_OPTIONS else 0)
            related_item_name = st.text_input(related_item_label, value=selected_row["related_item_name"] if selected_row is not None else "")
            uploaded_film = st.file_uploader("원화 첨부", type=None, key="film_upload")
            is_current = st.checkbox("현재 유효본", value=bool(selected_row["is_current"]) if selected_row is not None else True)
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "film_form_save", True),
                    ("삭제", "film_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_print_film(int(selected_row["print_film_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                if not film_code or not film_name:
                    st.error("원화 코드와 원화명을 입력해 주세요.")
                elif create_new_revision and uploaded_film is None:
                    st.error("신규 리비전 등록 시 원화 파일을 다시 첨부해 주세요.")
                else:
                    film_file_path = save_uploaded_file(uploaded_film, "print_films") if uploaded_film is not None else (selected_row["file_path"] if selected_row is not None else None)
                    project_id = dict(projects).get(selected_project_label)
                    master_service.save_print_film(
                        int(selected_row["print_film_id"]) if selected_row is not None else None,
                        create_new_revision=create_new_revision,
                        payload={
                            "project_id": project_id,
                            "film_code": film_code,
                            "film_name": film_name,
                            "artwork_type": artwork_type,
                            "revision_no": revision_no,
                            "related_item_name": related_item_name,
                            "status": status,
                            "file_path": film_file_path,
                            "notes": notes,
                            "is_current": is_current,
                        },
                        current_user_name=current_user()["user_name"],
                    )
                    flash_success(f"원화 정보를 저장했습니다. 현재 리비전: {revision_no}")
                    st.rerun()
        if not film_history_df.empty:
            render_history_panel("선택 원화 리비전 이력", film_history_df[["artwork_type", "film_code", "film_name", "revision_no", "is_current", "status", "related_item_name", "notes"]])
    history_df = project_df if can_edit(page_name) and selected_project_code else df
    if not history_df.empty:
        render_history_panel("이력 보기", history_df)


def render_raw_materials_page() -> None:
    page_name = "원재료"
    st.subheader(page_name)
    show_permission_hint(page_name)
    df = get_raw_materials()
    if can_edit(page_name):
        labels = ["신규 등록"]
        if not df.empty:
            labels += df.apply(lambda row: f"{row['material_code']} | {row['material_name']}", axis=1).tolist()
        pick_c1, pick_c2 = st.columns([2, 1])
        with pick_c1:
            selected_label = st.selectbox("원료 선택", options=labels, key="raw_material_pick")
        selected_row = None
        if selected_label != "신규 등록":
            selected_row = df[df.apply(lambda row: f"{row['material_code']} | {row['material_name']}", axis=1) == selected_label].iloc[0]
        with pick_c2:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="raw_material_mode")
        with st.container(border=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                material_code = st.text_input("원재료 코드", value=selected_row["material_code"] if selected_row is not None else "")
            with c2:
                material_name = st.text_input("원재료명", value=selected_row["material_name"] if selected_row is not None else "")
            with c3:
                status = st.selectbox("상태", MATERIAL_STATUS_OPTIONS, index=MATERIAL_STATUS_OPTIONS.index(selected_row["status"]) if selected_row is not None and selected_row["status"] in MATERIAL_STATUS_OPTIONS else 0)
            supplier_name = st.text_input("공급처", value=selected_row["supplier_name"] if selected_row is not None and pd.notna(selected_row["supplier_name"]) else "")
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None and pd.notna(selected_row["notes"]) else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "raw_material_form_save", True),
                    ("삭제", "raw_material_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_raw_material(int(selected_row["raw_material_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                duplicate = df[df["material_code"] == material_code]
                if selected_row is not None:
                    duplicate = duplicate[duplicate["raw_material_id"] != selected_row["raw_material_id"]]
                if not duplicate.empty:
                    st.error("원재료 코드는 중복될 수 없습니다.")
                else:
                    master_service.save_raw_material(
                        int(selected_row["raw_material_id"]) if selected_row is not None else None,
                        {
                            "material_code": material_code,
                            "material_name": material_name,
                            "material_type": RAW_MATERIAL_TYPES[0],
                            "supplier_name": supplier_name,
                            "status": status,
                            "notes": notes,
                        },
                        current_user()["user_name"],
                    )
                    flash_success("원료를 저장했습니다." if selected_row is None else "원료를 수정했습니다.")
                    st.rerun()
    if not df.empty:
        render_history_panel("이력 보기", df)


def render_sub_materials_page() -> None:
    page_name = "부재료"
    st.subheader(page_name)
    show_permission_hint(page_name)
    df = get_sub_materials()
    films_df = get_print_films()
    label_film_options = []
    if not films_df.empty:
        label_film_options = [
            (f"{row['project_code']} | {row['film_code']} | {row['film_name']}", int(row["print_film_id"]))
            for _, row in films_df[films_df["artwork_type"] == "라벨"].iterrows()
        ]
    if can_edit(page_name):
        labels = ["신규 등록"]
        if not df.empty:
            labels += df.apply(lambda row: f"{row['material_code']} | {row['material_name']}", axis=1).tolist()
        pick_c1, pick_c2 = st.columns([2, 1])
        with pick_c1:
            selected_label = st.selectbox("부재료 선택", options=labels, key="sub_material_pick")
        selected_row = None
        if selected_label != "신규 등록":
            selected_row = df[df.apply(lambda row: f"{row['material_code']} | {row['material_name']}", axis=1) == selected_label].iloc[0]
        with pick_c2:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="sub_material_mode")
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                material_code = st.text_input("부재료 코드", value=selected_row["material_code"] if selected_row is not None else "")
            with c2:
                material_name = st.text_input("부재료명", value=selected_row["material_name"] if selected_row is not None else "")
            with c3:
                material_type = st.selectbox("구분", SUB_MATERIAL_TYPES, index=SUB_MATERIAL_TYPES.index(selected_row["material_type"]) if selected_row is not None and selected_row["material_type"] in SUB_MATERIAL_TYPES else 0)
            with c4:
                status = st.selectbox("상태", MATERIAL_STATUS_OPTIONS, index=MATERIAL_STATUS_OPTIONS.index(selected_row["status"]) if selected_row is not None and selected_row["status"] in MATERIAL_STATUS_OPTIONS else 0)
            supplier_name = st.text_input("공급처", value=selected_row["supplier_name"] if selected_row is not None and pd.notna(selected_row["supplier_name"]) else "")
            backing_diameter = selected_row["backing_diameter"] if selected_row is not None and pd.notna(selected_row.get("backing_diameter")) else ""
            backing_thickness = selected_row["backing_thickness"] if selected_row is not None and pd.notna(selected_row.get("backing_thickness")) else ""
            backing_material_type = selected_row["backing_material_type"] if selected_row is not None and pd.notna(selected_row.get("backing_material_type")) else ""
            selected_label_film_id = int(selected_row["label_film_id"]) if selected_row is not None and pd.notna(selected_row.get("label_film_id")) else None
            label_film_label = next((label for label, film_id in label_film_options if film_id == selected_label_film_id), "")
            if material_type == "바킹":
                render_section_title("바킹 규격")
                spec_c1, spec_c2, spec_c3, spec_c4 = st.columns(4)
                with spec_c1:
                    backing_diameter = st.text_input("지름", value=backing_diameter)
                with spec_c2:
                    backing_thickness = st.text_input("두께", value=backing_thickness)
                with spec_c3:
                    backing_material_type = st.text_input("원단종류", value=backing_material_type)
                with spec_c4:
                    st.text_input("기타 기준", value="비고에 추가 입력", disabled=True)
            elif material_type == "라벨":
                render_section_title("라벨 원화")
                label_choices = [""] + [label for label, _ in label_film_options]
                label_film_label = st.selectbox("라벨 원화 선택", options=label_choices, index=label_choices.index(label_film_label) if label_film_label in label_choices else 0)
            notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None and pd.notna(selected_row["notes"]) else "")
            save_clicked, delete_clicked = render_page_actions(
                [
                    ("저장", "sub_material_form_save", True),
                    ("삭제", "sub_material_form_delete", selected_row is not None),
                ]
            )
            if delete_clicked and selected_row is not None:
                ok, message = master_service.delete_sub_material(int(selected_row["sub_material_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif save_clicked:
                duplicate = df[df["material_code"] == material_code]
                if selected_row is not None:
                    duplicate = duplicate[duplicate["sub_material_id"] != selected_row["sub_material_id"]]
                if material_type == "바킹" and (not backing_diameter.strip() or not backing_thickness.strip() or not backing_material_type.strip()):
                    st.error("바킹은 지름, 두께, 원단종류를 입력해 주세요.")
                elif material_type == "라벨" and not label_film_label:
                    st.error("라벨은 연결할 원화를 선택해 주세요.")
                elif not duplicate.empty:
                    st.error("부재료 코드는 중복될 수 없습니다.")
                else:
                    master_service.save_sub_material(
                        int(selected_row["sub_material_id"]) if selected_row is not None else None,
                        {
                            "material_code": material_code,
                            "material_name": material_name,
                            "material_type": material_type,
                            "supplier_name": supplier_name,
                            "backing_diameter": backing_diameter,
                            "backing_thickness": backing_thickness,
                            "backing_material_type": backing_material_type,
                            "label_film_id": dict(label_film_options).get(label_film_label),
                            "status": status,
                            "notes": notes,
                        },
                        current_user()["user_name"],
                    )
                    flash_success("부재료를 저장했습니다." if selected_row is None else "부재료를 수정했습니다.")
                    st.rerun()
    if not df.empty:
        render_history_panel("이력 보기", df)


MASTER_PAGE_RENDERERS = {
    "프로젝트 기본정보": render_projects_page,
    "상품": render_products_page,
    "공정품": render_items_page,
    "원재료": render_raw_materials_page,
    "부재료": render_sub_materials_page,
    "제품구성": render_bom_page,
    "제품도면": render_product_drawings_page,
    "원화": render_films_page,
}


def render_master_page(menu: str) -> bool:
    renderer = MASTER_PAGE_RENDERERS.get(menu)
    if renderer is None:
        return False
    renderer()
    return True
