from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from db.runtime import execute, execute_insert, format_revision, latest_rows_by_code, parse_revision_number, save_uploaded_file, try_delete
from domain.constants import MOLD_DRAWING_LAYOUTS, MOLD_STATUS_OPTIONS
from services import operations_service
from services.development_service import list_item_options_for_project, list_product_options_for_project
from services.reference_data_service import get_items, get_mold_drawings, get_molds, get_product_drawings, project_options, reset_cache
from services.shell_service import can_edit, current_user, flash_success, render_dataframe, render_form_actions, render_history_panel, render_page_actions, render_section_title, show_permission_hint


def render_molds_page() -> None:
    page_name = "금형 기본정보"
    st.subheader(page_name)
    show_permission_hint(page_name)
    projects = project_options()
    product_drawings_df = get_product_drawings()
    df = get_molds()
    mold_drawing_df = get_mold_drawings()
    if can_edit(page_name):
        pick_c1, pick_c2, pick_c3 = st.columns([1, 1.2, 0.8])
        with pick_c1:
            selected_project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="mold_project_label")
        selected_project_code = selected_project_label.split(" | ")[0] if selected_project_label else ""
        project_df = df[df["project_code"] == selected_project_code] if selected_project_code else df.iloc[0:0]
        project_drawings_df = product_drawings_df[product_drawings_df["project_code"] == selected_project_code] if selected_project_code else product_drawings_df.iloc[0:0]
        latest_project_drawings = latest_rows_by_code(project_drawings_df, "drawing_no", "product_drawing_id", "is_current")
        drawing_labels = [""] + latest_project_drawings.apply(lambda row: f"{row['project_code']} | {row['drawing_no']} | {row['revision_no']}", axis=1).tolist() if not latest_project_drawings.empty else [""]
        drawing_map = {
            f"{row['project_code']} | {row['drawing_no']} | {row['revision_no']}": int(row["product_drawing_id"])
            for _, row in latest_project_drawings.iterrows()
        }
        selected_row = None
        selected_drawing_row = None
        selected_label = "신규 등록"
        if selected_project_code:
            labels = ["신규 등록"]
            if not project_df.empty:
                labels += project_df.apply(lambda row: f"{row['mold_code']} | {row['mold_name']}", axis=1).tolist()
            with pick_c2:
                selected_label = st.selectbox("금형 선택", options=labels, key="mold_pick_label")
            if selected_label != "신규 등록":
                selected_row = project_df[project_df.apply(lambda row: f"{row['mold_code']} | {row['mold_name']}", axis=1) == selected_label].iloc[0]
            if selected_row is not None and not mold_drawing_df.empty and pd.notna(selected_row["mold_drawing_no"]):
                matches = mold_drawing_df[mold_drawing_df["mold_drawing_no"] == selected_row["mold_drawing_no"]]
                if not matches.empty:
                    matches = matches.copy()
                    matches["_revision_num"] = matches["revision_no"].apply(parse_revision_number)
                    selected_drawing_row = matches.sort_values(["_revision_num", "mold_drawing_id"], ascending=[False, False]).drop(columns=["_revision_num"]).iloc[0]
        with pick_c3:
            st.text_input("등록 모드", value="신규 등록" if selected_row is None else "기존 수정", disabled=True, key="mold_mode")
        render_section_title("기준 도면 정보")
        default_product_label = ""
        if selected_drawing_row is not None and pd.notna(selected_drawing_row["product_drawing_no"]):
            matching_rows = latest_project_drawings[latest_project_drawings["drawing_no"] == selected_drawing_row["product_drawing_no"]]
            if not matching_rows.empty:
                row = matching_rows.iloc[0]
                default_product_label = f"{row['project_code']} | {row['drawing_no']} | {row['revision_no']}"
        product_drawing_label = st.selectbox(
            "기준 제품도면",
            options=drawing_labels,
            index=drawing_labels.index(default_product_label) if default_product_label in drawing_labels else 0,
        )
        linked_product_drawing_id = drawing_map.get(product_drawing_label) if product_drawing_label else None
        linked_product_revision = 0
        if linked_product_drawing_id is not None:
            linked_row = latest_project_drawings[latest_project_drawings["product_drawing_id"] == linked_product_drawing_id].iloc[0]
            linked_product_revision = parse_revision_number(linked_row["revision_no"])
        render_section_title("금형도면 정보")
        top_c1, top_c2, top_c3 = st.columns(3)
        with top_c1:
            mold_drawing_no = st.text_input("금형도면 번호", value=selected_drawing_row["mold_drawing_no"] if selected_drawing_row is not None else "")
        existing_mold_revision = parse_revision_number(selected_drawing_row["revision_no"]) if selected_drawing_row is not None else 0
        with top_c2:
            reflect_mold_change = st.checkbox("금형 수정 반영", value=False, disabled=selected_row is None)
        next_mold_revision = max(existing_mold_revision, linked_product_revision)
        if selected_row is not None and reflect_mold_change:
            next_mold_revision += 1
        revision_no = format_revision(next_mold_revision)
        with top_c3:
            st.text_input("금형도면 리비전", value=revision_no, disabled=True)
        c0, c0b = st.columns(2)
        with c0:
            cavity_layout = st.selectbox("금형도면 Cavity 형식", MOLD_DRAWING_LAYOUTS, index=MOLD_DRAWING_LAYOUTS.index(selected_drawing_row["cavity_layout"]) if selected_drawing_row is not None and selected_drawing_row["cavity_layout"] in MOLD_DRAWING_LAYOUTS else 0)
        with c0b:
            design_priority = st.text_input("비용/시간 고려 메모", value=selected_drawing_row["design_priority"] if selected_drawing_row is not None else "")
        uploaded_mold_drawing = st.file_uploader("금형도면 첨부", type=None, key="mold_drawing_upload")
        render_section_title("금형 정보")
        mold_code = st.text_input("금형 코드", value=selected_row["mold_code"] if selected_row is not None else "")
        mold_name = st.text_input("금형명", value=selected_row["mold_name"] if selected_row is not None else "")
        c1, c2, c3 = st.columns(3)
        with c1:
            cavity = st.number_input("Cavity", min_value=1, step=1, value=int(selected_row["cavity"]) if selected_row is not None else 1)
        with c2:
            vendor_name = st.text_input("금형 제작처", value=selected_row["vendor_name"] if selected_row is not None else "")
        with c3:
            status = st.selectbox("상태", MOLD_STATUS_OPTIONS, index=MOLD_STATUS_OPTIONS.index(selected_row["status"]) if selected_row is not None and selected_row["status"] in MOLD_STATUS_OPTIONS else 0)
        notes = st.text_area("비고", height=88, value=selected_row["notes"] if selected_row is not None else "")
        save_clicked, delete_clicked = render_page_actions([("저장", "mold_save", True), ("삭제", "mold_delete", selected_row is not None)])
        if delete_clicked and selected_row is not None:
                ok, message = try_delete(
                    "DELETE FROM molds WHERE mold_id = ?",
                    (int(selected_row["mold_id"]),),
                )
                if ok and selected_drawing_row is not None:
                    try_delete(
                        "DELETE FROM mold_drawings WHERE mold_drawing_id = ?",
                        (int(selected_drawing_row["mold_drawing_id"]),),
                    )
                if ok:
                    reset_cache()
                    flash_success(message)
                    st.rerun()
                st.error(message)
        elif save_clicked:
                if not selected_project_label:
                    st.error("프로젝트를 먼저 선택해 주세요.")
                    return
                if not mold_code.strip():
                    st.error("금형 코드를 입력해 주세요.")
                    return
                if not mold_name.strip():
                    st.error("금형명을 입력해 주세요.")
                    return
                duplicate = df[df["mold_code"] == mold_code]
                if selected_row is not None:
                    duplicate = duplicate[duplicate["mold_id"] != selected_row["mold_id"]]
                if not duplicate.empty:
                    st.error("금형 코드는 중복될 수 없습니다.")
                else:
                    revision_changed = selected_drawing_row is None or revision_no != selected_drawing_row["revision_no"]
                    if revision_changed and uploaded_mold_drawing is None:
                        st.error("신규 등록 또는 리비전 변경 시 금형도면 파일을 첨부해 주세요.")
                    elif not mold_drawing_no:
                        st.error("금형도면 번호를 입력해 주세요.")
                    else:
                        drawing_file_path = save_uploaded_file(uploaded_mold_drawing, "mold_drawings") if uploaded_mold_drawing is not None else (selected_drawing_row["file_path"] if selected_drawing_row is not None else None)
                        project_id = dict(projects).get(selected_project_label)
                        try:
                            if selected_row is None:
                                mold_drawing_id = execute_insert(
                                    """
                                    INSERT INTO mold_drawings (
                                        project_id, product_drawing_id, mold_drawing_no, revision_no,
                                        cavity_layout, design_priority, file_path, notes, created_by, created_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        project_id,
                                        linked_product_drawing_id,
                                        mold_drawing_no,
                                        revision_no,
                                        cavity_layout,
                                        design_priority,
                                        drawing_file_path,
                                        notes,
                                        current_user()["user_name"],
                                        datetime.now().isoformat(timespec="seconds"),
                                    ),
                                )
                                execute(
                                    """
                                    INSERT INTO molds (
                                        project_id, mold_drawing_id, mold_code, mold_name, cavity,
                                        vendor_name, status, notes, created_by, created_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        project_id,
                                        mold_drawing_id,
                                        mold_code,
                                        mold_name,
                                        cavity,
                                        vendor_name,
                                        status,
                                        notes,
                                        current_user()["user_name"],
                                        datetime.now().isoformat(timespec="seconds"),
                                    ),
                                )
                            else:
                                if revision_changed:
                                    mold_drawing_id = execute_insert(
                                        """
                                        INSERT INTO mold_drawings (
                                            project_id, product_drawing_id, mold_drawing_no, revision_no,
                                            cavity_layout, design_priority, file_path, notes, created_by, created_at
                                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            project_id,
                                            linked_product_drawing_id,
                                            mold_drawing_no,
                                            revision_no,
                                            cavity_layout,
                                            design_priority,
                                            drawing_file_path,
                                            notes,
                                            current_user()["user_name"],
                                            datetime.now().isoformat(timespec="seconds"),
                                        ),
                                    )
                                else:
                                    mold_drawing_id = int(selected_drawing_row["mold_drawing_id"]) if selected_drawing_row is not None else None
                                if mold_drawing_id is not None and not revision_changed:
                                    execute(
                                        """
                                        UPDATE mold_drawings
                                        SET project_id = ?, product_drawing_id = ?, mold_drawing_no = ?, revision_no = ?,
                                            cavity_layout = ?, design_priority = ?, file_path = ?, notes = ?
                                        WHERE mold_drawing_id = ?
                                        """,
                                        (
                                            project_id,
                                            linked_product_drawing_id,
                                            mold_drawing_no,
                                            revision_no,
                                            cavity_layout,
                                            design_priority,
                                            drawing_file_path,
                                            notes,
                                            mold_drawing_id,
                                        ),
                                    )
                                execute(
                                    """
                                    UPDATE molds
                                    SET project_id = ?, mold_code = ?, mold_name = ?, cavity = ?, vendor_name = ?, status = ?, notes = ?
                                        , mold_drawing_id = ?
                                    WHERE mold_id = ?
                                    """,
                                    (
                                        project_id,
                                        mold_code,
                                        mold_name,
                                        cavity,
                                        vendor_name,
                                        status,
                                        notes,
                                        mold_drawing_id,
                                        int(selected_row["mold_id"]),
                                    ),
                                )
                        except Exception as exc:
                            st.error(f"금형 저장에 실패했습니다. 금형코드: {mold_code} | 사유: {exc}")
                        else:
                            reset_cache()
                            flash_success(f"금형 정보를 저장했습니다. 금형코드: {mold_code} | 금형도면 리비전: {revision_no}")
                            st.rerun()
    if not df.empty:
        render_history_panel("이력 보기", df)
        if not mold_drawing_df.empty:
            render_history_panel("금형도면 이력", mold_drawing_df)


def render_mold_dispatch_page() -> None:
    page_name = "금형 출고입고"
    st.subheader(page_name)
    show_permission_hint(page_name)
    df = operations_service.list_mold_dispatch_orders()
    molds_df = operations_service.list_molds()
    mold_drawings_df = get_mold_drawings()
    items_df = get_items()
    if can_edit(page_name):
        available_df = (
            df[df["status"].fillna("").astype(str) != "입고완료"].copy()
            if not df.empty
            else df
        )
        labels = ["선택 안 함"]
        if not available_df.empty:
            labels += available_df.apply(lambda row: f"{row['dispatch_code']} | {row['item_code']} | {row['status']}", axis=1).tolist()
        pick_c1, pick_c2 = st.columns([2, 1])
        with pick_c1:
            selected_label = st.selectbox("금형 출고지시 선택", options=labels, key="mold_dispatch_pick")
        selected_row = None
        if selected_label != "선택 안 함":
            selected_row = available_df[available_df.apply(lambda row: f"{row['dispatch_code']} | {row['item_code']} | {row['status']}", axis=1) == selected_label].iloc[0]
        with pick_c2:
            st.text_input("처리 모드", value="지시 선택" if selected_row is not None else "선택 대기", disabled=True, key="mold_dispatch_mode")
        candidate_molds_df = molds_df
        mold_filter_note = ""
        selected_item_row = None
        if selected_row is not None and not items_df.empty:
            matched_item = items_df[items_df["item_id"] == selected_row["item_id"]]
            if not matched_item.empty:
                selected_item_row = matched_item.iloc[0]
        if selected_item_row is not None and not molds_df.empty:
            linked_product_drawing_id = int(selected_item_row["product_drawing_id"]) if pd.notna(selected_item_row["product_drawing_id"]) else None
            primary_mold_id = int(selected_item_row["primary_mold_id"]) if pd.notna(selected_item_row["primary_mold_id"]) else None
            linked_mold_ids: set[int] = set()
            if linked_product_drawing_id is not None and not mold_drawings_df.empty:
                linked_drawing_nos = set(
                    mold_drawings_df[mold_drawings_df["product_drawing_id"] == linked_product_drawing_id]["mold_drawing_no"].dropna().astype(str).tolist()
                )
                if linked_drawing_nos:
                    linked_mold_ids.update(
                        molds_df[molds_df["mold_drawing_no"].fillna("").astype(str).isin(linked_drawing_nos)]["mold_id"].dropna().astype(int).tolist()
                    )
            if primary_mold_id is not None:
                linked_mold_ids.add(primary_mold_id)
            if linked_mold_ids:
                candidate_molds_df = molds_df[molds_df["mold_id"].isin(sorted(linked_mold_ids))].copy()
                mold_filter_note = "사출품 연계 도면/기본금형 기준으로 후보를 좁혔습니다."
            else:
                mold_filter_note = "연계 금형이 없어 전체 금형 목록을 표시합니다."
        mold_options_for_dispatch = [""] + candidate_molds_df.apply(lambda row: f"{row['mold_code']} | {row['mold_name']}", axis=1).tolist() if not candidate_molds_df.empty else [""]
        selected_mold_label = ""
        if selected_row is not None and pd.notna(selected_row["mold_code"]):
            selected_mold_label = f"{selected_row['mold_code']} | {selected_row['mold_name']}"
        can_dispatch = selected_row is not None and str(selected_row["status"] or "") in {"출고지시", "수정요청"}
        can_receipt = selected_row is not None and str(selected_row["status"] or "") in {"출고완료", "입고예정"}
        left_c, right_c = st.columns([1.0, 1.3])
        sample_request_display = ""
        if selected_row is not None:
            if pd.notna(selected_row["sample_request_date"]) and str(selected_row["sample_request_date"] or "").strip():
                sample_request_display = str(selected_row["sample_request_date"])
            elif pd.notna(selected_row["target_due_date"]) and str(selected_row["target_due_date"] or "").strip():
                sample_request_display = str(selected_row["target_due_date"])
        with left_c:
            st.markdown("**지시요약**")
            st.text_input("요구코드", value=selected_row["order_code"] if selected_row is not None else "", disabled=True)
            st.text_input("샘플요청일", value=sample_request_display, disabled=True)
            st.text_input(
                "지시코드",
                value=str(selected_row["instruction_code"] or "") if selected_row is not None and pd.notna(selected_row["instruction_code"]) else "",
                disabled=True,
            )
            st.text_input(
                "지시완료일",
                value=str(selected_row["requested_finish_date"] or "") if selected_row is not None and pd.notna(selected_row["requested_finish_date"]) else "",
                disabled=True,
            )
            st.text_input("공정품", value=f"{selected_row['item_code']} | {selected_row['item_name']}" if selected_row is not None else "", disabled=True)
        with right_c:
            st.markdown("**실행입력**")
            mold_label = st.selectbox(
                "대상 금형",
                options=mold_options_for_dispatch,
                index=mold_options_for_dispatch.index(selected_mold_label) if selected_mold_label in mold_options_for_dispatch else 0,
            )
            if mold_filter_note:
                st.caption(mold_filter_note)
            date_c1, date_c2 = st.columns(2)
            with date_c1:
                dispatch_date = st.date_input(
                    "출고일",
                    value=pd.to_datetime(selected_row["dispatch_date"]).date() if selected_row is not None and selected_row["dispatch_date"] else None,
                )
            with date_c2:
                receipt_date = st.date_input(
                    "입고일",
                    value=pd.to_datetime(selected_row["receipt_date"]).date() if selected_row is not None and selected_row["receipt_date"] else None,
                )
            modification_note = st.text_area(
                "내용/비고",
                height=88,
                value=selected_row["modification_note"] if selected_row is not None and pd.notna(selected_row["modification_note"]) else "",
            )
        dispatch_clicked, receipt_clicked = render_page_actions([("출고 실행", "mold_dispatch_execute", can_dispatch), ("입고 완료", "mold_dispatch_receipt", can_receipt)])
        if dispatch_clicked and selected_row is not None:
            if not mold_label or not dispatch_date:
                st.error("출고 실행 전에 대상 금형과 금형 출고일을 입력해 주세요.")
            else:
                mold_map = {
                    f"{row['mold_code']} | {row['mold_name']}": int(row["mold_id"])
                    for _, row in candidate_molds_df.iterrows()
                }
                try:
                    operations_service.execute_mold_dispatch(
                        int(selected_row["mold_dispatch_order_id"]),
                        mold_id=mold_map.get(mold_label),
                        sample_request_date=sample_request_display or None,
                        dispatch_date=str(dispatch_date) if dispatch_date else None,
                        modification_note=modification_note,
                    )
                except Exception as exc:
                    st.error(f"금형 출고 실행에 실패했습니다. 지시코드: {selected_row['dispatch_code']} | 사유: {exc}")
                else:
                    flash_success(f"금형 출고를 실행했습니다. 지시코드: {selected_row['dispatch_code']}")
                    st.rerun()
        elif dispatch_clicked:
            if selected_row is None:
                st.error("금형 출고지시를 먼저 선택해 주세요.")
            else:
                st.error("현재 상태에서는 출고 실행을 할 수 없습니다.")
        elif receipt_clicked and selected_row is not None:
            if str(selected_row["status"] or "") not in ["출고완료", "입고예정"]:
                st.error("출고 실행된 금형만 입고 처리할 수 있습니다.")
            elif not selected_row["dispatch_date"]:
                st.error("금형 출고일이 기록된 건만 입고 처리할 수 있습니다.")
            elif not receipt_date:
                st.error("금형 입고일을 입력해 주세요.")
            else:
                try:
                    operations_service.complete_mold_dispatch_receipt(
                        int(selected_row["mold_dispatch_order_id"]),
                        receipt_date=str(receipt_date),
                        modification_note=modification_note,
                    )
                except Exception as exc:
                    st.error(f"금형 입고 처리에 실패했습니다. 지시코드: {selected_row['dispatch_code']} | 사유: {exc}")
                else:
                    flash_success(f"금형 입고를 완료 처리했습니다. 지시코드: {selected_row['dispatch_code']}")
                    st.rerun()
        elif receipt_clicked:
            if selected_row is None:
                st.error("입고 처리할 금형 출고지시를 먼저 선택해 주세요.")
            else:
                st.error("현재 상태에서는 입고 완료를 처리할 수 없습니다.")
    if not df.empty:
        render_history_panel("이력 보기", df)


def render_mb_requests_page() -> None:
    page_name = "MB 의뢰"
    st.subheader(page_name)
    show_permission_hint(page_name)
    df = operations_service.list_mb_requests()
    if can_edit(page_name):
        available_df = df[df["purchase_requested"] != 1].copy() if not df.empty else df
        labels = ["선택 안 함"]
        if not available_df.empty:
            labels += available_df.apply(lambda row: f"{row['request_code']} | {row['item_code']} | {row['color_nuance']}", axis=1).tolist()
        pick_c1, pick_c2 = st.columns([2, 1])
        with pick_c1:
            selected_label = st.selectbox("MB 의뢰 선택", options=labels, key="mb_request_pick")
        selected_row = None
        if selected_label != "선택 안 함":
            selected_row = available_df[
                available_df.apply(lambda row: f"{row['request_code']} | {row['item_code']} | {row['color_nuance']}", axis=1) == selected_label
            ].iloc[0]
        with pick_c2:
            st.text_input("처리 모드", value="의뢰 선택" if selected_row is not None else "선택 대기", disabled=True, key="mb_request_mode")
        with st.form("mb_request_form"):
            top_c1, top_c2, top_c3 = st.columns(3)
            with top_c1:
                st.text_input("MB 의뢰번호", value=selected_row["request_code"] if selected_row is not None else "", disabled=True)
            with top_c2:
                st.text_input("고객요구", value=selected_row["order_code"] if selected_row is not None else "", disabled=True)
            with top_c3:
                st.text_input("공정품", value=f"{selected_row['item_code']} | {selected_row['item_name']}" if selected_row is not None else "", disabled=True)
            req_c1, req_c2, req_c3 = st.columns(3)
            with req_c1:
                st.text_input("색상 뉴앙스", value=selected_row["color_nuance"] if selected_row is not None else "", disabled=True)
            with req_c2:
                st.checkbox("색상샘플 유무", value=bool(selected_row["color_sample_exists"]) if selected_row is not None else False, disabled=True)
            with req_c3:
                sample_sent = st.checkbox("샘플전달 여부", value=bool(selected_row["sample_sent"]) if selected_row is not None else False)
            supplier_name = st.text_input("협의 업체", value=selected_row["supplier_name"] if selected_row is not None and pd.notna(selected_row["supplier_name"]) else "")
            consultation_note = st.text_area("업체협의 내용", height=88, value=selected_row["consultation_note"] if selected_row is not None and pd.notna(selected_row["consultation_note"]) else "")
            expected_receipt_date = st.date_input("입고예정일", value=pd.to_datetime(selected_row["expected_receipt_date"]).date() if selected_row is not None and selected_row["expected_receipt_date"] else None)
            save_clicked, purchase_clicked, delete_clicked = render_form_actions([("의뢰 정보 저장", True), ("구매지시 생성", selected_row is not None), ("삭제", selected_row is not None)])
            if save_clicked and selected_row is not None:
                operations_service.save_mb_request_consultation(
                    int(selected_row["mb_request_id"]),
                    sample_sent=sample_sent,
                    supplier_name=supplier_name,
                    consultation_note=consultation_note,
                    expected_receipt_date=str(expected_receipt_date) if expected_receipt_date else None,
                )
                flash_success("MB 의뢰 정보를 저장했습니다.")
                st.rerun()
            elif delete_clicked and selected_row is not None:
                ok, message = operations_service.delete_mb_request(int(selected_row["mb_request_id"]))
                if ok:
                    flash_success(message)
                    st.rerun()
                st.error(message)
            elif purchase_clicked and selected_row is not None:
                if not supplier_name or not expected_receipt_date:
                    st.error("구매지시 생성 전에 협의 업체와 입고예정일을 입력해 주세요.")
                else:
                    operations_service.create_mb_purchase_request(
                        int(selected_row["mb_request_id"]),
                        sample_sent=sample_sent,
                        supplier_name=supplier_name,
                        consultation_note=consultation_note,
                        expected_receipt_date=str(expected_receipt_date),
                    )
                    flash_success(f"MB 구매지시를 생성했습니다. 지시코드: {selected_row['request_code']}")
                    st.rerun()
    if not df.empty:
        render_history_panel("이력 보기", df)


def render_mb_receipts_page() -> None:
    page_name = "MB 구매입고"
    st.subheader(page_name)
    show_permission_hint(page_name)
    operations_service.sync_mb_request_receipt_statuses()
    requests_df = operations_service.list_mb_requests()
    receipts_df = operations_service.list_mb_receipts()
    if can_edit(page_name):
        completed_request_ids = (
            set(receipts_df["mb_request_id"].dropna().astype(int).tolist())
            if not receipts_df.empty and "mb_request_id" in receipts_df.columns
            else set()
        )
        available_df = (
            requests_df[
                (requests_df["purchase_requested"] == 1)
                & (~requests_df["mb_request_id"].astype(int).isin(completed_request_ids))
            ].copy()
            if not requests_df.empty
            else requests_df
        )
        labels = ["선택 안 함"]
        if not available_df.empty:
            labels += available_df.apply(lambda row: f"{row['request_code']} | {row['item_code']} | {row['color_nuance']}", axis=1).tolist()
        pick_c1, pick_c2, pick_c3 = st.columns([1.2, 1.2, 0.8])
        with pick_c1:
            selected_label = st.selectbox("구매지시 선택", options=labels, key="mb_receipt_pick")
        selected_request = None
        if selected_label != "선택 안 함":
            selected_request = available_df[available_df.apply(lambda row: f"{row['request_code']} | {row['item_code']} | {row['color_nuance']}", axis=1) == selected_label].iloc[0]
        receipt_labels = ["신규 등록"]
        if not receipts_df.empty:
            receipt_labels += receipts_df.apply(lambda row: f"{row['request_code']} | {row['item_code']} | {row['lot_no'] or '-'}", axis=1).tolist()
        with pick_c2:
            selected_receipt_label = st.selectbox("입고 이력 선택", options=receipt_labels, key="mb_receipt_history_pick")
        selected_receipt_row = None
        if selected_receipt_label != "신규 등록":
            selected_receipt_row = receipts_df[receipts_df.apply(lambda row: f"{row['request_code']} | {row['item_code']} | {row['lot_no'] or '-'}", axis=1) == selected_receipt_label].iloc[0]
            if selected_request is None:
                matched_request = requests_df[requests_df["mb_request_id"] == selected_receipt_row["mb_request_id"]]
                if not matched_request.empty:
                    selected_request = matched_request.iloc[0]
        with pick_c3:
            st.text_input("등록 모드", value="신규 등록" if selected_receipt_row is None else "기존 수정", disabled=True, key="mb_receipt_mode")
        existing_receipt = None
        if selected_request is not None and not receipts_df.empty:
            matched = receipts_df[receipts_df["mb_request_id"] == selected_request["mb_request_id"]]
            if not matched.empty:
                existing_receipt = matched.iloc[0]
        if selected_receipt_row is not None:
            existing_receipt = selected_receipt_row
        body_c1, body_c2 = st.columns([1.0, 1.4])
        with body_c1:
            st.markdown("**지시요약**")
            st.text_input("실험지시번호", value=str(selected_request["instruction_code"] or "") if selected_request is not None and pd.notna(selected_request["instruction_code"]) else "", disabled=True)
            st.text_input("완료일", value=str(selected_request["requested_finish_date"] or "") if selected_request is not None and pd.notna(selected_request["requested_finish_date"]) else "", disabled=True)
            st.text_input("MB 의뢰번호", value=selected_request["request_code"] if selected_request is not None else "", disabled=True)
            st.text_input("입고예정일", value=str(selected_request["expected_receipt_date"] or "") if selected_request is not None and pd.notna(selected_request["expected_receipt_date"]) else "", disabled=True)
        with body_c2:
            form_top_c1, form_top_c2, form_top_c3 = st.columns(3)
            with form_top_c1:
                receipt_date = st.date_input(
                    "입고일",
                    value=pd.to_datetime(existing_receipt["receipt_date"]).date()
                    if existing_receipt is not None and existing_receipt["receipt_date"]
                    else None,
                    key="mb_receipt_date",
                )
            with form_top_c2:
                receipt_qty = st.number_input(
                    "입고수량",
                    min_value=0.0,
                    step=1.0,
                    value=float(existing_receipt["receipt_qty"])
                    if existing_receipt is not None and pd.notna(existing_receipt["receipt_qty"])
                    else 0.0,
                    key="mb_receipt_qty",
                )
            with form_top_c3:
                lot_no = st.text_input(
                    "Lot",
                    value=existing_receipt["lot_no"]
                    if existing_receipt is not None and pd.notna(existing_receipt["lot_no"])
                    else "",
                    key="mb_receipt_lot",
                )
            receipt_note = st.text_area(
                "입고 메모",
                height=88,
                value=existing_receipt["receipt_note"]
                if existing_receipt is not None and pd.notna(existing_receipt["receipt_note"])
                else "",
                key="mb_receipt_note",
            )
        action_c1, action_c2 = st.columns(2)
        with action_c1:
            save_clicked = st.button("입고 저장", use_container_width=True, key="mb_receipt_save")
        with action_c2:
            delete_clicked = st.button("삭제", disabled=existing_receipt is None, use_container_width=True, key="mb_receipt_delete")
        if delete_clicked and existing_receipt is not None:
            ok, message = operations_service.delete_mb_receipt(
                int(existing_receipt["mb_receipt_id"]),
                mb_request_id=int(existing_receipt["mb_request_id"]),
            )
            if ok:
                flash_success(message)
                st.rerun()
            st.error(message)
        elif save_clicked and selected_request is None:
            st.error("입고 저장할 구매지시를 먼저 선택해 주세요.")
        elif save_clicked and selected_request is not None:
            receipt_result = operations_service.save_mb_receipt(
                mb_request_id=int(selected_request["mb_request_id"]),
                receipt_date=str(receipt_date) if receipt_date else None,
                receipt_qty=receipt_qty,
                lot_no=lot_no,
                receipt_note=receipt_note,
                current_user_name=current_user()["user_name"],
                existing_receipt_id=int(existing_receipt["mb_receipt_id"]) if existing_receipt is not None else None,
            )
            flash_success(
                f"MB 입고를 저장했습니다. 품목코드: {receipt_result.get('item_code') or '-'} | 현재재고: {receipt_result.get('current_stock') or 0}"
            )
            st.rerun()
    if not receipts_df.empty:
        render_history_panel("이력 보기", receipts_df)


def _wms_move_label(row: pd.Series) -> str:
    source_code = str(row.get("source_order_code") or row.get("source_instruction_code") or "").strip()
    actual_item_code = str(row.get("actual_item_code") or "").strip()
    parts = [
        str(row.get("move_code") or "").strip(),
        str(row.get("wms_kind") or "").strip(),
        str(row.get("sample_code") or "").strip(),
        str(row.get("item_code") or "").strip(),
        actual_item_code if actual_item_code and actual_item_code != str(row.get("item_code") or "").strip() else "",
        str(row.get("status") or "").strip(),
    ]
    if source_code:
        parts.append(source_code)
    return " | ".join([part for part in parts if part])


def _wms_dispatch_pick_label(row: pd.Series) -> str:
    due_date = str(row.get("expected_receipt_date") or "").strip()
    order_code = str(row.get("source_order_code") or "").strip()
    parts = [part for part in [due_date, order_code] if part]
    return " | ".join(parts) if parts else _wms_move_label(row)


def _wms_receipt_pick_label(row: pd.Series) -> str:
    expected_date = str(row.get("expected_receipt_date") or "").strip()
    instruction_code = str(row.get("source_instruction_code") or "").strip()
    parts = [part for part in [expected_date, instruction_code] if part]
    return " | ".join(parts) if parts else _wms_move_label(row)


def _inventory_label(row: pd.Series) -> str:
    return " | ".join(
        [
            part
            for part in [
                str(row.get("sample_code") or "").strip(),
                str(row.get("item_code") or "").strip(),
                str(row.get("item_name") or "").strip(),
                str(row.get("current_location") or "").strip(),
            ]
            if part
        ]
    )


def _wms_flow_status_text(row: pd.Series) -> str:
    has_instruction = bool(str(row.get("source_instruction_code") or "").strip())
    has_sample = pd.notna(row.get("sample_id")) or bool(str(row.get("sample_code") or "").strip())
    experiment_date = pd.to_datetime(row.get("experiment_date"), errors="coerce")
    quality_review_date = pd.to_datetime(row.get("quality_review_date"), errors="coerce")
    final_review_date = pd.to_datetime(row.get("final_review_date"), errors="coerce")
    approval_status = str(row.get("approval_status") or "").strip()

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
    return approval_status or "최종검토"


def render_wms_items_page() -> None:
    page_name = "WMS_공정품"
    st.subheader(page_name)
    show_permission_hint(page_name)
    operations_service.prepare_wms(current_user_name=current_user()["user_name"])
    projects = operations_service.list_project_options()
    moves_df = operations_service.list_postprocess_item_moves()
    inventory_df = operations_service.list_sample_inventory()
    if can_edit(page_name):
        all_inventory = inventory_df.copy()
        header_c1, header_c2, header_c3, header_c4 = st.columns([1, 1, 1, 1])
        with header_c1:
            project_label = st.selectbox("프로젝트", options=[""] + [label for label, _ in projects], key="wms_project_label")
        project_code = project_label.split(" | ")[0] if project_label else ""
        product_choices = list_product_options_for_project(project_code) if project_code else []
        with header_c2:
            product_label = st.selectbox("상품", options=[""] + [label for label, _ in product_choices], key="wms_product_label")
        selected_product_id = dict(product_choices).get(product_label) if product_label else None
        item_choices = list_item_options_for_project(project_code) if project_code else []
        with header_c3:
            item_label = st.selectbox("공정품", options=[""] + [label for label, _ in item_choices], key="wms_item_label")
        selected_item_id = dict(item_choices).get(item_label) if item_label else None
        with header_c4:
            category_filter = st.selectbox("구분", options=["전체", "고객", "외주", "내부"], key="wms_category_filter")

        project_moves = moves_df[moves_df["project_code"] == project_code].copy() if project_code else moves_df.copy()
        project_inventory = inventory_df[inventory_df["project_code"] == project_code].copy() if project_code else inventory_df.copy()
        if selected_product_id:
            project_moves = project_moves[pd.to_numeric(project_moves["product_id"], errors="coerce") == int(selected_product_id)]
            project_inventory = project_inventory[pd.to_numeric(project_inventory["product_id"], errors="coerce") == int(selected_product_id)]
        if selected_item_id:
            project_moves = project_moves[pd.to_numeric(project_moves["item_id"], errors="coerce") == int(selected_item_id)]
            project_inventory = project_inventory[pd.to_numeric(project_inventory["item_id"], errors="coerce") == int(selected_item_id)]
        if category_filter == "고객":
            project_moves = project_moves[
                (project_moves["source_type"] == "고객요구")
                | (project_moves["partner_name"] == "고객")
            ]
            project_inventory = project_inventory.iloc[0:0]
        elif category_filter == "외주":
            project_moves = project_moves[
                ~project_moves["partner_name"].isin(["내부", "고객"])
            ]
            project_inventory = project_inventory[
                ~project_inventory["partner_name"].isin(["내부", "고객"])
            ]
        elif category_filter == "내부":
            project_moves = project_moves[project_moves["partner_name"] == "내부"]
            project_inventory = project_inventory[project_inventory["partner_name"] == "내부"]

        dispatch_tab, receipt_tab, inventory_tab, adjust_tab = st.tabs(["출고실행", "입고관리", "재고현황", "재고조정"])

        with dispatch_tab:
            render_section_title("출고실행")
            dispatch_moves = (
                project_moves[
                    project_moves["wms_kind"].isin(["고객출고지시", "공정품출고지시", "전공정품출고지시"])
                    & project_moves["status"].isin(["최종검토대기", "출고대기"])
                ].copy()
                if not project_moves.empty
                else project_moves
            )
            left_col, right_col = st.columns([1.05, 1.95])
            with left_col:
                if dispatch_moves.empty:
                    st.caption("출고 실행 대상 지시가 없습니다.")
                else:
                    dispatch_labels = [""] + dispatch_moves.apply(_wms_dispatch_pick_label, axis=1).tolist()
                    selected_dispatch_label = st.selectbox("출고지시", options=dispatch_labels, key="wms_dispatch_pick")
                    selected_dispatch_row = dispatch_moves[dispatch_moves.apply(_wms_dispatch_pick_label, axis=1) == selected_dispatch_label].iloc[0] if selected_dispatch_label else None
            with right_col:
                if dispatch_moves.empty or 'selected_dispatch_row' not in locals() or selected_dispatch_row is None:
                    st.info("좌측에서 출고지시를 선택하면 실행 카드가 열립니다.")
                else:
                    selected_sample_id = int(selected_dispatch_row["sample_id"]) if pd.notna(selected_dispatch_row["sample_id"]) else None
                    inventory_match = all_inventory[all_inventory["sample_id"] == selected_sample_id] if (not all_inventory.empty and selected_sample_id is not None) else all_inventory.iloc[0:0]
                    inventory_row = inventory_match.iloc[0] if not inventory_match.empty else None
                    st.caption("지시 기반 출고만 실행할 수 있습니다.")
                    if str(selected_dispatch_row["status"] or "") == "최종검토대기":
                        st.info("이 건은 고객출고지시가 생성된 상태입니다. 최종검토에서 샘플을 확정하면 `출고대기`로 전환됩니다.")
                    info_entries = [
                        ("공정품", " | ".join([part for part in [str(selected_dispatch_row["item_code"] or "").strip(), str(selected_dispatch_row["item_name"] or "").strip()] if part]) or "-"),
                        ("샘플코드", str(selected_dispatch_row["sample_code"] or "-")),
                        ("요구수량", str(selected_dispatch_row["requested_qty"] or "-")),
                        ("현재상태", _wms_flow_status_text(selected_dispatch_row)),
                        ("재고수량", str(inventory_row["qty_on_hand"]) if inventory_row is not None else "-"),
                        ("가용수량", str(inventory_row["qty_available"]) if inventory_row is not None else "-"),
                        ("위치", str(inventory_row["current_location"]) if inventory_row is not None else "-"),
                    ]
                    _cols = st.columns(3)
                    for idx, (label, value) in enumerate(info_entries):
                        with _cols[idx % 3]:
                            st.caption(label)
                            st.write(value)
                    with st.form(f"wms_dispatch_form_{int(selected_dispatch_row['postprocess_move_id'])}"):
                        form_c1, form_c2, form_c3 = st.columns(3)
                        with form_c1:
                            partner_name = st.text_input("업체정보", value=str(selected_dispatch_row["partner_name"] or "내부"))
                            from_location = st.text_input("출고위치", value=str(inventory_row["current_location"]) if inventory_row is not None else str(selected_dispatch_row["from_location"] or "샘플창고"))
                        with form_c2:
                            to_location = st.text_input("도착위치", value=str(selected_dispatch_row["to_location"] or selected_dispatch_row["process_type"] or "개발실"))
                            dispatch_date = st.date_input("출고일", value=datetime.now().date(), key=f"wms_dispatch_date_{int(selected_dispatch_row['postprocess_move_id'])}")
                        with form_c3:
                            physical_checked = st.checkbox("실물확인", value=False, key=f"wms_dispatch_physical_{int(selected_dispatch_row['postprocess_move_id'])}")
                            dispatch_qty = st.number_input("출고수량", min_value=0.0, step=1.0, value=float(selected_dispatch_row["requested_qty"] or 0), key=f"wms_dispatch_qty_{int(selected_dispatch_row['postprocess_move_id'])}")
                        dispatch_note = st.text_area("비고", height=88, value=str(selected_dispatch_row["child_dispatch_note"] or ""))
                        (dispatch_clicked,) = render_form_actions([("출고 저장", True)])
                        if dispatch_clicked:
                            if str(selected_dispatch_row["status"] or "") != "출고대기":
                                st.error("현재 상태에서는 아직 출고를 실행할 수 없습니다. 최종검토 완료 후 진행해 주세요.")
                            elif selected_sample_id is None:
                                st.error("최종검토에서 발송 샘플이 아직 확정되지 않았습니다.")
                            elif not physical_checked:
                                st.error("실물확인을 먼저 체크해 주세요.")
                            elif dispatch_qty <= 0:
                                st.error("출고수량을 입력해 주세요.")
                            else:
                                try:
                                    operations_service.execute_wms_dispatch(
                                        postprocess_move_id=int(selected_dispatch_row["postprocess_move_id"]),
                                        sample_id=int(selected_sample_id),
                                        dispatch_qty=float(dispatch_qty),
                                        dispatch_date=str(dispatch_date),
                                        from_location=from_location,
                                        to_location=to_location,
                                        partner_name=partner_name or "내부",
                                        current_user_name=current_user()["user_name"],
                                    )
                                    flash_success("출고를 저장했습니다.")
                                    st.rerun()
                                except ValueError as exc:
                                    st.error(str(exc))
        with receipt_tab:
            render_section_title("입고관리")
            receipt_moves = project_moves[(project_moves["wms_kind"] == "입고예정") & (project_moves["status"] == "입고예정")].copy() if not project_moves.empty else project_moves
            left_col, right_col = st.columns([1.05, 1.95])
            with left_col:
                if receipt_moves.empty:
                    st.caption("입고예정 건이 없습니다.")
                else:
                    receipt_labels = [""] + receipt_moves.apply(_wms_receipt_pick_label, axis=1).tolist()
                    selected_receipt_label = st.selectbox("입고예정", options=receipt_labels, key="wms_receipt_pick")
                    selected_receipt_row = receipt_moves[receipt_moves.apply(_wms_receipt_pick_label, axis=1) == selected_receipt_label].iloc[0] if selected_receipt_label else None
            with right_col:
                if receipt_moves.empty or 'selected_receipt_row' not in locals() or selected_receipt_row is None:
                    st.info("좌측에서 입고예정 건을 선택하면 입고 카드가 열립니다.")
                else:
                    expected_date = str(selected_receipt_row["expected_receipt_date"] or "-")
                    st.caption(f"예정입고일: {expected_date}")
                    status_cols = st.columns(4)
                    with status_cols[0]:
                        st.caption("요구상태")
                        st.write(str(selected_receipt_row["source_order_status"] or "-"))
                    with status_cols[1]:
                        st.caption("지시상태")
                        st.write(str(selected_receipt_row["source_instruction_status"] or "-"))
                    with status_cols[2]:
                        st.caption("샘플상태")
                        st.write(str(selected_receipt_row["sample_status"] or "-"))
                    with status_cols[3]:
                        st.caption("입출고상태")
                        st.write(str(selected_receipt_row["status"] or "-"))
                    st.caption(
                        " | ".join(
                            [
                                part
                                for part in [
                                    str(selected_receipt_row["wms_kind"] or "").strip(),
                                    str(selected_receipt_row["item_code"] or "").strip(),
                                    str(selected_receipt_row["item_name"] or "").strip(),
                                ]
                                if part
                            ]
                        )
                    )
                    with st.form(f"wms_receipt_form_{int(selected_receipt_row['postprocess_move_id'])}"):
                        rc1, rc2, rc3 = st.columns(3)
                        with rc1:
                            partner_name = st.text_input("업체정보", value=str(selected_receipt_row["partner_name"] or "내부"))
                            to_location = st.text_input("입고위치", value=str(selected_receipt_row["to_location"] or "샘플창고"))
                        with rc2:
                            receipt_date = st.date_input("실제입고일", value=datetime.now().date(), key=f"wms_receipt_date_{int(selected_receipt_row['postprocess_move_id'])}")
                            receipt_qty = st.number_input("실제입고수량", min_value=0.0, step=1.0, value=float(selected_receipt_row["dispatch_qty"] or selected_receipt_row["requested_qty"] or 0), key=f"wms_receipt_qty_{int(selected_receipt_row['postprocess_move_id'])}")
                        with rc3:
                            physical_checked = st.checkbox("실물확인", value=False, key=f"wms_receipt_physical_{int(selected_receipt_row['postprocess_move_id'])}")
                            is_external = str(selected_receipt_row["partner_name"] or "내부") != "내부"
                        cost_c1, cost_c2, cost_c3, cost_c4 = st.columns(4)
                        with cost_c1:
                            unit_cost = st.number_input("공정단가", min_value=0.0, step=1.0, value=float(selected_receipt_row["unit_cost"] or 0.0), disabled=not is_external)
                        with cost_c2:
                            uph = st.number_input("UPH", min_value=0.0, step=1.0, value=float(selected_receipt_row["uph"] or 0.0), disabled=not is_external)
                        with cost_c3:
                            defect_rate = st.number_input("불량률", min_value=0.0, step=0.1, value=float(selected_receipt_row["defect_rate"] or 0.0), disabled=not is_external)
                        with cost_c4:
                            moq = st.number_input("MOQ", min_value=0.0, step=1.0, value=float(selected_receipt_row["moq"] or 0.0), disabled=not is_external)
                        receipt_note = st.text_area("입고 메모", height=88, value=str(selected_receipt_row["receipt_note"] or ""))
                        (receipt_clicked,) = render_form_actions([("입고 완료 저장", True)])
                        if receipt_clicked:
                            if not physical_checked:
                                st.error("실물확인을 먼저 체크해 주세요.")
                            elif receipt_qty <= 0:
                                st.error("실제입고수량을 입력해 주세요.")
                            else:
                                operations_service.complete_wms_receipt(
                                    postprocess_move_id=int(selected_receipt_row["postprocess_move_id"]),
                                    receipt_date=str(receipt_date),
                                    receipt_qty=float(receipt_qty),
                                    to_location=to_location,
                                    partner_name=partner_name or "내부",
                                    receipt_note=receipt_note,
                                    unit_cost=float(unit_cost) if is_external else None,
                                    uph=float(uph) if is_external else None,
                                    defect_rate=float(defect_rate) if is_external else None,
                                    moq=float(moq) if is_external else None,
                                    current_user_name=current_user()["user_name"],
                                )
                                flash_success("입고완료를 저장했습니다.")
                                st.rerun()
        with inventory_tab:
            render_section_title("재고현황")
            if project_inventory.empty:
                st.caption("조회할 재고가 없습니다.")
            else:
                render_dataframe(
                    project_inventory[["sample_code", "item_code", "item_name", "process_type", "qty_on_hand", "qty_reserved", "qty_available", "current_location", "partner_name", "status"]]
                )

        with adjust_tab:
            render_section_title("재고조정")
            if project_inventory.empty:
                st.caption("조정할 재고가 없습니다.")
            else:
                adj_left, adj_right = st.columns([1.05, 1.95])
                with adj_left:
                    inventory_labels = [""] + project_inventory.apply(_inventory_label, axis=1).tolist()
                    selected_inventory_label = st.selectbox("샘플재고", options=inventory_labels, key="wms_inventory_pick")
                    selected_inventory_row = project_inventory[project_inventory.apply(_inventory_label, axis=1) == selected_inventory_label].iloc[0] if selected_inventory_label else None
                with adj_right:
                    if 'selected_inventory_row' not in locals() or selected_inventory_row is None:
                        st.info("좌측에서 조정할 샘플재고를 선택해 주세요.")
                    else:
                        st.caption(
                            f"{selected_inventory_row['sample_code']} | {selected_inventory_row['item_code']} | 현재 {selected_inventory_row['qty_on_hand']} / 가용 {selected_inventory_row['qty_available']}"
                        )
                        with st.form(f"wms_adjust_form_{int(selected_inventory_row['sample_id'])}"):
                            adj_c1, adj_c2 = st.columns(2)
                            with adj_c1:
                                qty_delta = st.number_input("조정수량(+/-)", step=1.0, value=0.0, key=f"wms_adjust_qty_{int(selected_inventory_row['sample_id'])}")
                            with adj_c2:
                                reason = st.selectbox("조정사유", options=["분실", "파손", "폐기", "실사차이", "기타"], key=f"wms_adjust_reason_{int(selected_inventory_row['sample_id'])}")
                            note = st.text_area("비고", height=88, key=f"wms_adjust_note_{int(selected_inventory_row['sample_id'])}")
                            (adjust_clicked,) = render_form_actions([("재고조정 저장", True)])
                            if adjust_clicked:
                                if qty_delta == 0:
                                    st.error("조정수량을 입력해 주세요.")
                                else:
                                    operations_service.adjust_sample_inventory(
                                        sample_id=int(selected_inventory_row["sample_id"]),
                                        project_id=int(selected_inventory_row["project_id"]),
                                        item_id=int(selected_inventory_row["item_id"]),
                                        qty_delta=float(qty_delta),
                                        reason=reason,
                                        note=note,
                                        current_user_name=current_user()["user_name"],
                                    )
                                    flash_success("재고조정을 저장했습니다.")
                                    st.rerun()
    if not moves_df.empty:
        history_df = moves_df.copy()
        history_df["진행흐름"] = history_df.apply(_wms_flow_status_text, axis=1)
        render_history_panel("이력 보기", history_df[["move_code", "source_order_code", "source_instruction_code", "sample_code", "item_code", "partner_name", "requested_qty", "dispatch_date", "expected_receipt_date", "receipt_date", "진행흐름"]])


OPERATIONS_PAGE_RENDERERS = {
    "금형 기본정보": render_molds_page,
    "금형 출고입고": render_mold_dispatch_page,
    "MB 의뢰": render_mb_requests_page,
    "MB 구매입고": render_mb_receipts_page,
    "WMS_공정품": render_wms_items_page,
}


def render_operations_page(menu: str) -> bool:
    renderer = OPERATIONS_PAGE_RENDERERS.get(menu)
    if renderer is None:
        return False
    if menu == "WMS_공정품":
        print("[WMS] before renderer dispatch")
    renderer()
    return True
