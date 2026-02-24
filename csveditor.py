from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
import streamlit as st

from core import Transaction, date_key, money2, norm_spaces, normalize_date, parse_decimal, try_parse_line

st.set_page_config(page_title="Fast Bank Entry (Streamlit)", layout="wide")
st.title("Fast Bank Entry")
st.caption("Browser-based CSV and transaction workflow powered by Streamlit.")


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


def rows_to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["id", "date", "description", "category", "amount", "running"])

    sorted_rows = sorted(rows, key=lambda r: date_key(r["date"]))
    running = Decimal("0")
    computed = []
    for row in sorted_rows:
        running += row["amount"]
        computed.append({**row, "running": money2(running)})

    df = pd.DataFrame(computed)
    return df


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

st.subheader("Add transaction")
col1, col2, col3, col4 = st.columns([2, 4, 2, 3])
with col1:
    input_date = st.text_input("Date", placeholder="YYYY/MM/DD or DD/MM/YYYY")
with col2:
    input_desc = st.text_input("Description")
with col3:
    input_amount = st.text_input("Amount")
with col4:
    input_category = st.text_input("Category")

if st.button("Add row", type="primary"):
    payload = parse_single_row(input_date, input_desc, input_amount, input_category)
    if not payload:
        st.error("Could not parse row. Check date/amount fields.")
    else:
        st.session_state.rows.append(payload)
        st.session_state.next_id += 1
        st.success("Transaction added.")

st.subheader("Bulk import")
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

left, right = st.columns([2, 1])
with left:
    query = st.text_input("Filter text")
with right:
    min_amt_text = st.text_input("Min amount")

all_df = rows_to_df(st.session_state.rows)

if not all_df.empty:
    view_df = all_df.copy()
    if query.strip():
        mask = (
            view_df["description"].str.contains(query, case=False, na=False)
            | view_df["category"].str.contains(query, case=False, na=False)
            | view_df["date"].str.contains(query, case=False, na=False)
        )
        view_df = view_df[mask]

    if min_amt_text.strip():
        try:
            min_amt = parse_decimal(min_amt_text)
            view_df = view_df[view_df["amount"].apply(lambda v: Decimal(str(v)) >= min_amt)]
        except Exception:
            st.warning("Invalid min amount filter; ignored.")

    net_change = view_df["amount"].apply(lambda v: Decimal(str(v))).sum() if not view_df.empty else Decimal("0")
    dynamic_closing = money2(opening + net_change)

    m1, m2, m3 = st.columns(3)
    m1.metric("Rows", len(view_df))
    m2.metric("Net change", f"{money2(net_change):.2f}")
    m3.metric("Dynamic closing", f"{dynamic_closing:.2f}")

    if target is not None:
        delta = money2(dynamic_closing - target)
        if delta == 0:
            st.success("Closing balance matches target.")
        else:
            st.info(f"Difference vs target: {delta:.2f}")

    st.subheader("Editable transactions")
    edited = st.data_editor(
        view_df.drop(columns=["running"]),
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "date": st.column_config.TextColumn("Date"),
            "description": st.column_config.TextColumn("Description"),
            "category": st.column_config.TextColumn("Category"),
            "amount": st.column_config.NumberColumn("Amount", step=0.01, format="%.2f"),
        },
    )

    if st.button("Save edits"):
        updated_rows = []
        for _, row in edited.iterrows():
            d = normalize_date(str(row["date"]))
            if not d:
                continue
            updated_rows.append(
                {
                    "id": int(row["id"]),
                    "date": d,
                    "description": norm_spaces(str(row["description"])),
                    "category": norm_spaces(str(row.get("category", ""))),
                    "amount": money2(parse_decimal(str(row["amount"]))),
                }
            )
        st.session_state.rows = updated_rows
        st.success("Edits saved.")

    st.subheader("Category summary")
    if (view_df["category"].astype(str).str.strip() != "").any():
        summary = (
            view_df.assign(amount=view_df["amount"].apply(lambda v: float(Decimal(str(v)))))
            .groupby("category", as_index=False)["amount"]
            .sum()
            .sort_values("amount", ascending=False)
        )
        st.dataframe(summary, hide_index=True, use_container_width=True)
    else:
        st.caption("No categorized rows yet.")

    st.download_button(
        "Download CSV",
        data=export_csv(rows_to_df(st.session_state.rows)),
        file_name="transactions.csv",
        mime="text/csv",
    )

    if st.button("Clear all rows"):
        st.session_state.rows = []
        st.success("All rows removed.")
else:
    st.info("No rows yet. Add a transaction or import pasted lines.")
