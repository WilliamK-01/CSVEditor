import sys
import json
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PyQt6.QtCore import Qt, QStringListModel, QEvent, QStandardPaths
from PyQt6.QtGui import QKeySequence, QAction, QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QFileDialog, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QCompleter,
    QCheckBox
)

from core import Transaction, norm_spaces, parse_decimal, money2, normalize_date, date_key, try_parse_line

APP_NAME = "Fast Bank Entry (PyQt6)"
APP_DIR = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or ".")
DICT_FILE = APP_DIR / "descriptions_dict.json"
LAST_FILE = APP_DIR / "last_session.json"


class FastEntry(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1240, 860)

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

        self.status = QLabel("Ready.")
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

        # ===== Search row (UI improvement) =====
        search = QHBoxLayout()
        main.addLayout(search)
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("Filter table by date/description/amount (Ctrl+F)")
        self.filter_text.textChanged.connect(self.apply_filter)
        self.rows_label = QLabel("Rows: 0")
        search.addWidget(QLabel("Quick Filter:"))
        search.addWidget(self.filter_text, 1)
        search.addWidget(self.rows_label)

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

    def insert_transaction_row(self, tx: Transaction, row_id: int):
        r = self.table.rowCount()
        self.table.insertRow(r)
        it_date = QTableWidgetItem(tx.date)
        it_date.setData(Qt.ItemDataRole.UserRole, row_id)
        it_desc = QTableWidgetItem(tx.description)
        it_amt = QTableWidgetItem(f"{tx.amount:.2f}")
        self.table.setItem(r, 0, it_date)
        self.table.setItem(r, 1, it_desc)
        self.table.setItem(r, 2, it_amt)
        self.color_amount_item(it_amt, tx.amount)

    def sort_by_date_if_enabled(self, keep_row_id: int | None):
        if not self.auto_sort.isChecked():
            if keep_row_id is not None:
                self.trail_to_row_id(keep_row_id)
            return

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
            d_norm = normalize_date(d_raw) or d_raw
            try:
                amt = money2(parse_decimal(amt_txt))
            except (InvalidOperation, ValueError):
                amt = Decimal("0.00")
            self.insert_transaction_row(Transaction(d_norm, norm_spaces(desc), amt), row_id)

        self._updating = False
        self.apply_filter()
        if keep_row_id is not None:
            self.trail_to_row_id(keep_row_id)

    def apply_filter(self):
        needle = self.filter_text.text().strip().lower()
        visible = 0
        for r in range(self.table.rowCount()):
            hay = " | ".join(
                (self.table.item(r, c).text().lower() if self.table.item(r, c) else "")
                for c in range(3)
            )
            match = (not needle) or (needle in hay)
            self.table.setRowHidden(r, not match)
            if match:
                visible += 1
        self.rows_label.setText(f"Rows: {visible}/{self.table.rowCount()}")

    # ===== Color coding =====

    def color_amount_item(self, item: QTableWidgetItem, amt: Decimal):
        if amt > 0:
            item.setForeground(QBrush(QColor("#00C853")))
        elif amt < 0:
            item.setForeground(QBrush(QColor("#D97706")))
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
            except (json.JSONDecodeError, OSError):
                self.descriptions = []
        else:
            self.descriptions = []

    def save_dictionary(self):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            DICT_FILE.write_text(json.dumps(self.descriptions, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            self.set_status("Warning: could not save autocomplete dictionary.")

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

        act_filter = QAction(self)
        act_filter.setShortcut(QKeySequence("Ctrl+F"))
        act_filter.triggered.connect(lambda: self.filter_text.setFocus())
        self.addAction(act_filter)

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

        if c == 0:
            d = normalize_date(item.text())
            if d:
                self._updating = True
                item.setText(d)
                self._updating = False
            self.sort_by_date_if_enabled(keep_id)

        if c == 2:
            try:
                amt = money2(parse_decimal(item.text()))
                self._updating = True
                item.setText(f"{amt:.2f}")
                self._updating = False
                self.color_amount_item(item, amt)
            except (InvalidOperation, ValueError):
                item.setBackground(QBrush(QColor("#FFD7D7")))
                self.set_status(f"Invalid amount at row {r + 1}. Fix before export/validate.")
                return
            item.setBackground(QBrush(QColor("#FFFFFF")))

        if c == 1:
            self.learn_description(item.text())

        self.recompute_dynamic_closing()
        self.apply_filter()

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

        self._updating = True
        self.insert_transaction_row(Transaction(d, desc, amt), row_id)
        self._updating = False

        self.learn_description(desc)

        self.desc.clear()
        self.amount.clear()
        self.desc.setFocus()

        self.sort_by_date_if_enabled(row_id)
        self.recompute_dynamic_closing()
        self.apply_filter()
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
            d = parsed.date or last_date
            if not d:
                bad += 1
                continue
            last_date = d
            tx = Transaction(d, parsed.description, parsed.amount)

            row_id = self._next_row_id
            self._next_row_id += 1
            last_row_id = row_id

            self.insert_transaction_row(tx, row_id)
            self.learn_description(tx.description)
            ok += 1

        self._updating = False

        if last_date:
            self.date.setText(last_date)

        self.sort_by_date_if_enabled(last_row_id)
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status(f"Imported {ok}. Skipped {bad}. Total rows: {self.table.rowCount()}")

    def delete_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            self.set_status("No rows selected.")
            return
        if QMessageBox.question(self, "Confirm Delete", f"Delete {len(rows)} selected row(s)?") != QMessageBox.StandardButton.Yes:
            return

        self._updating = True
        for r in rows:
            self.table.removeRow(r)
        self._updating = False
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status(f"Deleted {len(rows)} rows. Total rows: {self.table.rowCount()}")

    def clear_table(self):
        if self.table.rowCount() == 0:
            return
        if QMessageBox.question(self, "Confirm Clear", "Clear all rows from table?") != QMessageBox.StandardButton.Yes:
            return

        self._updating = True
        self.table.setRowCount(0)
        self._updating = False
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status("Cleared table.")

    def get_rows(self, strict: bool = False):
        out = []
        errors = []
        for r in range(self.table.rowCount()):
            d = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ""
            desc = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            amt_txt = self.table.item(r, 2).text().strip() if self.table.item(r, 2) else ""

            d2 = normalize_date(d)
            desc2 = norm_spaces(desc)
            amt2 = None
            try:
                amt2 = money2(parse_decimal(amt_txt))
            except (InvalidOperation, ValueError):
                pass

            if not d2:
                errors.append(f"Row {r + 1}: invalid date '{d}'.")
            if amt2 is None:
                errors.append(f"Row {r + 1}: invalid amount '{amt_txt}'.")

            if not strict:
                if not d2:
                    d2 = d
                if amt2 is None:
                    amt2 = Decimal("0.00")
            if d2 and amt2 is not None:
                out.append(Transaction(d2, desc2, amt2))

        return out, errors

    def recompute_dynamic_closing(self):
        rows, _ = self.get_rows(strict=False)

        try:
            opening = money2(parse_decimal(self.opening.text()))
        except (InvalidOperation, ValueError):
            opening = Decimal("0.00")

        total = sum((row.amount for row in rows), Decimal("0.00"))

        computed = money2(opening + total)
        self.dynamic_closing.setText(f"{computed:.2f}")

        target_txt = self.target_closing.text().strip()
        if not target_txt:
            self.set_lineedit_bg(self.target_closing, None)
            return

        try:
            target = money2(parse_decimal(target_txt))
        except (InvalidOperation, ValueError):
            self.set_lineedit_bg(self.target_closing, "#FFD7D7")
            return

        diff = money2(computed - target)
        if diff == Decimal("0.00"):
            self.set_lineedit_bg(self.target_closing, "#D7FFD7")
        else:
            self.set_lineedit_bg(self.target_closing, "#FFF1B8")

    def validate_balances(self):
        rows, row_errors = self.get_rows(strict=True)
        if row_errors:
            self.set_status("Validation blocked: " + row_errors[0])
            return
        if not rows:
            self.set_status("No rows to validate.")
            return

        try:
            opening = money2(parse_decimal(self.opening.text()))
        except (InvalidOperation, ValueError):
            self.set_status("Opening balance invalid.")
            self.opening.setFocus()
            self.opening.selectAll()
            return

        try:
            target = money2(parse_decimal(self.target_closing.text()))
        except (InvalidOperation, ValueError):
            self.set_status("Target closing invalid.")
            self.target_closing.setFocus()
            self.target_closing.selectAll()
            return

        total = sum((row.amount for row in rows), Decimal("0.00"))
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

        rows, row_errors = self.get_rows(strict=True)
        if row_errors:
            QMessageBox.warning(self, "Export Error", row_errors[0])
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "transactions.csv", "CSV Files (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "description", "amount"])
                for row in rows:
                    w.writerow([row.date, row.description, f"{money2(row.amount):.2f}"])
            self.set_status(f"Exported {len(rows)} rows to {path}")
        except OSError as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def save_session(self):
        rows, _ = self.get_rows(strict=False)
        data = {
            "opening": self.opening.text().strip(),
            "target_closing": self.target_closing.text().strip(),
            "current_date": self.date.text().strip(),
            "next_row_id": self._next_row_id,
            "rows": [
                {
                    "id": (self.table.item(i, 0).data(Qt.ItemDataRole.UserRole) if self.table.item(i, 0) else i + 1),
                    "date": row.date,
                    "description": row.description,
                    "amount": str(money2(row.amount)),
                }
                for i, row in enumerate(rows)
            ],
        }
        path, _ = QFileDialog.getSaveFileName(self, "Save Session", "session.json", "JSON Files (*.json)")
        if not path:
            return
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            Path(path).write_text(payload, encoding="utf-8")
            LAST_FILE.write_text(payload, encoding="utf-8")
            self.set_status(f"Session saved to {path}")
        except OSError as e:
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

            self._updating = True
            self.table.setRowCount(0)

            max_id = 0
            last_row_id = None
            for row in data.get("rows", []):
                if isinstance(row, dict):
                    raw_id = int(row.get("id", 0) or 0)
                    d = row.get("date", "")
                    desc = row.get("description", "")
                    amt = row.get("amount", "0")
                else:
                    raw_id = 0
                    d, desc, amt = row

                d2 = normalize_date(d) or d
                desc2 = norm_spaces(desc)
                try:
                    amt2 = money2(parse_decimal(str(amt)))
                except (InvalidOperation, ValueError):
                    amt2 = Decimal("0.00")

                row_id = raw_id if raw_id > 0 else (max_id + 1)
                max_id = max(max_id, row_id)
                last_row_id = row_id
                self.insert_transaction_row(Transaction(d2, desc2, amt2), row_id)
                self.learn_description(desc2)

            file_next = int(data.get("next_row_id", max_id + 1) or (max_id + 1))
            self._next_row_id = max(file_next, max_id + 1)

            self._updating = False

            self.sort_by_date_if_enabled(last_row_id)
            self.recompute_dynamic_closing()
            self.apply_filter()

            if not quiet:
                self.set_status(f"Loaded {self.table.rowCount()} rows from {path}")
        except (json.JSONDecodeError, OSError, ValueError) as e:
            if not quiet:
                QMessageBox.critical(self, "Load Failed", str(e))


def main():
    app = QApplication(sys.argv)
    w = FastEntry()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
