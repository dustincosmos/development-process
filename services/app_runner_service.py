from __future__ import annotations

import streamlit as st

from db.schema import init_db
from domain.constants import APP_GROUP_SETS, MENU_GROUPS
from services.shell_service import filter_accessible_menus, login_panel, render_flash_messages, render_header
from ui_apps.development_pages import render_development_page
from ui_apps.master_pages import render_master_page
from ui_apps.operations_pages import render_operations_page
from ui_apps.system_pages import render_system_page


FLOW_GUIDES = {
    "기본정보관리": "프로젝트 기본정보 -> 상품 -> 공정품 -> 제품구성 -> 제품도면/원화 -> 원재료/부재료",
    "실행관리": "금형 기본정보 -> 금형 출고입고 -> MB 의뢰 -> MB 구매입고 -> WMS_공정품",
    "개발진행": "공정품 요구 -> 조립품 요구 -> 사출 실험지시 -> 공정품 실험지시 -> 조립 실험지시 -> 실험 -> 품질검토 -> 최종검토",
    "현황조회": "대시보드 -> 구조조회",
    "시스템관리": "사용자관리 -> 역할관리",
}

def _append_nav_trace(stage: str, **payload) -> None:
    trace = st.session_state.setdefault("nav_trace_dev", [])
    trace.append({"stage": stage, **payload})
    del trace[:-30]
    print({"stage": stage, **payload})


def _ensure_login_for_app(page_config_key: str) -> bool:
    return login_panel()


def run_app(*, page_title: str, group_names: list[str], page_config_key: str) -> None:
    st.set_page_config(page_title=page_title, layout="wide")
    init_db()
    render_header()
    render_flash_messages()
    if not _ensure_login_for_app(page_config_key):
        return

    normalized_groups = APP_GROUP_SETS.get(page_config_key, group_names)
    default_group = group_names[0] if group_names else "개발진행"
    session_key = f"menu_group_{page_config_key}"
    menu_key = f"menu_select_{page_config_key}"
    pending_nav_key = f"pending_nav_{page_config_key}"
    entry_source_key = f"menu_entry_source_{page_config_key}"
    menu_visit_key = f"menu_visit_token_{page_config_key}"
    pending_nav = st.session_state.pop(pending_nav_key, None)
    entry_source = "direct"
    if isinstance(pending_nav, dict):
        target_group = str(pending_nav.get("group") or "")
        target_menu = str(pending_nav.get("menu") or "")
        if target_group in normalized_groups:
            print("[MENU] applying pending_nav", {"group": target_group, "menu": target_menu})
            st.session_state[session_key] = target_group
            if target_menu and target_menu in MENU_GROUPS.get(target_group, []):
                st.session_state[f"{menu_key}_{target_group}"] = target_menu
            entry_source = "pending_nav"
    _append_nav_trace(
        "app_runner_after_pending_nav",
        page_config_key=page_config_key,
        pending_nav=pending_nav,
        entry_source=entry_source,
        session_group=st.session_state.get(session_key),
        current_menu=st.session_state.get("current_menu"),
    )
    previous_group = st.session_state.get(session_key)
    previous_menu = st.session_state.get("current_menu")
    visible_group_map = {
        group_name: filter_accessible_menus(group_name, MENU_GROUPS.get(group_name, []))
        for group_name in normalized_groups
    }
    visible_groups = [group_name for group_name, visible_menus in visible_group_map.items() if visible_menus]
    if not visible_groups:
        st.error("현재 사용자에게 활성화된 메뉴가 없습니다. 관리자에게 문의해 주세요.")
        return
    default_group = visible_groups[0]
    current_group = st.session_state.get(session_key)
    if current_group not in visible_groups:
        st.session_state[session_key] = default_group
    menu_group = st.sidebar.radio("메뉴 그룹", visible_groups, key=session_key)
    visible_menus = visible_group_map.get(menu_group, [])
    if not visible_menus:
        st.error("선택한 메뉴 그룹에 활성화된 메뉴가 없습니다.")
        return
    current_menu_key = f"{menu_key}_{menu_group}"
    if st.session_state.get(current_menu_key) not in visible_menus:
        st.session_state[current_menu_key] = visible_menus[0]
    menu = st.sidebar.selectbox("메뉴", visible_menus, key=current_menu_key)
    print(
        "[MENU] selection",
        {
            "page_config_key": page_config_key,
            "menu_group": menu_group,
            "menu": menu,
            "entry_source": entry_source,
            "previous_group": previous_group,
            "previous_menu": previous_menu,
            "menu_visit_before": st.session_state.get(menu_visit_key, 0),
        },
    )
    if previous_group != menu_group or previous_menu != menu:
        st.session_state[menu_visit_key] = int(st.session_state.get(menu_visit_key, 0) or 0) + 1
        print("[MENU] menu_visit_token updated", st.session_state.get(menu_visit_key))
    st.session_state["current_menu"] = menu
    st.session_state[entry_source_key] = entry_source
    _append_nav_trace(
        "app_runner_after_menu_select",
        page_config_key=page_config_key,
        menu_group=menu_group,
        menu=menu,
        entry_source=entry_source,
        current_menu=st.session_state.get("current_menu"),
        session_group=st.session_state.get(session_key),
        menu_visit_token=st.session_state.get(menu_visit_key),
    )
    st.sidebar.markdown("**입력 순서 안내**")
    st.sidebar.caption(FLOW_GUIDES.get(menu_group, ""))

    if render_system_page(menu):
        return
    if render_master_page(menu):
        return
    if render_operations_page(menu):
        return
    if render_development_page(menu):
        return
    st.error(f"처리되지 않은 메뉴입니다: {menu}")
