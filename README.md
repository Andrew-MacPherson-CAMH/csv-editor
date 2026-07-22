# CSV Data Editor (Streamlit)

Streamlit implementation of the IYS "Data Editor" wireframes: authenticated users edit cells of a tabular dataset in a grid, filter rows with live search, review pending changes as old → new diffs with per-cell validation, and publish behind a confirmation dialog.

Auth and storage are **pluggable providers selected in `config.yaml`** — swap Google Cloud auth or BigQuery for something else without touching application code.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Log in with `admin` / `admin` (the dev `mock` auth provider — see `config.yaml`). The default storage provider is `local_csv` backed by `sample_data/customers.csv` (120 sample rows), so the app runs end-to-end with no cloud setup.

## Screens → wireframes

| Wireframe | Where |
|---|---|
| 1a Login | centered card, logo mark, email/password, "Forgot password?" |
| 1b Editing | toolbar (title, file info, search, "Review changes (n)" badge, avatar), grid, footer legend + `rows x–y of n` pagination |
| 2a Search | as-you-type filtering, blue filter bar (`Showing x of n rows matching "…"`), Clear search, yellow match highlighting; **edits on hidden rows are kept and the badge count is unchanged** |
| 1c Review | only edited rows, green-tinted changed cells showing `old → new`, cells still editable, summary "n rows · m cells changed", plus a diff panel with struck-through old values |
| 1d Validation | invalid cells get the orange fill + red outline + inline `✗ …` message; summary turns red ("k cells invalid"); Publish disabled (grey, dashed border) |
| 1e Publish | modal dialog with dynamic cell/row counts, "download a backup copy first", Cancel / "Yes, publish" |

### One deliberate adaptation
Streamlit's `st.data_editor` cannot style individual editable cells, but the wireframes lean heavily on per-cell visual states (edited tint, invalid outline, match highlight). So the grid is a **styled `st.dataframe` with single-cell selection**: clicking a cell opens an inline editor directly beneath the grid (Enter commits; "Revert to original" clears the edited state, per spec). This preserves every visual state at the cost of a one-click hop instead of type-in-place. If type-in-place matters more than the visual states, swap the grid for `st.data_editor` — the edit-tracking model (`edits` keyed by `(row_id, column)`) supports either front end.

## Architecture

```
app.py                      Streamlit UI (login / editing / review / publish)
config.yaml                 provider selection + column & validation spec
core/
  config.py                 config loader, ColumnRule dataclass
  validation.py             type / length / regex validation engine
providers/
  auth/
    base.py                 AuthProvider ABC + User
    mock.py                 dev users from config
    gcloud_identity.py      Google Cloud Identity Platform (email+password REST)
    __init__.py             registry + factory (lazy imports)
  storage/
    base.py                 StorageProvider ABC (load / apply_edits contract)
    local_csv.py            local file, atomic writes
    bigquery.py             BigQuery, atomic MERGE publish
    __init__.py             registry + factory (lazy imports)
tests/test_app.py           end-to-end view tests (Streamlit AppTest)
```

### State model (matches the handoff spec)
- `user` — session auth
- `original_df` — dataset from the storage provider, indexed by a stable `_row_id`
- `edits` — `{(row_id, column): new_value}`; reverting a cell to its original value removes the entry
- `search` → derived filtered row list (search runs over data **with edits applied**)
- `validationErrors` — derived from `edits` + column rules on every rerun
- `view` — `editing | review`; publish dialog via `st.dialog`
- Publish → provider `apply_edits()` → merge into `original_df`, clear `edits`

## Swapping providers (requirements A & B)

Everything is driven by two lines in `config.yaml`:

```yaml
auth:
  provider: gcloud_identity   # or: mock
storage:
  provider: bigquery          # or: local_csv
```

### Auth: Google Cloud (current)
`gcloud_identity` calls the Identity Platform `signInWithPassword` REST endpoint. Set the API key via env var:

```bash
export GCP_IDENTITY_API_KEY="AIza..."
```

Bad credentials return a normal "Incorrect email or password" message; infrastructure problems (missing key, network) surface separately as `AuthError`.

### Storage: BigQuery (current)
```yaml
storage:
  provider: bigquery
  bigquery:
    project: my-gcp-project
    dataset: my_dataset
    table: customers
    id_column: id        # REQUIRED: stable unique key
```

```bash
pip install google-cloud-bigquery db-dtypes
gcloud auth application-default login   # or GOOGLE_APPLICATION_CREDENTIALS
```

Publishing runs a **single parameterized `MERGE`**, so all cells land atomically or not at all. Note: edited values are bound as STRING parameters; when the real column spec arrives, add per-column `CAST`s in `bigquery.py` for non-string BigQuery column types (the spot is marked by the `SET` clause builder).

### Adding a new provider
Implement the ABC, register it, name it in config — no other changes:

```python
# providers/storage/postgres.py
class PostgresStorageProvider(StorageProvider):
    name = "postgres"
    def load(self) -> pd.DataFrame: ...
    def apply_edits(self, df, edits) -> None: ...

# providers/storage/__init__.py
register_storage_provider("postgres",
    lambda: _import("providers.storage.postgres", "PostgresStorageProvider"))
```

The contract is documented in `providers/storage/base.py`: `load()` must return a DataFrame indexed by a stable unique row id; `apply_edits()` receives already-validated `{(row_id, column): value}` and should persist atomically where the backend allows. Same pattern for auth in `providers/auth/`.

## Columns & validation (requirement C)

Column definitions and validation rules are **pure config** — when the real spec arrives, edit `dataset.columns` in `config.yaml` only:

```yaml
- name: seats
  label: SEATS
  type: integer      # string | number | integer | date
  min: 1
  max: 999
  align: right
- name: email
  regex: "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"
  regex_hint: "not a valid email (regex)"
```

Supported per column: `type`, `required`, `min`/`max`, `max_length`, `regex` (+ `regex_hint` for the wireframe-style error message), `editable: false` for read-only columns. Error strings match the wireframe tone ("✗ must be a whole number, 1–999").

## Tests

```bash
CSV_EDITOR_TESTMODE=1 python -m pytest tests/ -q
```

Covers: login success/failure, review summary + publish gating on validation errors, search filtering keeping hidden-row edits and the badge count, and the editing view render. (`CSV_EDITOR_TESTMODE` disables dataframe cell-selection, which Streamlit's test harness can't serialize; it has no other effect.)

## Notes & known trade-offs
- Values are edited as strings and normalized by the storage provider on publish; typed BigQuery columns need the `CAST` noted above once the real schema lands.
- Search-match highlighting tints the whole matching cell (Streamlit can't style substrings inside grid cells).
- Concurrent editors aren't coordinated: last publish wins per cell. Add optimistic locking in a provider if needed.
- The "Forgot password?" link is a placeholder — wire it to the auth provider's reset flow when the real IdP is connected.
