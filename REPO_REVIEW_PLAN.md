# CSVEditor Repo Scan: Issues, UI Improvements, Local Save, and Architecture Plan

## Current Snapshot
- Stack: Streamlit + pandas + pure-Python parsing helpers.
- Main app: `csveditor.py`.
- Parsing/business helpers: `core.py`.
- Test coverage: unit tests for parsing/date normalization only.

## Errors / Risks We Can Fix Quickly
1. **Test discovery mismatch**
   - `python -m unittest -v` runs 0 tests, while discovery works with `-s tests`.
   - Fix: add `pytest` or package-style test discovery config; or document canonical command in README/Makefile.

2. **Broad exception handling hides data issues**
   - Multiple `except Exception` blocks in filters and parsing paths can swallow real defects.
   - Fix: catch specific exceptions (`InvalidOperation`, `ValueError`) and surface row-level warnings.

3. **Potential data loss when saving edits from filtered view**
   - Save flow only updates IDs present in the edited dataframe; new rows inserted in editor under filtered/sorted state can be dropped or inconsistently merged.
   - Fix: maintain source-of-truth by immutable row IDs + explicit create/update/delete diffing.

4. **Date parsing ambiguity**
   - `normalize_date` accepts both `%d/%m/%Y` and `%m/%d/%Y`, which can misinterpret dates like `01/02/2025`.
   - Fix: user-selectable locale mode, or strict preferred format with inline validation hints.

5. **String-based date filtering in dataframe**
   - Date range filter compares normalized date strings; this works because format is `YYYY/MM/DD` but is brittle.
   - Fix: keep a parsed datetime column for all filtering/sorting.

6. **Session-state only persistence**
   - Data is lost on refresh/redeploy/session end unless user manually downloads CSV.
   - Fix: add autosave backend (local file/SQLite/browser storage).

## UI / UX Improvements (High Impact)
1. **Guided import UX**
   - Add field mapping wizard (Date/Description/Amount/Category detection + preview + validation report).

2. **Inline validation chips**
   - Show per-row validation badges and hover details in the editor before save.

3. **Faster ledger workflow**
   - Keyboard-first add row form (Enter to submit, Tab order, duplicate-last-row shortcut).

4. **Review tab ergonomics**
   - Sticky filter bar.
   - Save status indicator (unsaved changes dot + timestamp).
   - Preset filter views (e.g., “Unverified expenses”, “This month”).

5. **Visual hierarchy refresh**
   - More distinct sections/cards around metrics, editor, and export.
   - Better color semantics for positive/negative/invalid values.

6. **Reconciliation support**
   - Add “statement balance at date”, “difference”, and “matched/unmatched” statuses.

## Local Save Options (Recommended Paths)

### Option A — JSON file autosave (fastest)
- Persist `rows`, `next_id`, and settings to a local JSON file on each save action.
- Pros: simple, no schema migration.
- Cons: weaker concurrency and partial-write risk.
- Good for single-user desktop usage.

### Option B — SQLite (best default)
- Add `sqlite3`/SQLModel layer with tables: `transactions`, `app_settings`, `saved_filters`.
- Pros: robust local persistence, transactional writes, easy backups.
- Cons: modest complexity increase.
- Best balance for this app.

### Option C — Browser storage only (if migrating frontend)
- localStorage/IndexedDB with export/import.
- Pros: offline-first UX.
- Cons: browser/device scoped, harder cross-device backup.

## Should You Move to React?

### Keep Streamlit if:
- You prioritize shipping speed and Python-centric workflows.
- Main users are internal/small team and desktop browser usage is acceptable.
- Complex multi-user auth/collaboration is not required.

### Consider React (or Next.js) if:
- You want sophisticated spreadsheet-like interactions, offline sync, granular keyboard UX.
- You need stronger client-state management and reusable design system components.
- You expect growth toward multi-user collaboration and richer integrations.

### Practical recommendation
- **Phase 1:** Stay in Streamlit, introduce SQLite persistence + better import/validation + UX refinements.
- **Phase 2:** Reassess after usage feedback. If UX constraints remain, migrate incrementally to React frontend with a lightweight Python API backend (FastAPI).

## 30/60/90 Plan

### Next 30 days (stabilize)
- Add persistence (SQLite).
- Tighten exception handling and date parsing mode.
- Improve test execution command + add integration tests for import/edit/save.

### 60 days (usability)
- Add import mapping preview.
- Add saved filters and unsaved-change indicators.
- Add reconciliation views and monthly report enhancements.

### 90 days (scale decision)
- Collect telemetry/feedback (edit latency, import error rates, save frequency).
- Decide whether Streamlit can meet UX goals.
- If not, scope React migration for editor/review surface first.
