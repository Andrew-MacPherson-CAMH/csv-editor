"""CSV Data Editor — Streamlit implementation of the IYS wireframes.

Views: login (1a) → editing grid with live search (1b/2a) → review with
diffs + validation (1c/1d) → publish confirmation dialog (1e).

Auth and storage are pluggable providers selected in config.yaml.

Grid approach: a styled st.dataframe with single-cell selection.
Clicking a cell opens an inline editor beneath the grid (Enter commits).
This keeps the wireframes' per-cell visual states (edited tint, invalid
outline, search-match highlight), which Streamlit's data_editor cannot
render on editable columns.
"""
from __future__ import annotations

import html
import os
import io
from typing import Any, Optional

import pandas as pd
import streamlit as st

from core.config import AppConfig, ColumnRule, load_config
from core.validation import validate_cell, validate_edits
from providers.auth import AuthError, create_auth_provider
from providers.storage import ROW_ID, StorageError, create_storage_provider

# ---------------------------------------------------------------- tokens
GREEN = "rgb(3,149,121)"
GREEN_HOVER = "rgb(2,119,97)"
EDIT_TINT = "rgb(230,245,241)"
ERROR_RED = "rgb(231,0,11)"
ERROR_FILL = "rgb(255,247,237)"
MATCH_YELLOW = "#fff3a6"
FILTER_BLUE = "#eef4fb"
MUTED = "rgb(161,161,161)"
SECONDARY = "rgb(82,82,82)"

st.set_page_config(page_title="Data Editor", page_icon="🗂️", layout="wide")

# AppTest cannot serialize selection-enabled dataframes; tests set this env var.
_SELECT_MODE = "ignore" if os.environ.get("CSV_EDITOR_TESTMODE") else "rerun"

# ------------------------------------------------------------- providers


@st.cache_resource
def get_config() -> AppConfig:
    return load_config()


@st.cache_resource
def get_auth_provider():
    cfg = get_config()
    return create_auth_provider(cfg.auth_provider_name, cfg.auth_settings())


@st.cache_resource
def get_storage_provider():
    cfg = get_config()
    return create_storage_provider(cfg.storage_provider_name, cfg.storage_settings())


# ----------------------------------------------------------------- state


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("user", None)
    ss.setdefault("original_df", None)   # DataFrame indexed by ROW_ID
    ss.setdefault("edits", {})           # {(row_id, column): new_value}
    ss.setdefault("view", "editing")     # editing | review
    ss.setdefault("grid_ver", 0)         # bump to reset grid selection state
    ss.setdefault("just_published", None)


def bump_grid() -> None:
    st.session_state.grid_ver += 1


def load_data(force: bool = False) -> pd.DataFrame:
    ss = st.session_state
    if ss.original_df is None or force:
        ss.original_df = get_storage_provider().load()
        ss.edits = {}
        bump_grid()
    return ss.original_df


def rules_by_column() -> dict[str, ColumnRule]:
    return {r.name: r for r in get_config().columns}


def current_value(row_id: Any, column: str) -> str:
    edits = st.session_state.edits
    if (row_id, column) in edits:
        return str(edits[(row_id, column)])
    return str(st.session_state.original_df.at[row_id, column])


