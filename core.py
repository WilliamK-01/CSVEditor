from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


@dataclass(frozen=True)
class Transaction:
    date: str
    description: str
    amount: Decimal


def norm_spaces(s: str) -> str:
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_decimal(s: str) -> Decimal:
    s = s.strip()
    if not s:
        return Decimal("0")

    # Keep only number-related symbols
    s = re.sub(r"[^\d\-,.]", "", s)

    # locale-ish handling:
    # If both separators appear, choose the last one as decimal separator.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")

    return Decimal(s)


def money2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_date(s: str) -> str:
    s = norm_spaces(s)
    if not s:
        return ""

    candidates = [
        "%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d",
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
        "%m/%d/%Y", "%m-%d-%Y",
    ]
    for fmt in candidates:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y/%m/%d")
        except ValueError:
            pass

    if re.fullmatch(r"\d{8}", s):
        try:
            dt = datetime.strptime(s, "%Y%m%d")
            return dt.strftime("%Y/%m/%d")
        except ValueError:
            pass

    return ""


def date_key(date_str: str):
    d = normalize_date(date_str)
    if not d:
        return (1, "9999/99/99")
    return (0, d)


def try_parse_line(line: str) -> Optional[Transaction]:
    raw = line.strip()
    if not raw:
        return None

    try:
        row = next(csv.reader([raw]))
        if len(row) >= 3:
            d = normalize_date(row[0])
            if d:
                return Transaction(d, norm_spaces(row[1]), money2(parse_decimal(row[2])))
    except (ValueError, ArithmeticError, csv.Error):
        pass

    if "\t" in raw:
        parts = [p.strip() for p in raw.split("\t") if p.strip() != ""]
        if len(parts) >= 3:
            d = normalize_date(parts[0])
            if d:
                return Transaction(d, norm_spaces(parts[1]), money2(parse_decimal(parts[2])))

    parts = re.split(r"\s{2,}", raw)
    if len(parts) >= 3:
        d = normalize_date(parts[0])
        if d:
            return Transaction(d, norm_spaces(parts[1]), money2(parse_decimal(parts[2])))

    toks = raw.split()
    if len(toks) >= 3:
        d = normalize_date(toks[0])
        if d:
            try:
                amt = money2(parse_decimal(toks[-1]))
                return Transaction(d, norm_spaces(" ".join(toks[1:-1])), amt)
            except ArithmeticError:
                pass
            except ValueError:
                pass

    return None
