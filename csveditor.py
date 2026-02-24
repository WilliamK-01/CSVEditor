from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st

from core import Transaction, date_key, money2, norm_spaces, normalize_date, parse_decimal, try_parse_line

st.set_page_config(page_title="Fast Bank Entry (Streamlit)", layout="wide")
st.title("Fast Bank Entry")
st.caption("High-speed browser workflow for transaction capture, reconciliation, and export.")



def ensure_state() -> None:
    if "rows" not in st.session_state:
        st.session_state.rows: list[dict[str, Any]] = []
    if "next_id" not in st.session_state:
        st.session_state.next_id = 1



def default_row_state() -> dict[str, Any]:
    return {"verified": False, "review_note": ""}



def tx_dict(tx: Transaction, category: str = "") -> dict[str, Any]:
    return {
        "id": st.session_state.next_id,
        "date": tx.date,
        "description": tx.description,
        "category": category,
        "amount": money2(tx.amount),
        **default_row_state(),
    }



def parse_single_row(date_text: str, description: str, amount_text: str, category: str = "") -> dict[str, Any] | None:
    d = normalize_date(date_text)
    if not d:
        return None
    try:
        amt = money2(parse_decimal(amount_text))
    except (InvalidOperation, ValueError):
        return None

    return {
        "id": st.session_state.next_id,
        "date": d,
        "description": norm_spaces(description),
        "category": norm_spaces(category),
        "amount": amt,
        **default_row_state(),
    }



def validate_row(row: dict[str, Any]) -> str:
    issues: list[str] = []
    if not normalize_date(str(row.get("date", ""))):
        issues.append("Invalid date")
    if not norm_spaces(str(row.get("description", ""))):
        issues.append("Missing description")
    try:
        parse_decimal(str(row.get("amount", "")))
    except Exception:
        issues.append("Invalid amount")
    return "OK" if not issues else "; ".join(issues)



def rows_to_df(rows: list[dict[str, Any]], opening: Decimal = Decimal("0")) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["id", "date", "description", "category", "amount", "running", "verified", "review_note", "status"])

    sorted_rows = sorted(rows, key=lambda r: date_key(r["date"]))
    running = opening
    computed = []
    for row in sorted_rows:
        running += Decimal(str(row["amount"]))
        hydrated = {**default_row_state(), **row}
        hydrated["status"] = validate_row(hydrated)
        computed.append({**hydrated, "running": money2(running)})

    return pd.DataFrame(computed)



def export_csv(df: pd.DataFrame) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Description", "Category", "Amount", "Running", "Verified", "ReviewNote", "Status"])
    for _, row in df.iterrows():
        writer.writerow([
            row["date"],
            row["description"],
            row["category"],
            f"{Decimal(str(row['amount'])):.2f}",
            f"{Decimal(str(row['running'])):.2f}",
            "Yes" if bool(row.get("verified", False)) else "No",
            row.get("review_note", ""),
            row.get("status", ""),
        ])
    return out.getvalue()



def import_structured_file(uploaded_file: Any) -> tuple[int, int]:
    text = uploaded_file.getvalue().decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return (0, 0)

    normalized = {f.lower().strip(): f for f in reader.fieldnames if isinstance(f, str)}
    date_col = normalized.get("date")
    desc_col = normalized.get("description") or normalized.get("details")
    amount_col = normalized.get("amount")
    category_col = normalized.get("category")

    if not date_col or not desc_col or not amount_col:
        return (0, 0)

    added = 0
    skipped = 0
    for row in reader:
        payload = parse_single_row(
            str(row.get(date_col, "")),
            str(row.get(desc_col, "")),
            str(row.get(amount_col, "")),
            str(row.get(category_col, "")) if category_col else "",
        )
        if payload:
            st.session_state.rows.append(payload)
            st.session_state.next_id += 1
            added += 1
        else:
            skipped += 1

    return (added, skipped)



