from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Generator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(__file__).resolve().parent / "transactions.db"

app = FastAPI(title="CSVEditor Local API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TransactionIn(BaseModel):
    date: str = Field(..., description="YYYY/MM/DD")
    description: str
    category: str = ""
    amount: str
    verified: bool = False
    review_note: str = ""


class TransactionOut(TransactionIn):
    id: int


@contextmanager
def db_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def normalize_date(value: str) -> str:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%Y/%m/%d")
        except ValueError:
            continue
    raise ValueError("Invalid date format")


def normalize_amount(value: str) -> str:
    cleaned = value.strip().replace(",", "")
    try:
        dec = Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid amount")
    return str(dec)


def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "description": row["description"],
        "category": row["category"],
        "amount": row["amount"],
        "verified": bool(row["verified"]),
        "review_note": row["review_note"],
    }


@app.on_event("startup")
def startup() -> None:
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                amount TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                review_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions() -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM transactions ORDER BY date ASC, id ASC").fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/transactions", response_model=TransactionOut)
def create_transaction(payload: TransactionIn) -> dict:
    try:
        date = normalize_date(payload.date)
        amount = normalize_amount(payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions (date, description, category, amount, verified, review_note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                date,
                payload.description.strip(),
                payload.category.strip(),
                amount,
                1 if payload.verified else 0,
                payload.review_note.strip(),
            ),
        )
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_dict(row)


@app.put("/transactions/{tx_id}", response_model=TransactionOut)
def update_transaction(tx_id: int, payload: TransactionIn) -> dict:
    try:
        date = normalize_date(payload.date)
        amount = normalize_amount(payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with db_conn() as conn:
        exists = conn.execute("SELECT id FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Transaction not found")
        conn.execute(
            """
            UPDATE transactions
            SET date = ?, description = ?, category = ?, amount = ?, verified = ?, review_note = ?
            WHERE id = ?
            """,
            (
                date,
                payload.description.strip(),
                payload.category.strip(),
                amount,
                1 if payload.verified else 0,
                payload.review_note.strip(),
                tx_id,
            ),
        )
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    return row_to_dict(row)


@app.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int) -> dict[str, bool]:
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"deleted": True}
