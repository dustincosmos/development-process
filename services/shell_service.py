from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from db.runtime import get_connection, hash_password
from domain.constants import PAGE_PERMISSIONS, ROLE_LABELS
from services.reference_data_service import get_role_menu_permissions, get_roles

FLASH_MESSAGES_KEY = "_flash_messages"
AUTH_QUERY_PARAM_KEY = "session_token"
AUTH_SESSION_TOKEN_KEY = "_auth_session_token"
AUTH_SESSION_HOURS = 12


def flash_message(message: str, level: str = "success") -> None:
    messages = st.session_state.get(FLASH_MESSAGES_KEY, [])
    messages.append({"level": level, "message": message})
    st.session_state[FLASH_MESSAGES_KEY] = messages


def flash_success(message: str) -> None:
    flash_message(message, "success")


def render_flash_messages() -> None:
    messages = st.session_state.pop(FLASH_MESSAGES_KEY, [])
    for entry in messages:
        level = entry.get("level", "success")
        message = entry.get("message", "")
        if level == "error":
            st.error(message)
        elif level == "warning":
            st.warning(message)
        elif level == "info":
            st.info(message)
        else:
            st.success(message)


def render_dataframe(df: pd.DataFrame) -> None:
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_section_title(title: str) -> None:
    st.caption(title)


def render_history_panel(title: str, df: pd.DataFrame) -> None:
    with st.expander(title, expanded=False):
        render_dataframe(df)


def render_form_actions(actions: list[tuple[str, bool]]) -> list[bool]:
    cols = st.columns(len(actions))
    results: list[bool] = []
    for col, (label, enabled) in zip(cols, actions):
        with col:
            results.append(st.form_submit_button(label, disabled=not enabled))
    return results


def render_page_actions(actions: list[tuple[str, str, bool]]) -> list[bool]:
    cols = st.columns(len(actions))
    results: list[bool] = []
    for col, (label, key, enabled) in zip(cols, actions):
        with col:
            results.append(st.button(label, key=key, disabled=not enabled, use_container_width=True))
    return results


def current_user() -> dict | None:
    return st.session_state.get("current_user")


def _current_role_codes() -> list[str]:
    user = current_user()
    if not user:
        return []
    role_codes = user.get("role_codes") or []
    if isinstance(role_codes, str):
        role_codes = [code for code in role_codes.split(",") if code]
    if not role_codes and user.get("role_code"):
        role_codes = [user["role_code"]]
    return [str(code).strip() for code in role_codes if str(code).strip()]


def role_label_map() -> dict[str, str]:
    roles_df = get_roles()
    if roles_df.empty:
        return dict(ROLE_LABELS)
    return {str(row["role_code"]): str(row["role_name"]) for _, row in roles_df.iterrows()}


def role_options(include_inactive: bool = False) -> list[tuple[str, str]]:
    roles_df = get_roles()
    if roles_df.empty:
        return list(dict(ROLE_LABELS).items())
    if not include_inactive and "is_active" in roles_df.columns:
        roles_df = roles_df[roles_df["is_active"] == 1].copy()
    return [(str(row["role_code"]), str(row["role_name"])) for _, row in roles_df.iterrows()]


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_query_param_token() -> str:
    value = st.query_params.get(AUTH_QUERY_PARAM_KEY, "")
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def _set_query_param_token(token: str | None) -> None:
    if token:
        st.query_params[AUTH_QUERY_PARAM_KEY] = token
    else:
        try:
            del st.query_params[AUTH_QUERY_PARAM_KEY]
        except Exception:
            pass


def _clear_local_auth_state() -> None:
    st.session_state.pop("current_user", None)
    st.session_state.pop(AUTH_SESSION_TOKEN_KEY, None)
    _set_query_param_token(None)


def _build_user_payload(conn, row) -> dict:
    role_rows = conn.execute(
        "SELECT role_code FROM user_roles WHERE user_id = ? ORDER BY role_code",
        (int(row["user_id"]),),
    ).fetchall()
    user = dict(row)
    user["role_codes"] = [role_row["role_code"] for role_row in role_rows] or ([user["role_code"]] if user.get("role_code") else [])
    return user


def _create_user_session(user_id: int) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_password(raw_token)
    now_text = _now_text()
    expires_at = (datetime.now() + timedelta(hours=AUTH_SESSION_HOURS)).isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (user_id, token_hash, issued_at, expires_at, last_seen_at, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (int(user_id), token_hash, now_text, expires_at, now_text),
        )
    return raw_token


def _revoke_user_session(raw_token: str | None) -> None:
    if not raw_token:
        return
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE user_sessions
            SET is_active = 0, revoked_at = ?, last_seen_at = ?
            WHERE token_hash = ? AND is_active = 1
            """,
            (_now_text(), _now_text(), hash_password(raw_token)),
        )


def _restore_user_from_token(raw_token: str | None) -> dict | None:
    token = str(raw_token or "").strip()
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                u.user_id,
                u.login_id,
                u.user_name,
                u.role_code,
                u.department,
                s.session_id,
                s.expires_at,
                s.is_active
            FROM user_sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ?
              AND s.is_active = 1
              AND u.is_active = 1
            ORDER BY s.session_id DESC
            LIMIT 1
            """,
            (hash_password(token),),
        ).fetchone()
        if row is None:
            return None
        expires_at = str(row["expires_at"] or "").strip()
        if not expires_at or expires_at <= _now_text():
            conn.execute(
                """
                UPDATE user_sessions
                SET is_active = 0, revoked_at = ?, last_seen_at = ?
                WHERE session_id = ?
                """,
                (_now_text(), _now_text(), int(row["session_id"])),
            )
            return None
        conn.execute(
            "UPDATE user_sessions SET last_seen_at = ? WHERE session_id = ?",
            (_now_text(), int(row["session_id"])),
        )
        return _build_user_payload(conn, row)