def apply_filters(df: pd.DataFrame, query: str, name_query: str, categories: list[str], date_range: tuple[date, date] | None,
                  min_amt_text: str, max_amt_text: str, tx_kind: str, verified_filter: str) -> pd.DataFrame:
    view_df = df.copy()

    if query.strip():
        mask = (
            view_df["description"].str.contains(query, case=False, na=False)
            | view_df["category"].str.contains(query, case=False, na=False)
            | view_df["date"].str.contains(query, case=False, na=False)
            | view_df["review_note"].str.contains(query, case=False, na=False)
        )
        view_df = view_df[mask]

    if name_query.strip():
        view_df = view_df[view_df["description"].str.contains(name_query, case=False, na=False)]

    if categories:
        view_df = view_df[view_df["category"].isin(categories)]

    if date_range and len(date_range) == 2:
        start = pd.to_datetime(date_range[0]).strftime("%Y/%m/%d")
        end = pd.to_datetime(date_range[1]).strftime("%Y/%m/%d")
        view_df = view_df[(view_df["date"] >= start) & (view_df["date"] <= end)]

    if min_amt_text.strip():
        try:
            min_amt = parse_decimal(min_amt_text)
            view_df = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) >= min_amt)]
        except Exception:
            st.warning("Invalid minimum amount filter; ignored.")

    if max_amt_text.strip():
        try:
            max_amt = parse_decimal(max_amt_text)
            view_df = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) <= max_amt)]
        except Exception:
            st.warning("Invalid maximum amount filter; ignored.")

    if tx_kind == "Income":
        view_df = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) > 0)]
    elif tx_kind == "Expense":
        view_df = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) < 0)]

    if verified_filter == "Verified only":
        view_df = view_df[view_df["verified"]]
    elif verified_filter == "Unverified only":
        view_df = view_df[~view_df["verified"]]

    return view_df



def amount_color(_: Any) -> str:
    try:
        amount = Decimal(str(_))
    except Exception:
        return ""
    if amount < 0:
        return "color: #c62828; font-weight: 600"
    if amount > 0:
        return "color: #1565c0; font-weight: 600"
    return ""



def tax_report(df: pd.DataFrame) -> pd.DataFrame:
    report_df = df.copy()
    report_df["category"] = report_df["category"].fillna("").astype(str)
    report_df["amount_decimal"] = report_df["amount"].apply(lambda v: Decimal(str(v)))

    vat_outputs = report_df[report_df["category"].str.contains("vat output|output vat|vat sale", case=False, regex=True)]["amount_decimal"].sum()
    vat_inputs = report_df[report_df["category"].str.contains("vat input|input vat|vat expense", case=False, regex=True)]["amount_decimal"].sum()

    paye_total = report_df[report_df["category"].str.contains("paye", case=False)]["amount_decimal"].sum()
    uif_total = report_df[report_df["category"].str.contains("uif", case=False)]["amount_decimal"].sum()
    sdl_total = report_df[report_df["category"].str.contains("sdl", case=False)]["amount_decimal"].sum()

    gross_income = report_df[report_df["amount_decimal"] > 0]["amount_decimal"].sum()
    deductible_expenses = report_df[report_df["amount_decimal"] < 0]["amount_decimal"].sum()

    records = [
        {"Metric": "Gross income", "Value": money2(gross_income)},
        {"Metric": "Deductible expenses", "Value": money2(deductible_expenses)},
        {"Metric": "Output VAT (from categories)", "Value": money2(vat_outputs)},
        {"Metric": "Input VAT (from categories)", "Value": money2(vat_inputs)},
        {"Metric": "Estimated VAT payable", "Value": money2(vat_outputs + vat_inputs)},
        {"Metric": "PAYE total", "Value": money2(paye_total)},
        {"Metric": "UIF total", "Value": money2(uif_total)},
        {"Metric": "SDL total", "Value": money2(sdl_total)},
    ]
    return pd.DataFrame(records)


ensure_state()

nav_choice = st.radio("Workspace", ["CSV Editor", "Reports", "Extra Tools (coming soon)"], horizontal=True)
if nav_choice == "Extra Tools (coming soon)":
    st.info("Extra tools will be added here. Continue using CSV Editor and Reports for now.")

with st.sidebar:
    st.subheader("Balances")
    opening_text = st.text_input("Opening balance", value="0")
    target_text = st.text_input("Target closing (optional)", value="")

    try:
        opening = money2(parse_decimal(opening_text))
    except Exception:
        opening = Decimal("0")

    try:
        target = money2(parse_decimal(target_text)) if target_text.strip() else None
    except Exception:
        target = None

    st.divider()
    st.subheader("Quick actions")
    recurring = st.selectbox("Recurring template", ["", "Salary", "Rent", "Utilities", "Groceries", "Transfer", "PAYE", "UIF", "VAT Output", "VAT Input"])
    if st.button("Add today from template") and recurring:
        amount_defaults = {
            "Salary": "2500",
            "Rent": "-1200",
            "Utilities": "-180",
            "Groceries": "-90",
            "Transfer": "0",
            "PAYE": "-650",
            "UIF": "-120",
            "VAT Output": "300",
            "VAT Input": "-180",
        }
        payload = parse_single_row(date.today().strftime("%Y/%m/%d"), recurring, amount_defaults[recurring], recurring)
        if payload:
            st.session_state.rows.append(payload)
            st.session_state.next_id += 1
            st.success(f"{recurring} added.")

    if st.button("Clear all rows"):
        st.session_state.rows = []
        st.success("All rows removed.")

