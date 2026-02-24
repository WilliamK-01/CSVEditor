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


def tx_dict(tx: Transaction, category: str = "") -> dict[str, Any]:
    return {
        "id": st.session_state.next_id,
        "date": tx.date,
        "description": tx.description,
        "category": category,
        "amount": money2(tx.amount),
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
    }


def rows_to_df(rows: list[dict[str, Any]], opening: Decimal = Decimal("0")) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["id", "date", "description", "category", "amount", "running"])

    sorted_rows = sorted(rows, key=lambda r: date_key(r["date"]))
    running = opening
    computed = []
    for row in sorted_rows:
        running += Decimal(str(row["amount"]))
        computed.append({**row, "running": money2(running)})

    return pd.DataFrame(computed)


def export_csv(df: pd.DataFrame) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Description", "Category", "Amount", "Running"])
    for _, row in df.iterrows():
        writer.writerow([
            row["date"],
            row["description"],
            row["category"],
            f"{Decimal(str(row['amount'])):.2f}",
            f"{Decimal(str(row['running'])):.2f}",
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


def apply_filters(df: pd.DataFrame, query: str, categories: list[str], date_range: tuple[date, date] | None,
                  min_amt_text: str, max_amt_text: str, tx_kind: str) -> pd.DataFrame:
    view_df = df.copy()

    if query.strip():
        mask = (
            view_df["description"].str.contains(query, case=False, na=False)
            | view_df["category"].str.contains(query, case=False, na=False)
            | view_df["date"].str.contains(query, case=False, na=False)
        )
        view_df = view_df[mask]

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

    return view_df


ensure_state()

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
    recurring = st.selectbox("Recurring template", ["", "Salary", "Rent", "Utilities", "Groceries", "Transfer"])
    if st.button("Add today from template") and recurring:
        amount_defaults = {
            "Salary": "2500",
            "Rent": "-1200",
            "Utilities": "-180",
            "Groceries": "-90",
            "Transfer": "0",
        }
        payload = parse_single_row(date.today().strftime("%Y/%m/%d"), recurring, amount_defaults[recurring], recurring)
        if payload:
            st.session_state.rows.append(payload)
            st.session_state.next_id += 1
            st.success(f"{recurring} added.")

    if st.button("Clear all rows"):
        st.session_state.rows = []
        st.success("All rows removed.")

entry_tab, review_tab, insight_tab = st.tabs(["Add & Import", "Review & Edit", "Insights"])

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

all_df = rows_to_df(st.session_state.rows, opening=opening)

with review_tab:
    if all_df.empty:
        st.info("No rows yet. Add transactions in the Add & Import tab.")
    else:
        st.subheader("Filters")
        f1, f2, f3, f4, f5, f6 = st.columns([2, 2, 2, 2, 2, 2])
        with f1:
            query = st.text_input("Search")
        with f2:
            categories = sorted([c for c in all_df["category"].astype(str).unique() if c.strip()])
            selected_categories = st.multiselect("Category", options=categories)
        with f3:
            min_amt_text = st.text_input("Min amount")
        with f4:
            max_amt_text = st.text_input("Max amount")
        with f5:
            tx_kind = st.selectbox("Type", ["All", "Income", "Expense"])
        with f6:
            valid_dates = pd.to_datetime(all_df["date"], format="%Y/%m/%d", errors="coerce").dropna()
            date_range = None
            if not valid_dates.empty:
                date_range = st.date_input(
                    "Date range",
                    value=(valid_dates.min().date(), valid_dates.max().date()),
                )

        view_df = apply_filters(all_df, query, selected_categories, date_range, min_amt_text, max_amt_text, tx_kind)

        net_change = view_df["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")
        dynamic_closing = money2(opening + net_change)
        income = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) > 0)]["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")
        expense = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) < 0)]["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Rows", len(view_df))
        m2.metric("Income", f"{money2(income):.2f}")
        m3.metric("Expense", f"{money2(expense):.2f}")
        m4.metric("Net change", f"{money2(net_change):.2f}")
        m5.metric("Dynamic closing", f"{dynamic_closing:.2f}")

        if target is not None:
            delta = money2(dynamic_closing - target)
            if delta == 0:
                st.success("Closing balance matches target.")
            else:
                st.info(f"Difference vs target: {delta:.2f}")

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
            },
        )

        c1, c2, c3 = st.columns([2, 2, 2])
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
                        }
                    )

                updated_map = {r["id"]: r for r in edited_rows}
                preserved = []
                for row in st.session_state.rows:
                    row_id = int(row["id"])
                    if row_id in updated_map:
                        preserved.append(updated_map[row_id])
                    else:
                        preserved.append(row)
                st.session_state.rows = preserved
                st.success("Edits saved.")

        with c2:
            ids_to_delete = st.multiselect("Delete selected IDs", options=view_df["id"].tolist())
            if st.button("Delete selected") and ids_to_delete:
                delete_set = set(ids_to_delete)
                st.session_state.rows = [r for r in st.session_state.rows if int(r["id"]) not in delete_set]
                st.success(f"Deleted {len(delete_set)} row(s).")

        with c3:
            st.download_button(
                "Download CSV",
                data=export_csv(rows_to_df(st.session_state.rows, opening=opening)),
                file_name="transactions.csv",
                mime="text/csv",
            )

with insight_tab:
    if all_df.empty:
        st.info("No insights yet. Add transactions to generate summaries.")
    else:
        st.subheader("Category summary")
        if (all_df["category"].astype(str).str.strip() != "").any():
            summary = (
                all_df.assign(amount=all_df["amount"].apply(lambda v: float(Decimal(str(v)))))
                .groupby("category", as_index=False)["amount"]
                .sum()
                .sort_values("amount", ascending=False)
            )
            st.dataframe(summary, hide_index=True, use_container_width=True)
            st.bar_chart(summary.set_index("category"))
        else:
            st.caption("No categorized rows yet.")

        st.subheader("Monthly net trend")
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
            st.dataframe(monthly, hide_index=True, use_container_width=True)
            st.line_chart(monthly.set_index("month"))
