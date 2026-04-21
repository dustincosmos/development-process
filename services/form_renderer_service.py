from __future__ import annotations

import streamlit as st


def render_configured_number_fields(
    *,
    fields: list[dict],
    values: dict,
    key_prefix: str,
    column_sizes: list[float] | None = None,
) -> dict:
    if not fields:
        return {}
    cols = st.columns(column_sizes or [1] * len(fields))
    rendered: dict = {}
    for col, field in zip(cols, fields):
        with col:
            if field.get("type") == "number":
                rendered[field["key"]] = st.number_input(
                    field["label"],
                    min_value=float(field.get("min_value", 0.0)),
                    step=float(field.get("step", 1.0)),
                    value=float(values.get(field["key"], 0.0) or 0.0),
                    key=f"{key_prefix}_{field['key']}",
                )
    return rendered