all_df = rows_to_df(st.session_state.rows, opening=opening)

if nav_choice == "CSV Editor":
    entry_tab, review_tab = st.tabs(["Add & Import", "Review & Edit"])

    with entry_tab:
        st.subheader("Add transaction")
        with st.form("add_single"):
            col1, col2, col3, col4 = st.columns([2, 4, 2, 3])
            with col1:
                input_date = st.text_input("Date", placeholder="YYYY/MM/DD or DD/MM/YYYY")
            with col2:
                input_desc = st.text_input("Description")
            with col3:
                input_amount = st.text_input("Amount")
            with col4:
                input_category = st.text_input("Category")
            submitted = st.form_submit_button("Add row", type="primary")

        if submitted:
            payload = parse_single_row(input_date, input_desc, input_amount, input_category)
            if not payload:
                st.error("Could not parse row. Check date and amount fields.")
            else:
                st.session_state.rows.append(payload)
                st.session_state.next_id += 1
                st.success("Transaction added.")

        st.subheader("Bulk import from pasted text")
        raw_text = st.text_area("Paste CSV, TSV, or spaced lines", height=140)
        if st.button("Import pasted lines"):
            added = 0
            for line in raw_text.splitlines():
                tx = try_parse_line(line)
                if tx:
                    st.session_state.rows.append(tx_dict(tx))
                    st.session_state.next_id += 1
                    added += 1
            st.success(f"Imported {added} rows.")

        st.subheader("Bulk import from file")
        uploaded = st.file_uploader("Upload CSV with Date, Description, Amount (optional Category)", type=["csv"])
        if uploaded is not None and st.button("Import uploaded CSV"):
            added, skipped = import_structured_file(uploaded)
            st.success(f"Imported {added} rows.")
            if skipped:
                st.warning(f"Skipped {skipped} invalid rows.")

    with review_tab:
        if all_df.empty:
            st.info("No rows yet. Add transactions in the Add & Import tab.")
        else:
            st.subheader("Filters")
            f1, f2, f3, f4, f5, f6, f7, f8 = st.columns([2, 2, 2, 2, 2, 2, 2, 2])
            with f1:
                query = st.text_input("Search")
            with f2:
                name_query = st.text_input("Filter by name")
            with f3:
                categories = sorted([c for c in all_df["category"].astype(str).unique() if c.strip()])
                selected_categories = st.multiselect("Category", options=categories)
            with f4:
                min_amt_text = st.text_input("Min amount")
            with f5:
                max_amt_text = st.text_input("Max amount")
            with f6:
                tx_kind = st.selectbox("Type", ["All", "Income", "Expense"])
            with f7:
                verified_filter = st.selectbox("Verification", ["All", "Verified only", "Unverified only"])
            with f8:
                valid_dates = pd.to_datetime(all_df["date"], format="%Y/%m/%d", errors="coerce").dropna()
                date_range = None
                if not valid_dates.empty:
                    date_range = st.date_input(
                        "Date range",
                        value=(valid_dates.min().date(), valid_dates.max().date()),
                    )

            view_df = apply_filters(all_df, query, name_query, selected_categories, date_range, min_amt_text, max_amt_text, tx_kind, verified_filter)

            net_change = view_df["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")
            dynamic_closing = money2(opening + net_change)
            income = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) > 0)]["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")
            expense = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) < 0)]["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")
            verified_count = int(view_df["verified"].sum()) if not view_df.empty else 0

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Rows", len(view_df))
            m2.metric("Income", f"{money2(income):.2f}")
            m3.metric("Expense", f"{money2(expense):.2f}")
            m4.metric("Net change", f"{money2(net_change):.2f}")
            m5.metric("Dynamic closing", f"{dynamic_closing:.2f}")
            m6.metric("Verified lines", f"{verified_count}/{len(view_df)}")

            if target is not None:
                delta = money2(dynamic_closing - target)
                if delta == 0:
                    st.success("Closing balance matches target.")
                else:
                    st.info(f"Difference vs target: {delta:.2f}")

            st.subheader("Preview (amount colours)")
            st.dataframe(
                view_df[["id", "date", "description", "category", "amount", "running", "verified", "status"]].style.map(amount_color, subset=["amount", "running"]),
                hide_index=True,
                use_container_width=True,
            )

            st.subheader("Editable transactions")
            edited = st.data_editor(
                view_df,
                hide_index=True,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "date": st.column_config.TextColumn("Date"),
                    "description": st.column_config.TextColumn("Description"),
                    "category": st.column_config.TextColumn("Category"),
                    "amount": st.column_config.NumberColumn("Amount", step=0.01, format="%.2f"),
                    "running": st.column_config.NumberColumn("Running", step=0.01, format="%.2f", disabled=True),
                    "verified": st.column_config.CheckboxColumn("Verified"),
                    "review_note": st.column_config.TextColumn("Review note"),
                    "status": st.column_config.TextColumn("Status", disabled=True),
                },
            )

            c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
            with c1:
                if st.button("Save edits"):
                    edited_rows: list[dict[str, Any]] = []
                    for _, row in edited.iterrows():
                        d = normalize_date(str(row["date"]))
                        if not d:
                            continue
                        edited_rows.append(
                            {
                                "id": int(row["id"]),
                                "date": d,
                                "description": norm_spaces(str(row["description"])),
                                "category": norm_spaces(str(row.get("category", ""))),
                                "amount": money2(parse_decimal(str(row["amount"]))),
                                "verified": bool(row.get("verified", False)),
                                "review_note": norm_spaces(str(row.get("review_note", ""))),
                            }
                        )

                    updated_map = {r["id"]: r for r in edited_rows}
                    preserved = []
                    for row in st.session_state.rows:
                        row_id = int(row["id"])
                        if row_id in updated_map:
                            preserved.append(updated_map[row_id])
                        else:
                            preserved.append({**default_row_state(), **row})
                    st.session_state.rows = preserved
                    st.success("Edits saved.")

            with c2:
                ids_to_delete = st.multiselect("Delete selected IDs", options=view_df["id"].tolist())
                if st.button("Delete selected") and ids_to_delete:
                    delete_set = set(ids_to_delete)
                    st.session_state.rows = [r for r in st.session_state.rows if int(r["id"]) not in delete_set]
                    st.success(f"Deleted {len(delete_set)} row(s).")

            with c3:
                batch_ids = st.multiselect("Batch select IDs", options=view_df["id"].tolist())
                batch_category = st.text_input("Batch set category")
                batch_verify = st.checkbox("Mark selected as verified")
                if st.button("Apply batch edit") and batch_ids:
                    id_set = set(batch_ids)
                    updated_rows = []
                    for row in st.session_state.rows:
                        row_id = int(row["id"])
                        hydrated = {**default_row_state(), **row}
                        if row_id in id_set:
                            if batch_category.strip():
                                hydrated["category"] = norm_spaces(batch_category)
                            if batch_verify:
                                hydrated["verified"] = True
                        updated_rows.append(hydrated)
                    st.session_state.rows = updated_rows
                    st.success(f"Updated {len(batch_ids)} selected row(s).")

            with c4:
                st.download_button(
                    "Download CSV",
                    data=export_csv(rows_to_df(st.session_state.rows, opening=opening)),
                    file_name="transactions.csv",
                    mime="text/csv",
                )

if nav_choice == "Reports":
    if all_df.empty:
        st.info("No data available for reports yet.")
    else:
        st.subheader("South African bookkeeping and tax report")
        st.caption("Tip: map your categories using names such as VAT Output, VAT Input, PAYE, UIF, and SDL for better estimates.")

        report = tax_report(all_df)
        st.dataframe(report.style.map(amount_color, subset=["Value"]), hide_index=True, use_container_width=True)

        trend = all_df.copy()
        trend["month"] = pd.to_datetime(trend["date"], format="%Y/%m/%d", errors="coerce").dt.strftime("%Y-%m")
        trend = trend.dropna(subset=["month"])
        if not trend.empty:
            monthly = (
                trend.assign(amount=trend["amount"].apply(lambda v: float(Decimal(str(v)))))
                .groupby("month", as_index=False)["amount"]
                .sum()
                .sort_values("month")
            )
            st.subheader("Monthly net trend")
            st.dataframe(monthly, hide_index=True, use_container_width=True)
            st.line_chart(monthly.set_index("month"))
