import sys
import json
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PyQt6.QtCore import Qt, QStringListModel, QEvent, QStandardPaths
from PyQt6.QtGui import QKeySequence, QAction, QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QCompleter,
    QCheckBox,
    QComboBox,
)

from core import Transaction, norm_spaces, parse_decimal, money2, normalize_date, date_key, try_parse_line

APP_NAME = "Fast Bank Entry (PyQt6)"
APP_DIR = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or ".")
DICT_FILE = APP_DIR / "descriptions_dict.json"
LAST_FILE = APP_DIR / "last_session.json"


class FastEntry(QMainWindow):
    COL_DATE = 0
    COL_DESC = 1
    COL_CATEGORY = 2
    COL_AMOUNT = 3
    COL_RUNNING = 4

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 920)

        self._updating = False
        self._next_row_id = 1
        self._undo_stack = []
        self._redo_stack = []

        self.descriptions = []
        self.load_dictionary()

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        top = QGridLayout()
        main.addLayout(top)

        self.opening = QLineEdit()
        self.opening.setPlaceholderText("Opening balance (e.g. 1234.56)")

        self.target_closing = QLineEdit()
        self.target_closing.setPlaceholderText("Fixed Closing balance target (statement)")

        self.dynamic_closing = QLineEdit()
        self.dynamic_closing.setReadOnly(True)

        self.auto_sort = QCheckBox("Auto-sort by date")
        self.auto_sort.setChecked(True)

        self.display_fmt = QComboBox()
        self.display_fmt.addItems(["YYYY/MM/DD", "DD/MM/YYYY"])
        self.display_fmt.currentTextChanged.connect(self.refresh_date_display)

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
        top.addWidget(QLabel("Date Display:"), 0, 6)
        top.addWidget(self.display_fmt, 0, 7)
        top.addWidget(self.auto_sort, 0, 8)
        top.addWidget(self.btn_validate, 0, 9)
        top.addWidget(self.status, 1, 0, 1, 10)

        self.opening.textChanged.connect(self.recompute_dynamic_closing)
        self.target_closing.textChanged.connect(self.recompute_dynamic_closing)
        self.auto_sort.stateChanged.connect(lambda: self.sort_by_date_if_enabled(None))

        entry = QHBoxLayout()
        main.addLayout(entry)

        self.date = QLineEdit()
        self.date.setPlaceholderText("Date")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Description")
        self.category = QLineEdit()
        self.category.setPlaceholderText("Category (optional)")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Amount")

        self.btn_add = QPushButton("Add (Enter)")
        self.btn_add.clicked.connect(self.add_current_row)

        entry.addWidget(QLabel("Date:"))
        entry.addWidget(self.date, 2)
        entry.addWidget(QLabel("Description:"))
        entry.addWidget(self.desc, 4)
        entry.addWidget(QLabel("Category:"))
        entry.addWidget(self.category, 3)
        entry.addWidget(QLabel("Amount:"))
        entry.addWidget(self.amount, 2)
        entry.addWidget(self.btn_add, 1)

        search = QGridLayout()
        main.addLayout(search)
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("Text filter (Ctrl+F)")
        self.filter_text.textChanged.connect(self.apply_filter)
        self.filter_from = QLineEdit()
        self.filter_from.setPlaceholderText("From date")
        self.filter_from.textChanged.connect(self.apply_filter)
        self.filter_to = QLineEdit()
        self.filter_to.setPlaceholderText("To date")
        self.filter_to.textChanged.connect(self.apply_filter)
        self.filter_min_amt = QLineEdit()
        self.filter_min_amt.setPlaceholderText("Min amount")
        self.filter_min_amt.textChanged.connect(self.apply_filter)
        self.filter_max_amt = QLineEdit()
        self.filter_max_amt.setPlaceholderText("Max amount")
        self.filter_max_amt.textChanged.connect(self.apply_filter)
        self.only_credits = QCheckBox("Only credits")
        self.only_credits.stateChanged.connect(self.apply_filter)
        self.only_debits = QCheckBox("Only debits")
        self.only_debits.stateChanged.connect(self.apply_filter)
        self.btn_clear_filter = QPushButton("Clear Filter")
        self.btn_clear_filter.clicked.connect(self.clear_filters)
        self.rows_label = QLabel("Rows: 0")

        search.addWidget(QLabel("Quick Filter:"), 0, 0)
        search.addWidget(self.filter_text, 0, 1, 1, 3)
        search.addWidget(QLabel("Date range:"), 0, 4)
        search.addWidget(self.filter_from, 0, 5)
        search.addWidget(self.filter_to, 0, 6)
        search.addWidget(QLabel("Amount range:"), 1, 0)
        search.addWidget(self.filter_min_amt, 1, 1)
        search.addWidget(self.filter_max_amt, 1, 2)
        search.addWidget(self.only_credits, 1, 3)
        search.addWidget(self.only_debits, 1, 4)
        search.addWidget(self.btn_clear_filter, 1, 5)
        search.addWidget(self.rows_label, 1, 6)

        self.completer_model = QStringListModel(self.descriptions)
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.desc.setCompleter(self.completer)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["date", "description", "category", "amount", "running_balance"])
        self.table.horizontalHeader().setSectionResizeMode(self.COL_DATE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_DESC, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_AMOUNT, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.COL_RUNNING, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.installEventFilter(self)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.itemSelectionChanged.connect(self.populate_editor_from_selection)
        main.addWidget(self.table, 6)

        editor = QHBoxLayout()
        main.addLayout(editor)
        self.edit_date = QLineEdit()
        self.edit_desc = QLineEdit()
        self.edit_category = QLineEdit()
        self.edit_amount = QLineEdit()
        self.btn_apply_edit = QPushButton("Apply Selected Row Edit")
        self.btn_apply_edit.clicked.connect(self.apply_selected_edit)
        editor.addWidget(QLabel("Edit Date:"))
        editor.addWidget(self.edit_date, 2)
        editor.addWidget(QLabel("Edit Description:"))
        editor.addWidget(self.edit_desc, 4)
        editor.addWidget(QLabel("Edit Category:"))
        editor.addWidget(self.edit_category, 3)
        editor.addWidget(QLabel("Edit Amount:"))
        editor.addWidget(self.edit_amount, 2)
        editor.addWidget(self.btn_apply_edit, 2)

        paste_row = QHBoxLayout()
        main.addLayout(paste_row)

        self.paste = QTextEdit()
        self.paste.setPlaceholderText("Paste CSV/tab/space separated lines here.")

        btns = QVBoxLayout()
        self.btn_import = QPushButton("Import Paste (Ctrl+I)")
        self.btn_import.clicked.connect(self.import_paste)

        self.export_filtered = QCheckBox("Export filtered rows only")

        self.btn_export = QPushButton("Export CSV… (Ctrl+E)")
        self.btn_export.clicked.connect(self.export_csv)

        self.btn_save = QPushButton("Save Session")
        self.btn_save.clicked.connect(self.save_session)

        self.btn_load = QPushButton("Load Session")
        self.btn_load.clicked.connect(self.load_session)

        self.btn_del = QPushButton("Delete Selected (Del)")
        self.btn_del.clicked.connect(self.delete_selected)

        self.btn_dup = QPushButton("Duplicate Selected (Ctrl+D)")
        self.btn_dup.clicked.connect(self.duplicate_selected)

        self.btn_clear = QPushButton("Clear Table")
        self.btn_clear.clicked.connect(self.clear_table)

        self.btn_show_validation = QPushButton("Show Validation Details")
        self.btn_show_validation.clicked.connect(self.show_validation_details)

        self.validation_text = QTextEdit()
        self.validation_text.setReadOnly(True)
        self.validation_text.setPlaceholderText("Validation details appear here")

        btns.addWidget(self.btn_import)
        btns.addWidget(self.export_filtered)
        btns.addWidget(self.btn_export)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_load)
        btns.addWidget(self.btn_del)
        btns.addWidget(self.btn_dup)
        btns.addWidget(self.btn_clear)
        btns.addWidget(self.btn_show_validation)
        btns.addStretch(1)

        paste_row.addWidget(self.paste, 4)
        paste_row.addWidget(self.validation_text, 3)
        paste_row.addLayout(btns, 1)

        self.make_shortcuts()
        self.date.returnPressed.connect(lambda: self.desc.setFocus())
        self.desc.returnPressed.connect(lambda: self.category.setFocus())
        self.category.returnPressed.connect(lambda: self.amount.setFocus())
        self.amount.returnPressed.connect(self.add_current_row)

        if LAST_FILE.exists():
            self.load_session(path=str(LAST_FILE), quiet=True)

        self.recompute_dynamic_closing()
        self.push_undo_snapshot()

    def set_status(self, msg: str):
        self.status.setText(msg)

    def set_lineedit_bg(self, le: QLineEdit, color_hex: str | None):
        le.setStyleSheet("" if not color_hex else f"QLineEdit {{ background-color: {color_hex}; }}")

    def canonical_to_display_date(self, d: str) -> str:
        if self.display_fmt.currentText() != "DD/MM/YYYY":
            return d
        parts = d.split("/")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return d

    def display_to_canonical_date(self, d: str) -> str:
        d = d.strip()
        if self.display_fmt.currentText() == "DD/MM/YYYY" and d.count("/") == 2:
            p = d.split("/")
            if len(p[0]) <= 2 and len(p[2]) == 4:
                d = f"{p[2]}/{p[1]}/{p[0]}"
        return normalize_date(d)

    def refresh_date_display(self):
        self._updating = True
        for r in range(self.table.rowCount()):
            it = self.table.item(r, self.COL_DATE)
            if it:
                canon = it.data(Qt.ItemDataRole.UserRole + 1) or normalize_date(it.text())
                if canon:
                    it.setData(Qt.ItemDataRole.UserRole + 1, canon)
                    it.setText(self.canonical_to_display_date(canon))
        self._updating = False
        self.apply_filter()

    def trail_to_row_id(self, row_id: int | None):
        if row_id is None:
            return
        for r in range(self.table.rowCount()):
            it = self.table.item(r, self.COL_DATE)
            if it and it.data(Qt.ItemDataRole.UserRole) == row_id:
                self.table.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                self.table.setCurrentCell(r, self.COL_DESC)
                self.table.selectRow(r)
                return

    def push_undo_snapshot(self):
        self._undo_stack.append(self.capture_state())
        if len(self._undo_stack) > 100:
            self._undo_stack = self._undo_stack[-100:]
        self._redo_stack.clear()

    def capture_state(self):
        rows = []
        for r in range(self.table.rowCount()):
            it_date = self.table.item(r, self.COL_DATE)
            it_desc = self.table.item(r, self.COL_DESC)
            it_cat = self.table.item(r, self.COL_CATEGORY)
            it_amt = self.table.item(r, self.COL_AMOUNT)
            rows.append(
                {
                    "id": it_date.data(Qt.ItemDataRole.UserRole) if it_date else r + 1,
                    "date": it_date.data(Qt.ItemDataRole.UserRole + 1) if it_date else "",
                    "description": it_desc.text() if it_desc else "",
                    "category": it_cat.text() if it_cat else "",
                    "amount": it_amt.text() if it_amt else "0.00",
                }
            )
        return {
            "opening": self.opening.text(),
            "target": self.target_closing.text(),
            "current_date": self.date.text(),
            "next_row_id": self._next_row_id,
            "rows": rows,
        }

    def restore_state(self, state):
        self._updating = True
        self.opening.setText(state.get("opening", ""))
        self.target_closing.setText(state.get("target", ""))
        self.date.setText(state.get("current_date", ""))
        self._next_row_id = int(state.get("next_row_id", 1) or 1)
        self.table.setRowCount(0)
        for row in state.get("rows", []):
            self.insert_row(
                row.get("date", ""),
                row.get("description", ""),
                row.get("category", ""),
                row.get("amount", "0.00"),
                int(row.get("id", 0) or 0),
            )
        self._updating = False
        self.sort_by_date_if_enabled(None)
        self.recompute_dynamic_closing()
        self.apply_filter()

    def undo(self):
        if len(self._undo_stack) < 2:
            self.set_status("Nothing to undo.")
            return
        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        self.restore_state(self._undo_stack[-1])
        self.set_status("Undo applied.")

    def redo(self):
        if not self._redo_stack:
            self.set_status("Nothing to redo.")
            return
        nxt = self._redo_stack.pop()
        self._undo_stack.append(nxt)
        self.restore_state(nxt)
        self.set_status("Redo applied.")

    def insert_row(self, d: str, desc: str, category: str, amt_txt: str, row_id: int):
        r = self.table.rowCount()
        self.table.insertRow(r)
        canonical_date = normalize_date(d) or d
        display_date = self.canonical_to_display_date(canonical_date)
        it_date = QTableWidgetItem(display_date)
        it_date.setData(Qt.ItemDataRole.UserRole, row_id)
        it_date.setData(Qt.ItemDataRole.UserRole + 1, canonical_date)
        it_desc = QTableWidgetItem(norm_spaces(desc))
        it_cat = QTableWidgetItem(norm_spaces(category))
        try:
            amt = money2(parse_decimal(str(amt_txt)))
        except (InvalidOperation, ValueError):
            amt = Decimal("0.00")
        it_amt = QTableWidgetItem(f"{amt:.2f}")
        it_run = QTableWidgetItem("0.00")
        it_run.setFlags(it_run.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(r, self.COL_DATE, it_date)
        self.table.setItem(r, self.COL_DESC, it_desc)
        self.table.setItem(r, self.COL_CATEGORY, it_cat)
        self.table.setItem(r, self.COL_AMOUNT, it_amt)
        self.table.setItem(r, self.COL_RUNNING, it_run)
        self.color_amount_item(it_amt, amt)

    def sort_by_date_if_enabled(self, keep_row_id: int | None):
        if not self.auto_sort.isChecked():
            self.update_running_balances()
            if keep_row_id is not None:
                self.trail_to_row_id(keep_row_id)
            return
        rows = []
        for r in range(self.table.rowCount()):
            d = self.table.item(r, self.COL_DATE).data(Qt.ItemDataRole.UserRole + 1)
            desc = self.table.item(r, self.COL_DESC).text()
            cat = self.table.item(r, self.COL_CATEGORY).text()
            amt = self.table.item(r, self.COL_AMOUNT).text()
            row_id = self.table.item(r, self.COL_DATE).data(Qt.ItemDataRole.UserRole)
            rows.append((date_key(d), d, desc, cat, amt, row_id))
        rows.sort(key=lambda x: (x[0], x[5] if x[5] is not None else 10**12))
        self._updating = True
        self.table.setRowCount(0)
        for _, d, desc, cat, amt, row_id in rows:
            self.insert_row(d, desc, cat, amt, row_id)
        self._updating = False
        self.update_running_balances()
        self.apply_filter()
        if keep_row_id is not None:
            self.trail_to_row_id(keep_row_id)

    def update_running_balances(self):
        try:
            opening = money2(parse_decimal(self.opening.text()))
        except (InvalidOperation, ValueError):
            opening = Decimal("0.00")
        running = opening
        self._updating = True
        for r in range(self.table.rowCount()):
            try:
                amt = money2(parse_decimal(self.table.item(r, self.COL_AMOUNT).text()))
            except (InvalidOperation, ValueError):
                amt = Decimal("0.00")
            running = money2(running + amt)
            self.table.item(r, self.COL_RUNNING).setText(f"{running:.2f}")
        self._updating = False

    def clear_filters(self):
        self.filter_text.clear()
        self.filter_from.clear()
        self.filter_to.clear()
        self.filter_min_amt.clear()
        self.filter_max_amt.clear()
        self.only_credits.setChecked(False)
        self.only_debits.setChecked(False)
        self.apply_filter()

    def apply_filter(self):
        needle = self.filter_text.text().strip().lower()
        date_from = self.display_to_canonical_date(self.filter_from.text()) if self.filter_from.text().strip() else ""
        date_to = self.display_to_canonical_date(self.filter_to.text()) if self.filter_to.text().strip() else ""
        min_amt = None
        max_amt = None
        try:
            if self.filter_min_amt.text().strip():
                min_amt = money2(parse_decimal(self.filter_min_amt.text()))
        except (InvalidOperation, ValueError):
            pass
        try:
            if self.filter_max_amt.text().strip():
                max_amt = money2(parse_decimal(self.filter_max_amt.text()))
        except (InvalidOperation, ValueError):
            pass

        visible = 0
        for r in range(self.table.rowCount()):
            date_item = self.table.item(r, self.COL_DATE)
            desc_item = self.table.item(r, self.COL_DESC)
            cat_item = self.table.item(r, self.COL_CATEGORY)
            amt_item = self.table.item(r, self.COL_AMOUNT)
            canon = date_item.data(Qt.ItemDataRole.UserRole + 1) if date_item else ""
            try:
                amt = money2(parse_decimal(amt_item.text() if amt_item else "0"))
            except (InvalidOperation, ValueError):
                amt = Decimal("0.00")

            hay = " | ".join([
                (date_item.text().lower() if date_item else ""),
                (desc_item.text().lower() if desc_item else ""),
                (cat_item.text().lower() if cat_item else ""),
                (amt_item.text().lower() if amt_item else ""),
            ])

            match = (not needle) or (needle in hay)
            if date_from and canon:
                match = match and canon >= date_from
            if date_to and canon:
                match = match and canon <= date_to
            if min_amt is not None:
                match = match and amt >= min_amt
            if max_amt is not None:
                match = match and amt <= max_amt
            if self.only_credits.isChecked() and amt <= 0:
                match = False
            if self.only_debits.isChecked() and amt >= 0:
                match = False

            self.table.setRowHidden(r, not match)
            if match:
                visible += 1

        self.rows_label.setText(f"Rows: {visible}/{self.table.rowCount()}")

    def color_amount_item(self, item: QTableWidgetItem, amt: Decimal):
        if amt > 0:
            item.setForeground(QBrush(QColor("#00C853")))
        elif amt < 0:
            item.setForeground(QBrush(QColor("#D97706")))
        else:
            item.setForeground(QBrush(QColor("#000000")))

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
        if desc and desc not in self.descriptions:
            self.descriptions.append(desc)
            self.descriptions = sorted(set(self.descriptions), key=lambda s: s.lower())
            self.refresh_completer()
            self.save_dictionary()

    def make_shortcuts(self):
        mapping = {
            "Ctrl+L": lambda: self.desc.setFocus(),
            "Ctrl+J": lambda: self.amount.setFocus(),
            "Ctrl+K": lambda: self.date.setFocus(),
            "Ctrl+F": lambda: self.filter_text.setFocus(),
            "Ctrl+Enter": self.add_current_row,
            "Ctrl+B": self.validate_balances,
            "Ctrl+E": self.export_csv,
            "Ctrl+I": self.import_paste,
            "Ctrl+Z": self.undo,
            "Ctrl+Y": self.redo,
            "Ctrl+D": self.duplicate_selected,
            "Alt+Up": self.move_selected_up,
            "Alt+Down": self.move_selected_down,
        }
        for key, fn in mapping.items():
            act = QAction(self)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(fn)
            self.addAction(act)

        act_del = QAction(self)
        act_del.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        act_del.triggered.connect(self.delete_selected)
        self.addAction(act_del)

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
        keep_id = self.table.item(r, self.COL_DATE).data(Qt.ItemDataRole.UserRole)

        if c == self.COL_DATE:
            d = self.display_to_canonical_date(item.text())
            if d:
                self._updating = True
                item.setData(Qt.ItemDataRole.UserRole + 1, d)
                item.setText(self.canonical_to_display_date(d))
                self._updating = False
            self.sort_by_date_if_enabled(keep_id)

        if c == self.COL_AMOUNT:
            try:
                amt = money2(parse_decimal(item.text()))
                self._updating = True
                item.setText(f"{amt:.2f}")
                self._updating = False
                self.color_amount_item(item, amt)
                item.setBackground(QBrush(QColor("#FFFFFF")))
            except (InvalidOperation, ValueError):
                item.setBackground(QBrush(QColor("#FFD7D7")))
                self.set_status(f"Invalid amount at row {r + 1}.")
                return

        if c == self.COL_DESC:
            self.learn_description(item.text())

        self.update_running_balances()
        self.recompute_dynamic_closing()
        self.apply_filter()

    def is_duplicate(self, d: str, desc: str, category: str, amt: Decimal) -> bool:
        desc = norm_spaces(desc).lower()
        category = norm_spaces(category).lower()
        for r in range(self.table.rowCount()):
            row_d = self.table.item(r, self.COL_DATE).data(Qt.ItemDataRole.UserRole + 1)
            row_desc = norm_spaces(self.table.item(r, self.COL_DESC).text()).lower()
            row_cat = norm_spaces(self.table.item(r, self.COL_CATEGORY).text()).lower()
            try:
                row_amt = money2(parse_decimal(self.table.item(r, self.COL_AMOUNT).text()))
            except (InvalidOperation, ValueError):
                row_amt = Decimal("0.00")
            if row_d == d and row_desc == desc and row_cat == category and row_amt == amt:
                return True
        return False

    def add_current_row(self):
        d = self.display_to_canonical_date(self.date.text())
        if not d:
            self.set_status("Invalid date.")
            self.date.setFocus()
            self.date.selectAll()
            return
        desc = norm_spaces(self.desc.text())
        if not desc:
            self.set_status("Description empty.")
            self.desc.setFocus()
            return
        category = norm_spaces(self.category.text())
        try:
            amt = money2(parse_decimal(self.amount.text().strip()))
        except (InvalidOperation, ValueError):
            self.set_status("Invalid amount.")
            self.amount.setFocus()
            self.amount.selectAll()
            return

        if self.is_duplicate(d, desc, category, amt):
            if QMessageBox.question(self, "Duplicate Detected", "A matching row already exists. Add anyway?") != QMessageBox.StandardButton.Yes:
                return

        self.push_undo_snapshot()
        row_id = self._next_row_id
        self._next_row_id += 1
        self._updating = True
        self.insert_row(d, desc, category, f"{amt:.2f}", row_id)
        self._updating = False
        self.learn_description(desc)

        self.desc.clear()
        self.category.clear()
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

        preview = []
        skipped = 0
        last_date = self.display_to_canonical_date(self.date.text()) if self.date.text().strip() else ""
        for ln in [ln for ln in text.splitlines() if ln.strip()]:
            parsed = try_parse_line(ln)
            if not parsed:
                skipped += 1
                continue
            d = parsed.date or last_date
            if not d:
                skipped += 1
                continue
            last_date = d
            preview.append((d, parsed.description, "", parsed.amount))

        if not preview:
            self.set_status(f"No valid lines found. Skipped {skipped}.")
            return

        sample = "\n".join([f"{d}, {desc}, {amt:.2f}" for d, desc, _, amt in preview[:8]])
        msg = f"Import {len(preview)} row(s)? Skipped {skipped}.\n\nPreview:\n{sample}"
        if QMessageBox.question(self, "Import Preview", msg) != QMessageBox.StandardButton.Yes:
            return

        self.push_undo_snapshot()
        ok = 0
        dup = 0
        last_row_id = None
        self._updating = True
        for d, desc, category, amt in preview:
            if self.is_duplicate(d, desc, category, amt):
                dup += 1
                continue
            row_id = self._next_row_id
            self._next_row_id += 1
            last_row_id = row_id
            self.insert_row(d, desc, category, str(amt), row_id)
            self.learn_description(desc)
            ok += 1
        self._updating = False

        if last_date:
            self.date.setText(self.canonical_to_display_date(last_date))

        self.sort_by_date_if_enabled(last_row_id)
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status(f"Imported {ok}. Duplicates skipped {dup}. Parse skipped {skipped}.")

    def selected_rows_desc(self):
        return sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)

    def delete_selected(self):
        rows = self.selected_rows_desc()
        if not rows:
            self.set_status("No rows selected.")
            return
        if QMessageBox.question(self, "Confirm Delete", f"Delete {len(rows)} selected row(s)?") != QMessageBox.StandardButton.Yes:
            return
        self.push_undo_snapshot()
        self._updating = True
        for r in rows:
            self.table.removeRow(r)
        self._updating = False
        self.update_running_balances()
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status(f"Deleted {len(rows)} rows.")

    def duplicate_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if not rows:
            self.set_status("No rows selected.")
            return
        self.push_undo_snapshot()
        self._updating = True
        for r in rows:
            d = self.table.item(r, self.COL_DATE).data(Qt.ItemDataRole.UserRole + 1)
            desc = self.table.item(r, self.COL_DESC).text()
            cat = self.table.item(r, self.COL_CATEGORY).text()
            amt = self.table.item(r, self.COL_AMOUNT).text()
            row_id = self._next_row_id
            self._next_row_id += 1
            self.insert_row(d, desc, cat, amt, row_id)
        self._updating = False
        self.sort_by_date_if_enabled(None)
        self.set_status(f"Duplicated {len(rows)} row(s).")

    def move_selected(self, delta: int):
        if self.auto_sort.isChecked():
            self.set_status("Disable auto-sort to move rows manually.")
            return
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if len(rows) != 1:
            self.set_status("Select exactly one row to move.")
            return
        r = rows[0]
        new_r = r + delta
        if new_r < 0 or new_r >= self.table.rowCount():
            return
        self.push_undo_snapshot()
        vals = [self.table.item(r, c).clone() for c in range(self.table.columnCount())]
        vals2 = [self.table.item(new_r, c).clone() for c in range(self.table.columnCount())]
        self._updating = True
        for c in range(self.table.columnCount()):
            self.table.setItem(r, c, vals2[c])
            self.table.setItem(new_r, c, vals[c])
        self._updating = False
        self.table.selectRow(new_r)
        self.update_running_balances()
        self.recompute_dynamic_closing()
        self.apply_filter()

    def move_selected_up(self):
        self.move_selected(-1)

    def move_selected_down(self):
        self.move_selected(1)

    def clear_table(self):
        if self.table.rowCount() == 0:
            return
        if QMessageBox.question(self, "Confirm Clear", "Clear all rows from table?") != QMessageBox.StandardButton.Yes:
            return
        self.push_undo_snapshot()
        self._updating = True
        self.table.setRowCount(0)
        self._updating = False
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status("Cleared table.")

    def get_rows(self, strict: bool = False, visible_only: bool = False):
        out = []
        errors = []
        for r in range(self.table.rowCount()):
            if visible_only and self.table.isRowHidden(r):
                continue
            d = self.table.item(r, self.COL_DATE).data(Qt.ItemDataRole.UserRole + 1)
            desc = self.table.item(r, self.COL_DESC).text().strip()
            cat = self.table.item(r, self.COL_CATEGORY).text().strip()
            amt_txt = self.table.item(r, self.COL_AMOUNT).text().strip()
            d2 = normalize_date(d)
            desc2 = norm_spaces(desc)
            cat2 = norm_spaces(cat)
            amt2 = None
            try:
                amt2 = money2(parse_decimal(amt_txt))
            except (InvalidOperation, ValueError):
                pass
            if not d2:
                errors.append(f"Row {r + 1}: invalid date '{d}'.")
            if amt2 is None:
                errors.append(f"Row {r + 1}: invalid amount '{amt_txt}'.")
            if strict and not desc2:
                errors.append(f"Row {r + 1}: description is empty.")
            if not strict:
                if not d2:
                    d2 = d
                if amt2 is None:
                    amt2 = Decimal("0.00")
            if d2 and amt2 is not None:
                out.append((Transaction(d2, desc2, amt2), cat2))
        return out, errors

    def recompute_dynamic_closing(self):
        rows, _ = self.get_rows(strict=False)
        try:
            opening = money2(parse_decimal(self.opening.text()))
        except (InvalidOperation, ValueError):
            opening = Decimal("0.00")
        total = sum((row.amount for row, _ in rows), Decimal("0.00"))
        computed = money2(opening + total)
        self.dynamic_closing.setText(f"{computed:.2f}")
        self.update_running_balances()

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
        self.set_lineedit_bg(self.target_closing, "#D7FFD7" if diff == Decimal("0.00") else "#FFF1B8")

    def summarize_categories(self, rows_with_cat):
        totals = {}
        for row, cat in rows_with_cat:
            key = cat or "(uncategorized)"
            totals[key] = money2(totals.get(key, Decimal("0.00")) + row.amount)
        lines = [f"{k}: {v:.2f}" for k, v in sorted(totals.items(), key=lambda x: x[0].lower())]
        return "\n".join(lines)

    def show_validation_details(self):
        _, errors = self.get_rows(strict=True)
        if errors:
            self.validation_text.setPlainText("\n".join(errors))
            self.set_status(f"Validation has {len(errors)} issue(s).")
        else:
            rows, _ = self.get_rows(strict=True)
            self.validation_text.setPlainText("No validation errors.\n\nCategory totals:\n" + self.summarize_categories(rows))
            self.set_status("Validation passed.")

    def validate_balances(self):
        rows, row_errors = self.get_rows(strict=True)
        if row_errors:
            self.validation_text.setPlainText("\n".join(row_errors))
            self.set_status("Validation blocked: " + row_errors[0])
            return
        if not rows:
            self.set_status("No rows to validate.")
            return

        try:
            opening = money2(parse_decimal(self.opening.text()))
        except (InvalidOperation, ValueError):
            self.set_status("Opening balance invalid.")
            return

        try:
            target = money2(parse_decimal(self.target_closing.text()))
        except (InvalidOperation, ValueError):
            self.set_status("Target closing invalid.")
            return

        total = sum((row.amount for row, _ in rows), Decimal("0.00"))
        computed = money2(opening + total)
        diff = money2(computed - target)
        if diff == Decimal("0.00"):
            self.set_status(f"MATCH: Opening {opening:.2f} + Sum {money2(total):.2f} = Target {target:.2f}")
        else:
            self.set_status(f"MISMATCH: computed {computed:.2f} vs target {target:.2f} (diff {diff:.2f})")

        self.validation_text.setPlainText("Category totals:\n" + self.summarize_categories(rows))

    def export_csv(self):
        if self.table.rowCount() == 0:
            self.set_status("Nothing to export.")
            return

        rows, row_errors = self.get_rows(strict=True, visible_only=self.export_filtered.isChecked())
        if row_errors:
            QMessageBox.warning(self, "Export Error", "\n".join(row_errors[:10]))
            return
        if not rows:
            self.set_status("No rows match export selection.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "transactions.csv", "CSV Files (*.csv)")
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "description", "category", "amount"])
                for row, cat in rows:
                    w.writerow([row.date, row.description, cat, f"{money2(row.amount):.2f}"])
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
            "display_format": self.display_fmt.currentText(),
            "rows": [
                {
                    "id": (self.table.item(i, self.COL_DATE).data(Qt.ItemDataRole.UserRole)),
                    "date": row.date,
                    "description": row.description,
                    "category": cat,
                    "amount": str(money2(row.amount)),
                }
                for i, (row, cat) in enumerate(rows)
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
            fmt = data.get("display_format", "YYYY/MM/DD")
            ix = self.display_fmt.findText(fmt)
            if ix >= 0:
                self.display_fmt.setCurrentIndex(ix)

            self._updating = True
            self.table.setRowCount(0)

            max_id = 0
            last_row_id = None
            strict_issues = []
            for idx, row in enumerate(data.get("rows", []), start=1):
                if isinstance(row, dict):
                    raw_id = int(row.get("id", 0) or 0)
                    d = row.get("date", "")
                    desc = row.get("description", "")
                    cat = row.get("category", "")
                    amt = row.get("amount", "0")
                else:
                    raw_id = 0
                    d, desc, amt = row
                    cat = ""
                d2 = normalize_date(d)
                if not d2:
                    strict_issues.append(f"Row {idx}: invalid date '{d}'")
                    d2 = d
                try:
                    amt2 = money2(parse_decimal(str(amt)))
                except (InvalidOperation, ValueError):
                    strict_issues.append(f"Row {idx}: invalid amount '{amt}'")
                    amt2 = Decimal("0.00")

                row_id = raw_id if raw_id > 0 else (max_id + 1)
                max_id = max(max_id, row_id)
                last_row_id = row_id
                self.insert_row(d2, desc, cat, str(amt2), row_id)
                self.learn_description(desc)

            file_next = int(data.get("next_row_id", max_id + 1) or (max_id + 1))
            self._next_row_id = max(file_next, max_id + 1)
            self._updating = False

            self.sort_by_date_if_enabled(last_row_id)
            self.recompute_dynamic_closing()
            self.apply_filter()
            self.push_undo_snapshot()

            if strict_issues:
                self.validation_text.setPlainText("Strict-load warnings:\n" + "\n".join(strict_issues))
            if not quiet:
                self.set_status(f"Loaded {self.table.rowCount()} rows from {path}")
        except (json.JSONDecodeError, OSError, ValueError) as e:
            if not quiet:
                QMessageBox.critical(self, "Load Failed", str(e))

    def populate_editor_from_selection(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if len(rows) != 1:
            return
        r = rows[0]
        self.edit_date.setText(self.table.item(r, self.COL_DATE).text())
        self.edit_desc.setText(self.table.item(r, self.COL_DESC).text())
        self.edit_category.setText(self.table.item(r, self.COL_CATEGORY).text())
        self.edit_amount.setText(self.table.item(r, self.COL_AMOUNT).text())

    def apply_selected_edit(self):
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        if len(rows) != 1:
            self.set_status("Select exactly one row to edit.")
            return
        d = self.display_to_canonical_date(self.edit_date.text())
        if not d:
            self.set_status("Edit date is invalid.")
            return
        desc = norm_spaces(self.edit_desc.text())
        cat = norm_spaces(self.edit_category.text())
        try:
            amt = money2(parse_decimal(self.edit_amount.text()))
        except (InvalidOperation, ValueError):
            self.set_status("Edit amount is invalid.")
            return

        self.push_undo_snapshot()
        r = rows[0]
        self._updating = True
        it_d = self.table.item(r, self.COL_DATE)
        it_d.setData(Qt.ItemDataRole.UserRole + 1, d)
        it_d.setText(self.canonical_to_display_date(d))
        self.table.item(r, self.COL_DESC).setText(desc)
        self.table.item(r, self.COL_CATEGORY).setText(cat)
        self.table.item(r, self.COL_AMOUNT).setText(f"{amt:.2f}")
        self._updating = False

        self.learn_description(desc)
        self.sort_by_date_if_enabled(it_d.data(Qt.ItemDataRole.UserRole))
        self.recompute_dynamic_closing()
        self.apply_filter()
        self.set_status("Row updated.")


def main():
    app = QApplication(sys.argv)
    w = FastEntry()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
