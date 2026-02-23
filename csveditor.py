import sys
import json
import csv
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from datetime import datetime

from PyQt6.QtCore import Qt, QStringListModel, QEvent
from PyQt6.QtGui import QKeySequence, QAction, QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QCompleter,
    QCheckBox
)

APP_NAME = "Fast Bank Entry (PyQt6)"
DICT_FILE = Path("descriptions_dict.json")
LAST_FILE = Path("last_session.json")


def norm_spaces(s: str) -> str:
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_decimal(s: str) -> Decimal:
    s = s.strip()
    if not s:
        return Decimal("0")
    s = re.sub(r"[^\d\-,.]", "", s)

    if "," in s and "." in s:
        s = s.replace(",", "")
    else:
        if "," in s and "." not in s:
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
        "%m/%d/%Y", "%m-%d-%Y"
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
    """
    Returns a sortable key for yyyy/mm/dd.
    Invalid or empty dates sort to the bottom.
    """
    d = normalize_date(date_str)
    if not d:
        return (1, "9999/99/99")  # invalid last
    return (0, d)


def try_parse_line(line: str):
    raw = line.strip()
    if not raw:
        return None

    try:
        row = next(csv.reader([raw]))
        if len(row) >= 3:
            d = normalize_date(row[0])
            if d:
                desc = norm_spaces(row[1])
                amt = money2(parse_decimal(row[2]))
                return d, desc, amt
    except Exception:
        pass

    if "\t" in raw:
        parts = [p.strip() for p in raw.split("\t") if p.strip() != ""]
        if len(parts) >= 3:
            d = normalize_date(parts[0])
            if d:
                desc = norm_spaces(parts[1])
                amt = money2(parse_decimal(parts[2]))
                return d, desc, amt

    parts = re.split(r"\s{2,}", raw)
    if len(parts) >= 3:
        d = normalize_date(parts[0])
        if d:
            desc = norm_spaces(parts[1])
            amt = money2(parse_decimal(parts[2]))
            return d, desc, amt

    toks = raw.split()
    if len(toks) >= 3:
        d = normalize_date(toks[0])
        if d:
            try:
                amt = money2(parse_decimal(toks[-1]))
                desc = norm_spaces(" ".join(toks[1:-1]))
                return d, desc, amt
            except Exception:
                pass

    return None