def df_with_edits(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for (row_id, column), value in st.session_state.edits.items():
        if row_id in out.index and column in out.columns:
            out.at[row_id, column] = "" if value is None else str(value)
    return out


def set_edit(row_id: Any, column: str, new_value: str) -> None:
    """Commit a cell value; reverting to the original clears the edit."""
    original = str(st.session_state.original_df.at[row_id, column])
    new = "" if new_value is None else str(new_value)
    if new == original:
        st.session_state.edits.pop((row_id, column), None)
    else:
        st.session_state.edits[(row_id, column)] = new


def row_number(df: pd.DataFrame, row_id: Any) -> int:
    return int(df.index.get_indexer([row_id])[0]) + 1


def esc(text: Any) -> str:
    return html.escape("" if text is None else str(text))


# ------------------------------------------------------------------- css


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Open+Sans:ital,wght@0,400;0,600;1,400&display=swap');
        html, body, [class*="css"], .stApp {{ font-family: 'Open Sans', Arial, sans-serif; }}
        .stApp {{ background: rgb(241,239,234); }}
        /* clear Streamlit's fixed header so the toolbar isn't covered */
        .block-container {{ padding-top: 4.5rem; max-width: 1200px; }}

        .de-card {{
            background: #fff; border: 1px solid rgb(229,229,229); border-radius: 12px;
            box-shadow: 0 7px 8px -4px rgba(0,0,0,.1), 0 12px 17px 2px rgba(0,0,0,.08),
                        0 5px 22px 4px rgba(0,0,0,.06);
            padding: 14px 18px;
        }}
        .de-title {{ font-size: 17px; font-weight: 600; }}
        .de-fileinfo {{ font-size: 12px; color: {SECONDARY}; }}
        .de-note {{ font-style: italic; font-size: 12px; color: {SECONDARY}; }}

        .de-filterbar {{
            background: {FILTER_BLUE}; border: 1px solid #dbe7f6; border-radius: 6px;
            padding: 6px 12px; font-size: 13px; margin: 2px 0 8px;
        }}
        .de-filterbar mark {{ background: {MATCH_YELLOW}; padding: 0 2px; }}

        .de-legend {{ font-size: 12px; color: {SECONDARY}; }}
        .de-swatch {{
            display:inline-block; width:12px; height:12px; border:1px solid rgb(212,212,212);
            border-radius:3px; vertical-align:-2px; margin-right:5px;
        }}

        .de-diff-old {{ text-decoration: line-through; color: {MUTED}; font-size: 12px; }}
        .de-diff-new {{ font-weight: 600; }}
        .de-diff-err {{ color: {ERROR_RED}; font-size: 11px; }}
        .de-summary-err {{ color: {ERROR_RED}; font-weight: 600; }}

        .de-avatar {{
            display:inline-flex; align-items:center; justify-content:center;
            width:32px; height:32px; border-radius:50%; background:{GREEN};
            color:#fff; font-size:12px; font-weight:600; margin-top:2px;
        }}

        div.stButton > button[kind="primary"] {{
            background: {GREEN}; border-color: {GREEN}; color: #fff;
            border-radius: 6px; font-weight: 600;
        }}
        div.stButton > button[kind="primary"]:hover {{
            background: {GREEN_HOVER}; border-color: {GREEN_HOVER};
        }}
        div.stButton > button[kind="primary"]:disabled {{
            background: #eee; border: 1px dashed rgb(212,212,212); color: {MUTED};
        }}
        div.stButton > button {{ border-radius: 6px; }}
        /* Streamlit text inputs: the visible border lives on the baseweb
           wrapper. Styling the inner <input> draws a second box on focus,
           so target the wrapper's :focus-within instead. */
        div[data-testid="stTextInput"] div[data-baseweb="input"] {{ border-radius: 6px; }}
        div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {{
            border-color: {GREEN}; box-shadow: 0 0 0 1px {GREEN};
        }}
        div[data-testid="stTextInput"] input {{
            border: none !important; box-shadow: none !important; outline: none !important;
        }}
        div[data-testid="stForm"] {{
            border: 2px solid {GREEN}; border-radius: 8px; background: #fff;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------- login (1a)


def render_login() -> None:
    cfg = get_config()
    _, mid, _ = st.columns([1, 1.05, 1])
    with mid:
        st.markdown(
            f"""
            <div style="max-width:420px;margin:48px auto 12px;text-align:center;">
              <div style="width:56px;height:56px;border-radius:50%;background:{GREEN};margin:0 auto 14px;
                          display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;">DE</div>
              <div style="font-size:22px;font-weight:600;">{esc(cfg.title)}</div>
              <div class="de-note">{esc(cfg.subtitle)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("login"):
            username = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button(
                "Log in", type="primary", width="stretch"
            )
            st.markdown(
                f'<div style="text-align:center;font-size:13px;"><a href="#" '
                f'style="color:{GREEN};">Forgot password?</a></div>',
                unsafe_allow_html=True,
            )

        if submitted:
            try:
                user = get_auth_provider().authenticate(username.strip(), password)
            except AuthError as exc:
                st.error(f"Sign-in is unavailable: {exc}")
                return
            if user is None:
                st.error("Incorrect email or password.")
            else:
                st.session_state.user = user
                st.rerun()


# --------------------------------------------------------------- toolbar


def render_toolbar(subtitle: str) -> None:
    cfg = get_config()
    user = st.session_state.user
    c_title, c_search, c_review, c_avatar, c_out = st.columns(
        [3.0, 2.6, 1.7, 0.4, 0.5]
    )
    with c_title:
        st.markdown(
            f'<div style="padding-top:6px;"><span class="de-title">{esc(cfg.title)}</span>'
            f'&nbsp;&nbsp;<span class="de-fileinfo">{esc(subtitle)}</span></div>',
            unsafe_allow_html=True,
        )
    with c_search:
        st.text_input(
            "Search",
            key="search",
            placeholder="🔍  Search all columns…",
            label_visibility="collapsed",
            on_change=bump_grid,
        )
    with c_review:
        n_edits = len(st.session_state.edits)
        label = f"Review changes ({n_edits})" if n_edits else "Review changes"
        if st.button(label, width="stretch", disabled=n_edits == 0,
                     help=None if n_edits else "Edit a cell to enable review"):
            st.session_state.view = "review"
            bump_grid()
            st.rerun()
    with c_avatar:
        st.markdown(
            f'<div class="de-avatar" title="{esc(user.display_name)}">{esc(user.initials)}</div>',
            unsafe_allow_html=True,
        )
    with c_out:
        if st.button("⎋", help=f"Log out {user.display_name}"):
            st.session_state.user = None
            st.session_state.original_df = None
            st.session_state.edits = {}
            st.session_state.view = "editing"
            st.rerun()


# ------------------------------------------------------- grid helpers


def grid_column_config(rules: list[ColumnRule]) -> dict:
    cfg: dict = {ROW_ID: st.column_config.Column("#", width="small")}
    for r in rules:
        cfg[r.name] = st.column_config.Column(r.label)
    return cfg


def build_grid(page_df: pd.DataFrame, base_df: pd.DataFrame) -> pd.DataFrame:
    """Grid frame: '#' (original row number) first, data columns after."""
    grid = page_df.drop(columns=[ROW_ID], errors="ignore").astype(str)
    numbers = [str(row_number(base_df, rid)) for rid in page_df.index]
    grid.insert(0, ROW_ID, numbers)
    return grid


def style_grid(
    grid: pd.DataFrame,
    errors: dict,
    term: str = "",
):
    """Pandas Styler implementing the wireframe cell states.

    Precedence: invalid (1d) > edited (1b) > search match (2a).
    """
    edits = st.session_state.edits
    t = term.lower()

    def per_row(row):
        styles = []
        for col in grid.columns:
            if col == ROW_ID:
                styles.append(f"color:{MUTED};")
                continue
            key = (row.name, col)
            if key in errors:
                styles.append(
                    f"background-color:{ERROR_FILL};"
                    f"box-shadow: inset 0 0 0 2px {ERROR_RED}; font-weight:600;"
                )
            elif key in edits:
                styles.append(f"background-color:{EDIT_TINT};")
            elif t and t in str(row[col]).lower():
                styles.append(f"background-color:{MATCH_YELLOW};")
            else:
                styles.append("")
        return styles

    return grid.style.apply(per_row, axis=1)


def selected_cell(event, page_df: pd.DataFrame) -> Optional[tuple[Any, str]]:
    """Map a grid selection event to (row_id, column_name), if any."""
    try:
        cells = event.selection.cells
    except (AttributeError, KeyError):
        return None
    if not cells:
        return None
    pos, column = cells[0]
    if column == ROW_ID or column not in st.session_state.original_df.columns:
        return None
    return page_df.index[int(pos)], column


def render_cell_editor(row_id: Any, column: str) -> None:
    """Inline editor for the selected cell (active-cell state, 1b)."""
    df = st.session_state.original_df
    rules = rules_by_column()
    rule = rules.get(column)
    label = rule.label if rule else column.upper()
    original = str(df.at[row_id, column])
    value_now = current_value(row_id, column)
    is_edited = (row_id, column) in st.session_state.edits

    hint = ""
    if rule:
        bits = []
        if rule.type != "string":
            bits.append(rule.type)
        if rule.min is not None or rule.max is not None:
            bits.append(f"{rule.min if rule.min is not None else ''}–{rule.max if rule.max is not None else ''}")
        if rule.max_length:
            bits.append(f"max {rule.max_length} chars")
        if rule.regex:
            bits.append("format-checked")
        if bits:
            hint = " · ".join(str(b) for b in bits)

    with st.form(f"cell_{row_id}_{column}", border=True):
        top = f"Editing **{label}** · row {row_number(df, row_id)}"
        if is_edited:
            top += f' &nbsp; <span class="de-diff-old">{esc(original)}</span>'
        st.markdown(top, unsafe_allow_html=True)
        new_value = st.text_input(
            "Value",
            value=value_now,
            label_visibility="collapsed",
            help=hint or None,
        )
        c1, c2, c3 = st.columns([1.2, 1.6, 4])
        commit = c1.form_submit_button("Commit", type="primary", width="stretch")
        revert = c2.form_submit_button(
            "Revert to original", width="stretch", disabled=not is_edited
        )
        if hint:
            c3.markdown(f'<div class="de-note" style="padding-top:8px;">{esc(hint)}</div>',
                        unsafe_allow_html=True)

    if commit:
        set_edit(row_id, column, new_value)
        if rule:
            err = validate_cell(new_value, rule)
            if err and (row_id, column) in st.session_state.edits:
                st.session_state.just_published = None
                st.warning(f"Saved as a pending edit, but: ✗ {err}. "
                           "Publishing is blocked until it's fixed.")
        bump_grid()
        st.rerun()
    if revert:
        st.session_state.edits.pop((row_id, column), None)
        bump_grid()
        st.rerun()


def filter_rows(display_df: pd.DataFrame, term: str) -> pd.DataFrame:
    if not term:
        return display_df
    t = term.lower()
    mask = (
        display_df.drop(columns=[ROW_ID], errors="ignore")
        .apply(lambda col: col.astype(str).str.lower().str.contains(t, regex=False))
        .any(axis=1)
    )
    return display_df[mask]


# --------------------------------------------------------- editing (1b/2a)


def render_editing() -> None:
    cfg = get_config()
    df = load_data()
    total = len(df)

    render_toolbar(f"{cfg.dataset_display_name} · {total:,} rows")

    if st.session_state.just_published:
        st.success(st.session_state.just_published)
        st.session_state.just_published = None

    display = df_with_edits(df)
    term = (st.session_state.get("search") or "").strip()
    filtered = filter_rows(display, term)

    # 2a — filter status bar (edits on hidden rows are kept; badge unchanged)
    if term:
        bar = st.columns([5.5, 1])
        bar[0].markdown(
            f'<div class="de-filterbar">Showing <b>{len(filtered):,}</b> of {total:,} rows '
            f'matching "<mark>{esc(term)}</mark>"</div>',
            unsafe_allow_html=True,
        )
        if bar[1].button("Clear search", width="stretch"):
            st.session_state.search = ""
            bump_grid()
            st.rerun()

    # Inline cell editor renders ABOVE the grid (the grid fills the rest
    # of the viewport, so anything below it would be off-screen).
    editor_slot = st.container()

    # all rows in one grid that fills the remaining viewport height and
    # the full container width; it scrolls internally in both directions
    grid = build_grid(filtered, df)
    event = st.dataframe(
        style_grid(grid, errors={}, term=term),
        key=f"grid_{st.session_state.grid_ver}",
        column_config=grid_column_config(cfg.columns),
        hide_index=True,
        width="stretch",
        height="stretch",
        on_select=_SELECT_MODE,
        selection_mode="single-cell",
    )

    sel = selected_cell(event, filtered)
    if sel:
        with editor_slot:
            render_cell_editor(*sel)

    # Proper flex layout instead of viewport math: the page column is
    # exactly 100vh, the grid's element container is the only flexible
    # child (flex: 1), so the grid genuinely fills all remaining space
    # and the footer sits in normal flow at the bottom — no overlap or
    # floating when the window/devtools resize. Injected here so it only
    # applies to the editing view. Requires the grid's `key`, which
    # Streamlit exposes as a `st-key-…` class on its element container.
    st.markdown(
        """<style>
        div.block-container {
            height: 100vh;
            max-width: 100%;
            display: flex; flex-direction: column;
            overflow: hidden;
            padding-bottom: 0.75rem;
        }
        /* every wrapper between the page column and the grid must be
           allowed to flex and to shrink below its content size */
        div.block-container > div,
        div.block-container div[data-testid="stVerticalBlock"] {
            flex: 1 1 auto; min-height: 0;
            display: flex; flex-direction: column;
        }
        /* non-grid siblings (toolbar, filter bar, editor, footer) keep
           their natural height */
        div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"],
        div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"],
        div[data-testid="stVerticalBlock"] > div[data-testid="stForm"],
        div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
            flex: 0 0 auto;
        }
        /* the grid is the one flexible child */
        div[data-testid="stVerticalBlock"] > div[class*="st-key-grid_"] {
            flex: 1 1 auto !important; min-height: 180px;
            display: flex; flex-direction: column;
        }
        div[class*="st-key-grid_"] div[data-testid="stDataFrame"] {
            height: 100% !important;
        }
        </style>""",
        unsafe_allow_html=True,
    )

    # footer / status bar
    n_edits = len(st.session_state.edits)
    f1, f2 = st.columns([4.4, 1.8])
    with f1:
        st.markdown(
            f'<div class="de-legend">'
            f'<span class="de-swatch" style="background:{EDIT_TINT};"></span>edited cell'
            + (f' &nbsp; <span class="de-swatch" style="background:{MATCH_YELLOW};"></span>search match' if term else "")
            + f' &nbsp;·&nbsp; {n_edits} pending edit{"s" if n_edits != 1 else ""}'
            f' &nbsp;·&nbsp; click a cell to edit</div>',
            unsafe_allow_html=True,
        )
    with f2:
        st.markdown(
            f'<div class="de-legend" style="text-align:right;padding-top:2px;">'
            f'{len(filtered):,} of {total:,} rows{" (filtered)" if term else ""}</div>',
            unsafe_allow_html=True,
        )


# ------------------------------------------------------ review (1c/1d/1e)


def render_review() -> None:
    cfg = get_config()
    df = load_data()
    edits = st.session_state.edits
    rules = rules_by_column()
    errors = validate_edits(edits, rules)

    edited_row_ids = [rid for rid in df.index if any(k[0] == rid for k in edits)]
    n_rows, n_cells = len(edited_row_ids), len(edits)

    c_back, c_title, c_publish = st.columns([1.5, 4, 1.7])
    with c_back:
        if st.button("← Back to editing", width="stretch"):
            st.session_state.view = "editing"
            bump_grid()
            st.rerun()
    with c_title:
        if errors:
            summary = (
                f'<span class="de-summary-err">{len(errors)} '
                f'cell{"s" if len(errors) != 1 else ""} invalid</span>'
            )
        else:
            summary = (
                f'{n_rows} row{"s" if n_rows != 1 else ""} · '
                f'{n_cells} cell{"s" if n_cells != 1 else ""} changed'
            )
        st.markdown(
            f'<div style="padding-top:6px;"><span class="de-title">Review changes</span>'
            f'&nbsp;&nbsp;<span class="de-fileinfo">{summary}</span></div>',
            unsafe_allow_html=True,
        )
    with c_publish:
        if st.button(
            "Publish changes",
            type="primary",
            width="stretch",
            disabled=bool(errors) or n_cells == 0,
            help="Fix invalid cells to enable publishing" if errors else None,
        ):
            publish_dialog(n_rows, n_cells)

    if n_cells == 0:
        st.markdown('<div class="de-note">No pending changes — go back and edit some cells.</div>',
                    unsafe_allow_html=True)
        return

    # grid of ONLY edited rows; changed cells show `old → new` (+ error)
    page_df = df_with_edits(df.loc[edited_row_ids])
    grid = build_grid(page_df, df)
    for (row_id, column), new in edits.items():
        old = str(df.at[row_id, column])
        text = f"{old} → {new}"
        err = errors.get((row_id, column))
        if err:
            text += f"   ✗ {err}"
        grid.at[row_id, column] = text

    event = st.dataframe(
        style_grid(grid, errors=errors),
        key=f"review_grid_{st.session_state.grid_ver}",
        column_config=grid_column_config(cfg.columns),
        hide_index=True,
        width="stretch",
        height="content",
        on_select=_SELECT_MODE,
        selection_mode="single-cell",
    )
    st.markdown(
        f'<div class="de-legend" style="margin-top:-6px;">'
        f'<span class="de-swatch" style="background:{EDIT_TINT};"></span>changed (old → new) &nbsp; '
        f'<span class="de-swatch" style="background:{ERROR_FILL};border-color:{ERROR_RED};"></span>invalid '
        f'&nbsp;·&nbsp; cells are still editable — click one</div>',
        unsafe_allow_html=True,
    )

    sel = selected_cell(event, page_df)
    if sel:
        render_cell_editor(*sel)


@st.dialog("Publish these changes?")
def publish_dialog(n_rows: int, n_cells: int) -> None:
    cfg = get_config()
    st.markdown(
        f"You're about to update **{n_cells} cell{'s' if n_cells != 1 else ''}** across "
        f"**{n_rows} row{'s' if n_rows != 1 else ''}** in **{cfg.dataset_display_name}**. "
        "This can't be undone."
    )
    backup = io.StringIO()
    st.session_state.original_df.drop(columns=[ROW_ID], errors="ignore").to_csv(
        backup, index=False
    )
    st.download_button(
        "⬇ Download a backup copy first",
        data=backup.getvalue(),
        file_name=f"backup_{cfg.dataset_display_name.replace(' ', '_')}",
        mime="text/csv",
    )
    c1, c2 = st.columns(2)
    if c1.button("Cancel", width="stretch"):
        st.rerun()
    if c2.button("Yes, publish", type="primary", width="stretch"):
        try:
            get_storage_provider().apply_edits(
                st.session_state.original_df, dict(st.session_state.edits)
            )
        except StorageError as exc:
            st.error(f"Publish failed — no changes were saved: {exc}")
            return
        st.session_state.original_df = df_with_edits(st.session_state.original_df)
        st.session_state.edits = {}
        st.session_state.view = "editing"
        st.session_state.just_published = (
            f"Published {n_cells} cell{'s' if n_cells != 1 else ''} across "
            f"{n_rows} row{'s' if n_rows != 1 else ''}."
        )
        bump_grid()
        st.rerun()


# ------------------------------------------------------------------ main


def main() -> None:
    init_state()
    inject_css()

    if st.session_state.user is None:
        render_login()
        return

    try:
        if st.session_state.view == "review":
            render_review()
        else:
            render_editing()
    except StorageError as exc:
        st.error(f"Storage error: {exc}")
        if st.button("Retry"):
            st.session_state.original_df = None
            st.rerun()


if __name__ == "__main__":
    main()
