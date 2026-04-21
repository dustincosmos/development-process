from __future__ import annotations

import base64
import json
from pathlib import Path

import streamlit as st

from db.development_flow_repository import get_current_product_drawing_for_item


def parse_json_text(raw: object) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def derive_requirement_checks(process_type: str, detail: dict) -> list[str]:
    checks: list[str] = []
    if process_type in ["사출", "후가공", "인쇄", "사상"] and detail.get("color_required"):
        checks.append("색상")
    if process_type == "사출" and detail.get("raw_material_experiment_required"):
        checks.append("원료실험")
    if process_type == "사출" and detail.get("product_drawing_change_required"):
        checks.append("제품도변경")
    if process_type == "사출" and detail.get("mold_dispatch_required"):
        checks.append("금형수정")
    if process_type == "사출" and any(detail.get(f"spec_location_{idx}") or detail.get(f"spec_value_{idx}") for idx in range(1, 5)):
        checks.append("특정위치규격")
    if process_type == "사출" and (
        detail.get("appearance_items")
        or any(detail.get(f"appearance_item_{idx}") or detail.get(f"appearance_position_{idx}") for idx in range(1, 5))
    ):
        checks.append("외관")
    if process_type in ("후가공", "사상") and detail.get("masking_position"):
        checks.append("마스킹위치")
    if process_type == "인쇄" and detail.get("film_revision_required"):
        checks.append("원화수정")
    if process_type == "인쇄" and (detail.get("print_position") or detail.get("print_tolerance_deg")):
        checks.append("위치")
    if process_type == "조립" and detail.get("assembly_function"):
        checks.append("기능")
    if process_type == "조립" and (detail.get("backing_spec") or detail.get("sub_material_other")):
        checks.append("부재료사양")
    if detail.get("other_request"):
        checks.append("기타")
    return checks


def render_product_drawing_reference(item_id: int) -> None:
    drawing = get_current_product_drawing_for_item(item_id)
    with st.expander("해당 제품도면 최종 수정본", expanded=False):
        if not drawing:
            st.caption("연결된 제품도면이 없습니다.")
            return
        if drawing.get("used_fallback"):
            st.warning("Item에 직접 연결된 도면이 없어 프로젝트의 최신 도면을 대신 표시합니다.")
        file_path = drawing.get("file_path")
        st.caption("도면 정보")
        info_cols = st.columns([1.1, 1.4, 0.8, 2.0])
        info_cols[0].caption("도면번호")
        info_cols[0].write(str(drawing["drawing_no"] or "-"))
        info_cols[1].caption("도면명")
        info_cols[1].write(str(drawing["drawing_name"] or "-"))
        info_cols[2].caption("리비전")
        info_cols[2].write(str(drawing["revision_no"] or "-"))
        info_cols[3].caption("메모")
        info_cols[3].write(str(drawing.get("file_note") or "-"))
        if file_path:
            st.caption(str(file_path))
        else:
            st.caption("첨부 파일은 없고 메모만 등록되어 있습니다.")
            return

        st.caption("도면 이미지")
        path = Path(file_path)
        if not path.exists():
            st.warning("첨부 파일 경로를 찾을 수 없습니다.")
            return
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            st.image(str(path), caption=path.name, use_column_width=True)
        elif suffix == ".pdf":
            pdf_bytes = path.read_bytes()
            pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
            st.download_button(
                "PDF 다운로드",
                data=pdf_bytes,
                file_name=path.name,
                mime="application/pdf",
                use_container_width=True,
                key=f"drawing_ref_pdf_download_{item_id}",
            )
            st.markdown(
                f"""
                <object
                    data="data:application/pdf;base64,{pdf_base64}#toolbar=0&navpanes=0"
                    type="application/pdf"
                    width="100%"
                    height="680"
                    style="border:1px solid #d9d9d9; border-radius:8px;"
                >
                    <p style="padding:12px; margin:0;">
                        브라우저에서 PDF 미리보기를 지원하지 않습니다.
                        위의 다운로드 버튼으로 파일을 열어 주세요.
                    </p>
                </object>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info("현재 파일은 이미지 미리보기를 지원하지 않습니다.")
            st.caption(path.name)