def _ensure_authenticated_user() -> dict | None:
    token = str(st.session_state.get(AUTH_SESSION_TOKEN_KEY) or _get_query_param_token() or "").strip()
    if not token:
        if st.session_state.get("current_user"):
            st.session_state.pop("current_user", None)
        return None
    user = _restore_user_from_token(token)
    if user is None:
        _clear_local_auth_state()
        return None
    st.session_state["current_user"] = user
    st.session_state[AUTH_SESSION_TOKEN_KEY] = token
    if _get_query_param_token() != token:
        _set_query_param_token(token)
    return user


def can_edit(page_name: str) -> bool:
    user = current_user()
    if not user:
        return False
    role_codes = user.get("role_codes") or []
    if isinstance(role_codes, str):
        role_codes = [code for code in role_codes.split(",") if code]
    if not role_codes and user.get("role_code"):
        role_codes = [user["role_code"]]
    return bool(set(role_codes) & PAGE_PERMISSIONS.get(page_name, set()))


def can_access_menu(menu_group: str, menu_name: str) -> bool:
    role_codes = _current_role_codes()
    if not role_codes:
        return False
    if "admin" in role_codes:
        return True
    role_permissions_df = get_role_menu_permissions()
    configured_roles = set()
    if not role_permissions_df.empty:
        configured_roles = {str(code).strip() for code in role_permissions_df["role_code"].dropna().tolist()}
    applicable_roles = [code for code in role_codes if code in configured_roles]
    if applicable_roles:
        matched = role_permissions_df[
            (role_permissions_df["role_code"].isin(applicable_roles))
            & (role_permissions_df["menu_group"].astype(str) == str(menu_group))
            & (role_permissions_df["menu_name"].astype(str) == str(menu_name))
            & (role_permissions_df["is_enabled"] == 1)
        ]
        return not matched.empty
    return True


def filter_accessible_menus(menu_group: str, menu_names: list[str]) -> list[str]:
    return [menu_name for menu_name in menu_names if can_access_menu(menu_group, menu_name)]


def show_permission_hint(page_name: str) -> None:
    user = current_user()
    if can_edit(page_name) and user:
        role_codes = user.get("role_codes") or []
        if isinstance(role_codes, str):
            role_codes = [code for code in role_codes.split(",") if code]
        if not role_codes and user.get("role_code"):
            role_codes = [user["role_code"]]
        labels = role_label_map()
        role_text = ", ".join(labels.get(code, code) for code in role_codes) if role_codes else "-"
        st.sidebar.caption(f"{page_name} · 입력/수정 권한: {role_text}")
    else:
        st.sidebar.caption(f"{page_name} · 조회만 가능합니다.")


def login_panel() -> bool:
    user = _ensure_authenticated_user()
    if user:
        role_codes = user.get("role_codes") or []
        if isinstance(role_codes, str):
            role_codes = [code for code in role_codes.split(",") if code]
        if not role_codes and user.get("role_code"):
            role_codes = [user["role_code"]]
        labels = role_label_map()
        role_text = ", ".join(labels.get(code, code) for code in role_codes) if role_codes else "-"
        st.sidebar.success(f"{user['user_name']} / {role_text}")
        if st.sidebar.button("로그아웃"):
            _revoke_user_session(st.session_state.get(AUTH_SESSION_TOKEN_KEY) or _get_query_param_token())
            _clear_local_auth_state()
            st.rerun()
        return True

    st.sidebar.subheader("로그인")
    with st.sidebar.form("login_form"):
        login_id = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
        if submitted:
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT user_id, login_id, user_name, role_code, department
                    FROM users
                    WHERE login_id = ? AND password_hash = ? AND is_active = 1
                    """,
                    (login_id, hash_password(password)),
                ).fetchone()
            if row:
                with get_connection() as conn:
                    user = _build_user_payload(conn, row)
                raw_token = _create_user_session(int(user["user_id"]))
                st.session_state["current_user"] = user
                st.session_state[AUTH_SESSION_TOKEN_KEY] = raw_token
                _set_query_param_token(raw_token)
                st.rerun()
            st.sidebar.error("아이디 또는 비밀번호를 확인해 주세요.")
    st.sidebar.caption("기본 관리자 계정: admin / admin1234")
    return False


def render_header() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.6rem;
        }
        h3 {
            margin-top: 0;
            margin-bottom: 0.7rem;
            padding-top: 0.15rem;
            line-height: 1.3;
        }
        div[data-testid="stCaptionContainer"] p {
            font-size: 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("**플라스틱 포장재 개발관리**")
