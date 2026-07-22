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
import io
from typing import Any

import pandas as pd
import streamlit as st


from core.config import AppConfig, ColumnRule, load_config
from core.validation import validate_edits
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
    ss.setdefault("grid_ver", 0)         # bump to rotate the grid widget key
    ss.setdefault("undo_stack", [])      # instruction objects, see undo/redo below
    ss.setdefault("redo_stack", [])
    ss.setdefault("just_published", None)


def bump_grid() -> None:
    st.session_state.grid_ver += 1


def load_data(force: bool = False) -> pd.DataFrame:
    ss = st.session_state
    if ss.original_df is None or force:
        ss.original_df = get_storage_provider().load()
        ss.edits = {}
        ss.undo_stack, ss.redo_stack = [], []
        bump_grid()
    return ss.original_df


def rules_by_column() -> dict[str, ColumnRule]:
    return {r.name: r for r in get_config().columns}


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
        /* Edge/IE add a native password-reveal eye on top of Streamlit's
           own toggle — hide the native one */
        input::-ms-reveal, input::-ms-clear {{ display: none !important; }}

        /* kill the grid's hover toolbar (download / search / fullscreen) */
        [data-testid="stElementToolbar"] {{ display: none !important; }}

        /* the user-menu popover trigger looks like the avatar circle */
        div[data-testid="stPopover"] button[data-testid="stPopoverButton"] {{
            border-radius: 50%; width: 36px; height: 36px; min-height: 36px;
            padding: 0; background: {GREEN}; border: none; color: #fff;
            font-weight: 600; font-size: 12px;
        }}
        div[data-testid="stPopover"] button[data-testid="stPopoverButton"]:hover {{
            background: {GREEN_HOVER}; color: #fff;
        }}
        div[data-testid="stPopover"] button[data-testid="stPopoverButton"] svg {{
            display: none;   /* hide the caret so only initials show */
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
    c_title, c_search, c_review, c_avatar = st.columns([3.0, 2.6, 1.7, 0.55])
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
        with st.popover(user.initials, help=user.display_name):
            st.markdown(f"**{esc(user.display_name)}**", unsafe_allow_html=True)
            if st.button("Log out", width="stretch"):
                st.session_state.user = None
                st.session_state.original_df = None
                st.session_state.edits = {}
                st.session_state.undo_stack, st.session_state.redo_stack = [], []
                st.session_state.view = "editing"
                st.rerun()


# ------------------------------------------------------- grid helpers


def grid_column_config(rules: list[ColumnRule]) -> dict:
    cfg: dict = {
        ROW_ID: st.column_config.TextColumn("#", disabled=True, width="small")
    }
    for r in rules:
        cfg[r.name] = st.column_config.TextColumn(r.label, disabled=not r.editable)
    return cfg


def build_grid(page_df: pd.DataFrame, base_df: pd.DataFrame) -> pd.DataFrame:
    """Grid frame: '#' (original row number) first, data columns after."""
    grid = page_df.drop(columns=[ROW_ID], errors="ignore").astype(str)
    numbers = [str(row_number(base_df, rid)) for rid in page_df.index]
    grid.insert(0, ROW_ID, numbers)
    return grid


# ----------------------------------------------------- undo / redo core
#
# Every user action on a cell pushes an *instruction object* describing
# how to restore the cell's previous pending state, e.g.
#     {"row": 7, "col": "seats", "inst": "MODIFY", "value": "25"}
#     {"row": 2, "col": "email", "inst": "DELETE"}
# DELETE = remove the pending edit (cell back to its original value);
# MODIFY = set the pending edit to `value`. Undo pops an instruction and
# applies it verbatim; before applying, the inverse (the cell's current
# state) is pushed to the redo stack — and vice versa.


def _cell_instruction(row_id, column) -> dict:
    """Instruction that restores this cell's CURRENT pending state."""
    edits = st.session_state.edits
    if (row_id, column) in edits:
        return {"row": row_id, "col": column, "inst": "MODIFY",
                "value": edits[(row_id, column)]}
    return {"row": row_id, "col": column, "inst": "DELETE"}


def _apply_instruction(instr: dict) -> None:
    ss = st.session_state
    key = (instr["row"], instr["col"])
    if instr["inst"] == "DELETE":
        ss.edits.pop(key, None)
    else:
        value = str(instr["value"])
        if value == str(ss.original_df.at[key[0], key[1]]):
            ss.edits.pop(key, None)      # original value == no pending edit
        else:
            ss.edits[key] = value


def record_action(row_id, column) -> None:
    """Call BEFORE mutating a cell: snapshots its state for undo and
    invalidates the redo stack (a new action forks history)."""
    ss = st.session_state
    ss.undo_stack.append(_cell_instruction(row_id, column))
    ss.redo_stack.clear()


def undo() -> None:
    ss = st.session_state
    if not ss.undo_stack:
        return
    instr = ss.undo_stack.pop()
    ss.redo_stack.append(_cell_instruction(instr["row"], instr["col"]))
    _apply_instruction(instr)
    bump_grid()


def redo() -> None:
    ss = st.session_state
    if not ss.redo_stack:
        return
    instr = ss.redo_stack.pop()
    ss.undo_stack.append(_cell_instruction(instr["row"], instr["col"]))
    _apply_instruction(instr)
    bump_grid()


def harvest_editor(widget_key: str, row_ids: list) -> None:
    """Merge a data_editor's changes into the global edits map.

    Runs on every committed cell (Enter / click away). Each real change
    is recorded on the undo stack first. Typing the original value back
    clears the cell's edited state, per spec.
    """
    ss = st.session_state
    state = ss.get(widget_key, {})
    original = ss.original_df
    for pos, changes in state.get("edited_rows", {}).items():
        row_id = row_ids[int(pos)]
        for column, value in changes.items():
            if column not in original.columns:
                continue
            new = "" if value is None else str(value)
            current = ss.edits.get((row_id, column), str(original.at[row_id, column]))
            if new == str(current):
                continue                      # no actual change
            record_action(row_id, column)
            if new == str(original.at[row_id, column]):
                ss.edits.pop((row_id, column), None)   # revert -> clear
            else:
                ss.edits[(row_id, column)] = new
    bump_grid()


def revert_edit(row_id, column) -> None:
    """Revert one pending edit (review screen), undoably."""
    record_action(row_id, column)
    st.session_state.edits.pop((row_id, column), None)
    bump_grid()


def render_undo_redo() -> None:
    """Undo / redo buttons, top-left of the grid."""
    ss = st.session_state
    c1, c2, _ = st.columns([0.55, 0.55, 8])
    c1.button(
        "↶ Undo",
        width="stretch",
        disabled=not ss.undo_stack,
        help=f"{len(ss.undo_stack)} step{'s' if len(ss.undo_stack) != 1 else ''} to undo",
        on_click=undo,
    )
    c2.button(
        "↷ Redo",
        width="stretch",
        disabled=not ss.redo_stack,
        help=f"{len(ss.redo_stack)} step{'s' if len(ss.redo_stack) != 1 else ''} to redo",
        on_click=redo,
    )


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
        def _clear_search():
            # widget state may only be changed in a callback, which runs
            # before the search input is instantiated on the next run
            st.session_state.search = ""
            bump_grid()

        bar = st.columns([5.5, 1])
        bar[0].markdown(
            f'<div class="de-filterbar">Showing <b>{len(filtered):,}</b> of {total:,} rows '
            f'matching "<mark>{esc(term)}</mark>"</div>',
            unsafe_allow_html=True,
        )
        bar[1].button("Clear search", width="stretch", on_click=_clear_search)

    # undo / redo — top-left of the table
    render_undo_redo()

    # inline-editable grid of all (filtered) rows: type directly in a
    # cell, Enter or clicking away commits
    grid = build_grid(filtered, df)
    row_ids = list(filtered.index)
    widget_key = f"grid_{st.session_state.grid_ver}"
    st.data_editor(
        grid,
        key=widget_key,
        column_config=grid_column_config(cfg.columns),
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=560,   # initial paint only — the autosizer below corrects it
        on_change=harvest_editor,
        args=(widget_key, row_ids),
    )

    # Autosizer: measured in the browser, not guessed in CSS. Sets the
    # grid height to (viewport bottom − grid top − footer height), and
    # refits on window resize and on Streamlit re-renders (the grid key
    # rotates every commit, remounting the element). components.html JS
    # runs in a same-origin iframe, so it can reach the parent document.
    st.iframe(
        """<script>
        const P = window.parent, doc = P.document;
        function fit() {
          const grid = doc.querySelector('div[data-testid="stDataFrame"]');
          if (!grid) return;
          const top = grid.getBoundingClientRect().top;
          const h = Math.max(P.innerHeight - top - 16, 220);
          // Set a CSS variable only; the stylesheet applies it with
          // !important, which React's plain inline styles can't override.
          doc.documentElement.style.setProperty('--de-grid-h', h + 'px');
        }
        function fitTwice() { fit(); P.requestAnimationFrame(fit); }
        fitTwice();
        P.addEventListener('resize', fitTwice);
        if (P.__deFitObserver) P.__deFitObserver.disconnect();
        P.__deFitObserver = new P.MutationObserver(() => {
          P.clearTimeout(P.__deFitTimer);
          P.__deFitTimer = P.setTimeout(fitTwice, 80);
        });
        P.__deFitObserver.observe(doc.body, { childList: true, subtree: true });
        </script>""",
        height=1,
    )

    # editing view uses the full width; hide the sizer iframe's slot
    st.markdown(
        """<style>
        div.block-container { max-width: 100%; padding-bottom: 0.5rem; }
        div[data-testid="stElementContainer"]:has(> iframe) {
            height: 0; min-height: 0; margin: 0; padding: 0;
        }
        div[data-testid="stElementContainer"] > iframe { height: 0; border: 0; display: block; }

        /* Grid height from the autosizer's CSS variable. Stylesheet
           !important beats the React component's plain inline styles,
           so re-renders can't snap the container back to its initial
           height. Scoped by the grid widget's st-key class; applied to
           every wrapper down to the resizable so the outer container
           truly grows/shrinks and the footer reflows beneath it. */
        div[class*="st-key-grid_"],
        div[class*="st-key-grid_"] [data-testid="stFullScreenFrame"],
        div[class*="st-key-grid_"] [data-testid="stDataFrame"],
        div[class*="st-key-grid_"] [data-testid="stDataFrameResizable"] {
            height: var(--de-grid-h, 560px) !important;
            max-height: none !important;
            min-height: 0 !important;
        }
        </style>""",
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

    # inline-editable grid of ONLY the edited rows (new values shown;
    # type to adjust further — reverting to the original clears the edit
    # and drops the cell, or use ↩ in the change list below)
    page_df = df_with_edits(df.loc[edited_row_ids])
    grid = build_grid(page_df, df)
    widget_key = f"review_grid_{st.session_state.grid_ver}"
    st.data_editor(
        grid,
        key=widget_key,
        column_config=grid_column_config(cfg.columns),
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height="content",
        on_change=harvest_editor,
        args=(widget_key, edited_row_ids),
    )

    # change list: old → new with inline validation and per-change revert
    st.markdown(
        '<div class="de-note" style="margin-top:4px;">Pending changes (old → new)</div>',
        unsafe_allow_html=True,
    )
    for (row_id, column), new in sorted(
        edits.items(), key=lambda kv: (row_number(df, kv[0][0]), kv[0][1])
    ):
        rule = rules.get(column)
        label = rule.label if rule else column.upper()
        old = str(df.at[row_id, column])
        err = errors.get((row_id, column))
        err_html = f'<div class="de-diff-err">✗ {esc(err)}</div>' if err else ""
        c1, c2 = st.columns([8, 0.6])
        c1.markdown(
            f'<div style="font-size:13px;padding-top:4px;'
            + (f'background:{ERROR_FILL};border-left:3px solid {ERROR_RED};padding-left:8px;' if err else "")
            + f'">'
            f'<span style="color:{MUTED};">row {row_number(df, row_id)}</span> · '
            f'<b>{esc(label)}</b>: '
            f'<span class="de-diff-old">{esc(old)}</span> → '
            f'<span class="de-diff-new">{esc(new)}</span>{err_html}</div>',
            unsafe_allow_html=True,
        )
        c2.button(
            "↩",
            key=f"rev_review_{row_id}_{column}",
            help=f'Revert to "{old}"',
            on_click=revert_edit,
            args=(row_id, column),
        )


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
        st.session_state.undo_stack, st.session_state.redo_stack = [], []
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