class FastEntry(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 840)

        self._updating = False
        self._next_row_id = 1

        self.descriptions = []
        self.load_dictionary()

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        # ===== Top controls =====
        top = QGridLayout()
        main.addLayout(top)

        self.opening = QLineEdit()
        self.opening.setPlaceholderText("Opening balance (e.g. 1234.56)")

        self.target_closing = QLineEdit()
        self.target_closing.setPlaceholderText("Fixed Closing balance target (statement)")

        self.dynamic_closing = QLineEdit()
        self.dynamic_closing.setReadOnly(True)
        self.dynamic_closing.setPlaceholderText("Dynamic closing (computed)")

        self.auto_sort = QCheckBox("Auto-sort by date")
        self.auto_sort.setChecked(True)

        self.btn_validate = QPushButton("Validate (Ctrl+B)")
        self.btn_validate.clicked.connect(self.validate_balances)

        self.status = QLabel(
            "Ready. Enter adds row. Ctrl+L Description, Ctrl+J Amount, Ctrl+I Import Paste, Ctrl+E Export. "
            "Auto-sort is manual and reliable now."
        )
        self.status.setWordWrap(True)

        top.addWidget(QLabel("Opening Balance:"), 0, 0)
        top.addWidget(self.opening, 0, 1)
        top.addWidget(QLabel("Target Closing:"), 0, 2)
        top.addWidget(self.target_closing, 0, 3)
        top.addWidget(QLabel("Dynamic Closing:"), 0, 4)
        top.addWidget(self.dynamic_closing, 0, 5)
        top.addWidget(self.auto_sort, 0, 6)
        top.addWidget(self.btn_validate, 0, 7)
        top.addWidget(self.status, 1, 0, 1, 8)

        self.opening.textChanged.connect(self.recompute_dynamic_closing)
        self.target_closing.textChanged.connect(self.recompute_dynamic_closing)
        self.auto_sort.stateChanged.connect(lambda: self.sort_by_date_if_enabled(None))

        # ===== Entry row =====
        entry = QHBoxLayout()
        main.addLayout(entry)

        self.date = QLineEdit()
        self.date.setPlaceholderText("Date (yyyy/mm/dd) - type once, auto-carries")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Description (autocomplete)")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Amount (negative for expense)")

        self.btn_add = QPushButton("Add (Enter)")
        self.btn_add.clicked.connect(self.add_current_row)

        entry.addWidget(QLabel("Date:"))
        entry.addWidget(self.date, 2)
        entry.addWidget(QLabel("Description:"))
        entry.addWidget(self.desc, 5)
        entry.addWidget(QLabel("Amount:"))
        entry.addWidget(self.amount, 2)
        entry.addWidget(self.btn_add, 1)

        # Autocomplete
        self.completer_model = QStringListModel(self.descriptions)
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.desc.setCompleter(self.completer)

        # ===== Table =====
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["date", "description", "amount"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.installEventFilter(self)
        self.table.itemChanged.connect(self.on_item_changed)
        main.addWidget(self.table, 6)

        # ===== Paste + buttons =====
        paste_row = QHBoxLayout()
        main.addLayout(paste_row)

        self.paste = QTextEdit()
        self.paste.setPlaceholderText(
            "Paste from old program here.\n"
            "Supported: CSV lines date,description,amount OR tab-separated OR 'date  desc  amount'.\n"
            "Then Ctrl+I (Import) or click Import Paste."
        )

        btns = QVBoxLayout()
        self.btn_import = QPushButton("Import Paste (Ctrl+I)")
        self.btn_import.clicked.connect(self.import_paste)

        self.btn_export = QPushButton("Export CSV… (Ctrl+E)")
        self.btn_export.clicked.connect(self.export_csv)

        self.btn_save = QPushButton("Save Session")
        self.btn_save.clicked.connect(self.save_session)

        self.btn_load = QPushButton("Load Session")
        self.btn_load.clicked.connect(self.load_session)

        self.btn_clear = QPushButton("Clear Table")
        self.btn_clear.clicked.connect(self.clear_table)

        self.btn_del = QPushButton("Delete Selected (Del)")
        self.btn_del.clicked.connect(self.delete_selected)

        btns.addWidget(self.btn_import)
        btns.addWidget(self.btn_export)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_load)
        btns.addWidget(self.btn_del)
        btns.addWidget(self.btn_clear)
        btns.addStretch(1)

        paste_row.addWidget(self.paste, 4)
        paste_row.addLayout(btns, 1)

        # Shortcuts + Enter flow
        self.make_shortcuts()
        self.date.returnPressed.connect(lambda: self.desc.setFocus())
        self.desc.returnPressed.connect(lambda: self.amount.setFocus())
        self.amount.returnPressed.connect(self.add_current_row)

        if LAST_FILE.exists():
            self.load_session(path=str(LAST_FILE), quiet=True)

        self.recompute_dynamic_closing()

    # ===== Helpers =====

    def set_status(self, msg: str):
        self.status.setText(msg)

    def set_lineedit_bg(self, le: QLineEdit, color_hex: str | None):
        if not color_hex:
            le.setStyleSheet("")
        else:
            le.setStyleSheet(f"QLineEdit {{ background-color: {color_hex}; }}")

    def trail_to_row_id(self, row_id: int | None):
        if row_id is None:
            return
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.data(Qt.ItemDataRole.UserRole) == row_id:
                self.table.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                self.table.setCurrentCell(r, 1)
                self.table.selectRow(r)
                return

    def sort_by_date_if_enabled(self, keep_row_id: int | None):
        if not self.auto_sort.isChecked():
            if keep_row_id is not None:
                self.trail_to_row_id(keep_row_id)
            return

        # Manual, reliable sort: extract -> sort -> rebuild
        rows = []
        for r in range(self.table.rowCount()):
            it_date = self.table.item(r, 0)
            it_desc = self.table.item(r, 1)
            it_amt = self.table.item(r, 2)

            d = it_date.text().strip() if it_date else ""
            desc = it_desc.text().strip() if it_desc else ""
            amt_txt = it_amt.text().strip() if it_amt else "0.00"
            row_id = it_date.data(Qt.ItemDataRole.UserRole) if it_date else None

            rows.append((date_key(d), d, desc, amt_txt, row_id))

        rows.sort(key=lambda x: (x[0], x[4] if x[4] is not None else 10**12))

        self._updating = True
        self.table.setRowCount(0)
        for _, d_raw, desc, amt_txt, row_id in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)

            d_norm = normalize_date(d_raw) or d_raw

            it_date = QTableWidgetItem(d_norm)
            it_date.setData(Qt.ItemDataRole.UserRole, row_id)

            it_desc = QTableWidgetItem(norm_spaces(desc))

            # normalize and color amount
            try:
                amt = money2(parse_decimal(amt_txt))
                amt_str = f"{amt:.2f}"
            except Exception:
                amt = Decimal("0.00")
                amt_str = "0.00"

            it_amt = QTableWidgetItem(amt_str)

            self.table.setItem(r, 0, it_date)
            self.table.setItem(r, 1, it_desc)
            self.table.setItem(r, 2, it_amt)

            self.color_amount_item(it_amt, amt)

        self._updating = False

        if keep_row_id is not None:
            self.trail_to_row_id(keep_row_id)

    # ===== Color coding =====

    def color_amount_item(self, item: QTableWidgetItem, amt: Decimal):
        # Brighter green, orange negatives
        if amt > 0:
            item.setForeground(QBrush(QColor("#00C853")))   # bright green
        elif amt < 0:
            item.setForeground(QBrush(QColor("#D97706")))   # orange
        else:
            item.setForeground(QBrush(QColor("#000000")))

    # ===== Dictionary =====

    def load_dictionary(self):
        if DICT_FILE.exists():
            try:
                data = json.loads(DICT_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.descriptions = sorted(set(norm_spaces(x) for x in data if str(x).strip()))
                else:
                    self.descriptions = []
            except Exception:
                self.descriptions = []
        else:
            self.descriptions = []

    def save_dictionary(self):
        try:
            DICT_FILE.write_text(json.dumps(self.descriptions, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def refresh_completer(self):
        self.completer_model.setStringList(self.descriptions)

    def learn_description(self, desc: str):
        desc = norm_spaces(desc)
        if not desc:
            return
        if desc not in self.descriptions:
            self.descriptions.append(desc)
            self.descriptions = sorted(set(self.descriptions), key=lambda s: s.lower())
            self.refresh_completer()
            self.save_dictionary()

    # ===== Shortcuts =====

    def make_shortcuts(self):
        act_desc = QAction(self)
        act_desc.setShortcut(QKeySequence("Ctrl+L"))
        act_desc.triggered.connect(lambda: self.desc.setFocus())
        self.addAction(act_desc)

        act_amt = QAction(self)
        act_amt.setShortcut(QKeySequence("Ctrl+J"))
        act_amt.triggered.connect(lambda: self.amount.setFocus())
        self.addAction(act_amt)

        act_date = QAction(self)
        act_date.setShortcut(QKeySequence("Ctrl+K"))
        act_date.triggered.connect(lambda: self.date.setFocus())
        self.addAction(act_date)

        act_add = QAction(self)
        act_add.setShortcut(QKeySequence("Ctrl+Enter"))
        act_add.triggered.connect(self.add_current_row)
        self.addAction(act_add)

        act_del = QAction(self)
        act_del.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        act_del.triggered.connect(self.delete_selected)
        self.addAction(act_del)

        act_val = QAction(self)
        act_val.setShortcut(QKeySequence("Ctrl+B"))
        act_val.triggered.connect(self.validate_balances)
        self.addAction(act_val)

        act_exp = QAction(self)
        act_exp.setShortcut(QKeySequence("Ctrl+E"))
        act_exp.triggered.connect(self.export_csv)
        self.addAction(act_exp)

        act_imp = QAction(self)
        act_imp.setShortcut(QKeySequence("Ctrl+I"))
        act_imp.triggered.connect(self.import_paste)
        self.addAction(act_imp)

    # ===== Events =====

    def eventFilter(self, obj, event):
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.table.closePersistentEditor(self.table.currentItem())
                return True
        return super().eventFilter(obj, event)

    def on_item_changed(self, item: QTableWidgetItem):
        if self._updating:
            return

        r, c = item.row(), item.column()
        keep_id = None
        it0 = self.table.item(r, 0)
        if it0:
            keep_id = it0.data(Qt.ItemDataRole.UserRole)

        # normalize date edits
        if c == 0:
            d = normalize_date(item.text())
            if d:
                self._updating = True
                item.setText(d)
                self._updating = False
            self.sort_by_date_if_enabled(keep_id)

        # normalize + color amount edits
        if c == 2:
            try:
                amt = money2(parse_decimal(item.text()))
                self._updating = True
                item.setText(f"{amt:.2f}")
                self._updating = False
                self.color_amount_item(item, amt)
            except Exception:
                pass

        if c == 1:
            self.learn_description(item.text())

        self.recompute_dynamic_closing()

    # ===== Core logic =====

    def add_current_row(self):
        d = normalize_date(self.date.text())
        if not d:
            self.set_status("Invalid date. Use yyyy/mm/dd (or 01/11/2025 and I’ll normalize).")
            self.date.setFocus()
            self.date.selectAll()
            return

        desc = norm_spaces(self.desc.text())
        if not desc:
            self.set_status("Description empty.")
            self.desc.setFocus()
            return

        try:
            amt = money2(parse_decimal(self.amount.text().strip()))
        except (InvalidOperation, ValueError):
            self.set_status("Invalid amount. Example: -123.45 or 1000 or 1,234.56")
            self.amount.setFocus()
            self.amount.selectAll()
            return

        row_id = self._next_row_id
        self._next_row_id += 1

        r = self.table.rowCount()
        self._updating = True
        self.table.insertRow(r)

        it_date = QTableWidgetItem(d)
        it_date.setData(Qt.ItemDataRole.UserRole, row_id)
        it_desc = QTableWidgetItem(desc)
        it_amt = QTableWidgetItem(f"{amt:.2f}")

        self.table.setItem(r, 0, it_date)
        self.table.setItem(r, 1, it_desc)
        self.table.setItem(r, 2, it_amt)
        self._updating = False

        self.color_amount_item(it_amt, amt)
        self.learn_description(desc)

        self.desc.clear()
        self.amount.clear()
        self.desc.setFocus()

        self.sort_by_date_if_enabled(row_id)
        self.recompute_dynamic_closing()
        self.set_status(f"Added. Total rows: {self.table.rowCount()}")

    def import_paste(self):
        text = self.paste.toPlainText()
        if not text.strip():
            self.set_status("Nothing to import.")
            return

        lines = [ln for ln in text.splitlines() if ln.strip()]
        ok, bad = 0, 0
        last_date = normalize_date(self.date.text()) if self.date.text().strip() else ""
        last_row_id = None

        self._updating = True
        for ln in lines:
            parsed = try_parse_line(ln)
            if not parsed:
                bad += 1
                continue
            d, desc, amt = parsed
            if not d and last_date:
                d = last_date
            if d:
                last_date = d

            row_id = self._next_row_id
            self._next_row_id += 1
            last_row_id = row_id

            r = self.table.rowCount()
            self.table.insertRow(r)

            it_date = QTableWidgetItem(d)
            it_date.setData(Qt.ItemDataRole.UserRole, row_id)
            it_desc = QTableWidgetItem(desc)
            it_amt = QTableWidgetItem(f"{amt:.2f}")

            self.table.setItem(r, 0, it_date)
            self.table.setItem(r, 1, it_desc)
            self.table.setItem(r, 2, it_amt)

            self.learn_description(desc)
            self.color_amount_item(it_amt, amt)
            ok += 1

        self._updating = False

        if last_date:
            self.date.setText(last_date)

        self.sort_by_date_if_enabled(last_row_id)
        self.recompute_dynamic_closing()
        self.set_status(f"Imported {ok}. Skipped {bad}. Total rows: {self.table.rowCount()}")

    def delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            self.set_status("No rows selected.")
            return
        self._updating = True
        for r in rows:
            self.table.removeRow(r)
        self._updating = False
        self.recompute_dynamic_closing()
        self.set_status(f"Deleted {len(rows)} rows. Total rows: {self.table.rowCount()}")

    def clear_table(self):
        self._updating = True
        self.table.setRowCount(0)
        self._updating = False
        self.recompute_dynamic_closing()
        self.set_status("Cleared table.")

    def get_rows(self):
        out = []
        for r in range(self.table.rowCount()):
            d = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ""
            desc = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            amt = self.table.item(r, 2).text().strip() if self.table.item(r, 2) else ""
            d2 = normalize_date(d) or d
            desc2 = norm_spaces(desc)
            try:
                amt2 = money2(parse_decimal(amt))
            except Exception:
                amt2 = Decimal("0.00")
            out.append((d2, desc2, amt2))
        return out

    def recompute_dynamic_closing(self):
        rows = self.get_rows()

        try:
            opening = money2(parse_decimal(self.opening.text()))
        except Exception:
            opening = Decimal("0.00")

        total = Decimal("0.00")
        for _, _, amt in rows:
            total += amt

        computed = money2(opening + total)
        self.dynamic_closing.setText(f"{computed:.2f}")

        target_txt = self.target_closing.text().strip()
        if not target_txt:
            self.set_lineedit_bg(self.target_closing, None)
            return

        try:
            target = money2(parse_decimal(target_txt))
        except Exception:
            self.set_lineedit_bg(self.target_closing, "#FFD7D7")
            return

        diff = money2(computed - target)
        if diff == Decimal("0.00"):
            self.set_lineedit_bg(self.target_closing, "#D7FFD7")
        else:
            self.set_lineedit_bg(self.target_closing, "#FFF1B8")

    def validate_balances(self):
        rows = self.get_rows()
        if not rows:
            self.set_status("No rows to validate.")
            return

        try:
            opening = money2(parse_decimal(self.opening.text()))
        except Exception:
            self.set_status("Opening balance invalid.")
            self.opening.setFocus()
            self.opening.selectAll()
            return

        try:
            target = money2(parse_decimal(self.target_closing.text()))
        except Exception:
            self.set_status("Target closing invalid.")
            self.target_closing.setFocus()
            self.target_closing.selectAll()
            return

        total = Decimal("0.00")
        for _, _, amt in rows:
            total += amt

        computed = money2(opening + total)
        diff = money2(computed - target)

        if diff == Decimal("0.00"):
            self.set_status(f"MATCH: Opening {opening:.2f} + Sum {money2(total):.2f} = Target {target:.2f}")
        else:
            self.set_status(f"MISMATCH: computed {computed:.2f} vs target {target:.2f} (diff {diff:.2f})")

    def export_csv(self):
        if self.table.rowCount() == 0:
            self.set_status("Nothing to export.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "transactions.csv", "CSV Files (*.csv)")
        if not path:
            return

        rows = self.get_rows()

        for i, (d, _, _) in enumerate(rows, start=1):
            if not normalize_date(d):
                QMessageBox.warning(self, "Export Error", f"Row {i} has invalid date: '{d}'. Fix it before exporting.")
                return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "description", "amount"])
                for d, desc, amt in rows:
                    d = normalize_date(d)
                    w.writerow([d, desc, f"{money2(amt):.2f}"])
            self.set_status(f"Exported {len(rows)} rows to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def save_session(self):
        rows = self.get_rows()
        data = {
            "opening": self.opening.text().strip(),
            "target_closing": self.target_closing.text().strip(),
            "current_date": self.date.text().strip(),
            "next_row_id": self._next_row_id,
            "rows": [(d, desc, str(money2(amt))) for (d, desc, amt) in rows],
        }
        path, _ = QFileDialog.getSaveFileName(self, "Save Session", "session.json", "JSON Files (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            LAST_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.set_status(f"Session saved to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def load_session(self, path=None, quiet=False):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Load Session", "", "JSON Files (*.json)")
            if not path:
                return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.opening.setText(data.get("opening", ""))
            self.target_closing.setText(data.get("target_closing", ""))
            self.date.setText(data.get("current_date", ""))

            self._next_row_id = int(data.get("next_row_id", 1))

            self._updating = True
            self.table.setRowCount(0)

            last_row_id = None
            for d, desc, amt in data.get("rows", []):
                d2 = normalize_date(d) or d
                desc2 = norm_spaces(desc)
                try:
                    amt2 = money2(parse_decimal(str(amt)))
                except Exception:
                    amt2 = Decimal("0.00")

                row_id = self._next_row_id
                self._next_row_id += 1
                last_row_id = row_id

                r = self.table.rowCount()
                self.table.insertRow(r)

                it_date = QTableWidgetItem(d2)
                it_date.setData(Qt.ItemDataRole.UserRole, row_id)
                it_desc = QTableWidgetItem(desc2)
                it_amt = QTableWidgetItem(f"{amt2:.2f}")

                self.table.setItem(r, 0, it_date)
                self.table.setItem(r, 1, it_desc)
                self.table.setItem(r, 2, it_amt)

                self.learn_description(desc2)
                self.color_amount_item(it_amt, amt2)

            self._updating = False

            self.sort_by_date_if_enabled(last_row_id)
            self.recompute_dynamic_closing()

            if not quiet:
                self.set_status(f"Loaded {self.table.rowCount()} rows from {path}")
        except Exception as e:
            if not quiet:
                QMessageBox.critical(self, "Load Failed", str(e))


def main():
    app = QApplication(sys.argv)
    w = FastEntry()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
