"""Native Qt desktop interface. Source and database work belongs to ControllerWorker."""
from __future__ import annotations

import copy
import json
import os
import time
import textwrap
import uuid
from pathlib import Path
from typing import Callable

from . import __version__
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt, QLockFile
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QStyle, QSystemTrayIcon, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


def label(text: str, muted: bool = False) -> QLabel:
    item = QLabel(text)
    item.setWordWrap(True)
    item.setTextFormat(Qt.TextFormat.PlainText)
    if muted:
        item.setObjectName("muted")
    return item


def spin(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
    item = QSpinBox()
    item.setRange(minimum, maximum)
    item.setValue(value)
    item.setSuffix(suffix)
    return item


def combo(options: list[tuple[str, str]], value: str = "") -> QComboBox:
    item = QComboBox()
    for title, data in options:
        item.addItem(title, data)
    if value:
        item.setCurrentIndex(max(0, item.findData(value)))
    return item


def set_combo(item: QComboBox, value: object) -> None:
    index = item.findData(value)
    if index >= 0:
        item.setCurrentIndex(index)


def compact_time(value):
    value=str(value or "—")
    if "T" in value:
        # Preserve the original offset; subsecond receipts remain available in details.
        import re
        return re.sub(r"\.\d+(?=[+-]\d\d:\d\d$)","",value).replace("T"," ")
    return value


def wrap_forms(widget):
    def visit(layout):
        if layout is None:
            return
        if isinstance(layout,QFormLayout):
            layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for i in range(layout.count()):
            visit(layout.itemAt(i).layout())
    for child in [widget,*widget.findChildren(QWidget)]:
        if isinstance(child,QCheckBox) and len(child.text())>42:
            child.setText(textwrap.fill(child.text().replace("\n"," "),width=42))
        visit(child.layout())


def icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#164f67"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(1, 1, 62, 62, 15, 15)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "A")
    painter.end()
    return QIcon(pixmap)


class ControllerWorker(QObject):
    snapshot_ready = Signal(dict)
    result_ready = Signal(str, object)
    finished = Signal()

    def __init__(self, state_dir: str | None, factory: Callable | None = None):
        super().__init__()
        self.state_dir = state_dir
        self.factory = factory
        self.controller = None
        self.timer = None
        self.last_snapshot = 0.0

    @Slot()
    def initialize(self):
        try:
            if self.factory is None:
                from .controller import Controller
                self.factory = Controller
            self.controller = self.factory(state_dir=self.state_dir)
            self.timer = QTimer(self)
            self.timer.setInterval(250)
            self.timer.timeout.connect(self.pulse)
            self.timer.start()
            self.publish()
        except Exception as exc:
            self.result_ready.emit("error", {"error": self.safe_error(exc)})

    @staticmethod
    def safe_error(exc):
        try:
            from .notifications import redact
            return redact(str(exc))
        except Exception:
            return type(exc).__name__ + ": operation failed"

    def publish(self):
        if self.controller is not None:
            self.snapshot_ready.emit(self.controller.snapshot())
            self.last_snapshot = time.monotonic()

    @Slot()
    def pulse(self):
        try:
            self.controller.tick()
            if time.monotonic() - self.last_snapshot >= 1:
                self.publish()
        except Exception as exc:
            self.result_ready.emit("error", {"error": self.safe_error(exc)})

    @Slot(str, dict)
    def command(self, command, payload):
        if self.controller is None:
            self.result_ready.emit(command, {"error": "Monitor worker has not initialized."})
            return
        try:
            if command=="configure":
                payload=copy.deepcopy(payload)
                # Only credential actions can replace references. A quick Apply/Test
                # must not overwrite a just-saved secret with a stale UI snapshot.
                for channel in ("gmail","telegram"):
                    payload.setdefault("channels",{}).setdefault(channel,{})["credential_ref"]=self.controller.config["channels"][channel]["credential_ref"]
            result = self.controller.handle(command, payload)
            if result is not None:
                self.result_ready.emit(command, result)
            self.publish()
        except Exception as exc:
            self.result_ready.emit(command, {"error": self.safe_error(exc)})

    @Slot()
    def shutdown(self):
        if self.timer is not None:
            self.timer.stop()
        try:
            if self.controller is not None:
                self.controller.close()
        finally:
            self.finished.emit()


class RuleDialog(QDialog):
    def __init__(self, rule: dict | None = None, parent=None):
        super().__init__(parent)
        self.original = copy.deepcopy(rule or {})
        self.setWindowTitle("Edit rule" if rule else "Add rule")
        self.resize(530, 540)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(self.original.get("name", ""))
        self.pattern = QLineEdit(self.original.get("pattern", ""))
        self.enabled = QCheckBox("Enabled for future records")
        self.enabled.setChecked(self.original.get("enabled", True))
        self.kind = combo([("Literal word or phrase", "literal"), ("Logged level", "level")], self.original.get("kind", "literal"))
        self.levels = QLineEdit(", ".join(self.original.get("levels", ["Error", "Fatal", "Critical"])))
        self.mode = combo([("Contains", "contains"), ("Whole word / phrase", "whole"), ("Exact message", "exact")], self.original.get("mode", "contains"))
        self.scope = combo([("Message only", "message"), ("Full original line", "full")], self.original.get("scope", "message"))
        self.case = QCheckBox("Case sensitive")
        self.case.setChecked(self.original.get("case_sensitive", False))
        self.severity = combo([("Warning", "warning"), ("Error", "error"), ("Critical", "critical")], self.original.get("severity", "error"))
        self.component = QLineEdit(self.original.get("component", ""))
        self.gmail = QCheckBox("Gmail")
        self.telegram = QCheckBox("Telegram")
        channels = self.original.get("channels", ["gmail", "telegram"])
        self.gmail.setChecked("gmail" in channels)
        self.telegram.setChecked("telegram" in channels)
        self.ignore = QCheckBox("Ignore matching records (auditable suppression)")
        self.ignore.setChecked(self.original.get("ignore", False))
        for title, widget in [("Name", self.name), ("Rule type", self.kind), ("Literal text", self.pattern), ("Logged levels", self.levels), ("Match mode", self.mode), ("Search", self.scope), ("", self.case), ("Alert severity", self.severity), ("Component (optional)", self.component), ("Channels", self.gmail), ("", self.telegram), ("", self.ignore), ("", self.enabled)]:
            form.addRow(title, widget)
        layout.addLayout(form)
        layout.addWidget(label("Whole-word matching uses Unicode letter, number and underscore boundaries. Ignore rules can suppress Error-level records; review them carefully.", True))
        self.error = label("")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        if not self.name.text().strip():
            self.error.setText("Enter a rule name.")
        elif self.kind.currentData() == "literal" and not self.pattern.text().strip():
            self.error.setText("Enter a nonempty literal word or phrase.")
        elif self.kind.currentData() == "level" and not self.levels.text().strip():
            self.error.setText("Enter at least one logged level.")
        elif self.ignore.isChecked() and QMessageBox.warning(self, "Review ignore rule", "This ignore rule may suppress Error-level events. Keep this explicit suppression?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        else:
            self.accept()

    def value(self):
        return {**self.original, "id": self.original.get("id", uuid.uuid4().hex), "name": self.name.text().strip(), "pattern": self.pattern.text(), "kind": self.kind.currentData(), "levels": [x.strip() for x in self.levels.text().split(",") if x.strip()], "mode": self.mode.currentData(), "scope": self.scope.currentData(), "case_sensitive": self.case.isChecked(), "severity": self.severity.currentData(), "component": self.component.text().strip(), "channels": [x for x, w in [("gmail", self.gmail), ("telegram", self.telegram)] if w.isChecked()], "ignore": self.ignore.isChecked(), "enabled": self.enabled.isChecked()}


class SourcePanel(QWidget):
    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.folder = QLineEdit()
        self.filename = QLineEdit()
        self.folder.setPlaceholderText("Choose the actual source folder")
        self.path = label("Select a folder and filename", True)
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        browse = QPushButton("Browse folder…")
        browse.clicked.connect(self.browse_folder)
        direct = QPushButton("Choose log file…")
        direct.clicked.connect(self.browse_file)
        pathrow = QHBoxLayout()
        pathrow.addWidget(browse)
        pathrow.addWidget(direct)
        self.encoding = combo([("Automatic (BOM / UTF-8 / Windows-1252)", "auto"), ("UTF-8", "utf-8"), ("Windows-1252", "cp1252"), ("UTF-16 little endian", "utf-16-le"), ("UTF-16 big endian", "utf-16-be")])
        self.timezone = QLineEdit()
        self.timezone.setPlaceholderText("Unknown / naive; optional IANA name")
        self.interval = spin(0, 3600, 0, " s")
        self.interval.setSpecialValueText("Use global polling interval")
        self.expect = QCheckBox("Expect activity — arm inactivity watch")
        self.activity_mode = combo([("N empty successful polls", "cycles"), ("Elapsed quiet duration", "duration")])
        self.cycles = spin(1, 100000, 30)
        self.duration = spin(1, 604800, 300, " s")
        self.grace = spin(0, 86400, 60, " s")
        self.nominal = label("", True)
        self.heartbeat = QCheckBox("Watch ‘Process is alive.’ heartbeat")
        self.heartbeat_seconds = spin(30, 604800, 300, " s")
        self.progress = QCheckBox("Watch completed / advancing imaging progress")
        self.progress_seconds = spin(30, 604800, 900, " s")
        self.lifecycle = QCheckBox("Disarm activity on run ended / known suspension")
        self.lifecycle.setChecked(True)
        self.reminder = spin(0, 604800, 1800, " s")
        self.reminder.setSpecialValueText("No repeated reminders")
        self.recovery = QCheckBox("Notify when activity recovers")
        for title, widget in [("Folder", self.folder), ("Filename", self.filename)]:
            form.addRow(title, widget)
        form.addRow("", pathrow)
        form.addRow("Resolved path", self.path)
        form.addRow("Encoding", self.encoding)
        form.addRow("Source timezone", self.timezone)
        form.addRow("Polling override", self.interval)
        self.validate_button = QPushButton("Validate / test read (read-only)")
        form.addRow("", self.validate_button)
        form.addRow("", self.expect)
        form.addRow("Silence policy", self.activity_mode)
        form.addRow("Consecutive empty polls", self.cycles)
        form.addRow("Quiet duration", self.duration)
        form.addRow("Startup / resume grace", self.grace)
        form.addRow("Effective policy", self.nominal)
        if source == "execution":
            form.addRow("", self.heartbeat)
            form.addRow("Heartbeat threshold", self.heartbeat_seconds)
            form.addRow("", self.progress)
            form.addRow("Progress threshold", self.progress_seconds)
        form.addRow("", self.lifecycle)
        form.addRow("Reminder interval", self.reminder)
        form.addRow("", self.recovery)
        layout.addLayout(form)
        note = "Execution sample heartbeat intervals exceed two minutes. Initial thresholds are sample-derived and require adjustment for your experiment." if source == "execution" else "The prefilled engine folder is an unverified suggestion. Use Choose log file to select the actual ATLAS log. Engine records may be roughly an hour apart; silence does not prove a crash."
        layout.addWidget(label(note, True))
        layout.addStretch()
        self.folder.textChanged.connect(self.update_path)
        self.filename.textChanged.connect(self.update_path)

    def update_path(self):
        self.path.setText(self.full_path())

    def full_path(self):
        return str(Path(self.folder.text()).expanduser() / self.filename.text())

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select " + self.source + " source folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select " + self.source + " source log", self.folder.text(), "Log files (*.log *.txt);;All files (*)")
        if path:
            self.folder.setText(str(Path(path).parent))
            self.filename.setText(Path(path).name)

    def load(self, config):
        self.original = copy.deepcopy(config)
        self.folder.setText(config.get("folder", ""))
        self.filename.setText(config.get("filename", ""))
        set_combo(self.encoding, config.get("encoding", "auto"))
        self.timezone.setText(config.get("timezone", ""))
        self.interval.setValue(config.get("interval", 0))
        self.expect.setChecked(config.get("expect_activity", False))
        set_combo(self.activity_mode, config.get("inactivity_mode", "cycles"))
        for widget, key, default in [(self.cycles,"cycles",30),(self.duration,"duration",300),(self.grace,"grace",60),(self.heartbeat_seconds,"heartbeat_seconds",300),(self.progress_seconds,"progress_seconds",900),(self.reminder,"reminder_seconds",1800)]:
            widget.setValue(int(config.get(key, default)))
        self.heartbeat.setChecked(config.get("heartbeat", False))
        self.progress.setChecked(config.get("progress", False))
        self.lifecycle.setChecked(config.get("lifecycle_disarm", True))
        self.recovery.setChecked(config.get("recovery_notify", False))

    def value(self):
        return {**getattr(self,"original",{}), "folder":self.folder.text().strip(), "filename":self.filename.text().strip(), "encoding":self.encoding.currentData(), "timezone":self.timezone.text().strip(), "interval":self.interval.value(), "expect_activity":self.expect.isChecked(), "inactivity_mode":self.activity_mode.currentData(), "cycles":self.cycles.value(), "duration":self.duration.value(), "grace":self.grace.value(), "heartbeat":self.heartbeat.isChecked(), "heartbeat_seconds":self.heartbeat_seconds.value(), "progress":self.progress.isChecked(), "progress_seconds":self.progress_seconds.value(), "lifecycle_disarm":self.lifecycle.isChecked(), "reminder_seconds":self.reminder.value(), "recovery_notify":self.recovery.isChecked()}


class MainWindow(QMainWindow):
    command_requested = Signal(str, dict)
    shutdown_requested = Signal()

    def __init__(self, controller_factory=None, state_dir=None, enable_tray=True):
        super().__init__()
        self.setWindowTitle(f"ATLAS Watchdog {__version__}")
        self.setWindowIcon(icon())
        self.resize(1390, 900)
        self.config = {}
        self.current_snapshot = {}
        self.events = []
        self.history_offset = 0
        self.display_cleared = set()
        self.shutting_down = False
        self.loaded = False
        self.pending_start = None
        self.pending_test_channel = None
        self.pending_gmail_check = False
        self.last_snapshot_at = time.monotonic()
        self.build_ui()
        self.build_menu()
        wrap_forms(self)
        self.thread = QThread(self)
        self.worker = ControllerWorker(state_dir, controller_factory)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.initialize)
        self.command_requested.connect(self.worker.command, Qt.ConnectionType.QueuedConnection)
        self.shutdown_requested.connect(self.worker.shutdown, Qt.ConnectionType.QueuedConnection)
        self.worker.snapshot_ready.connect(self.receive_snapshot)
        self.worker.result_ready.connect(self.receive_result)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.start()
        self.tray = None
        if enable_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            tray_menu = QMenu(self)
            tray_menu.addAction("Show ATLAS Watchdog", self.activate)
            tray_menu.addSeparator()
            tray_menu.addAction("Quit and stop monitoring", self.quit_app)
            self.tray.setContextMenu(tray_menu)
            self.tray.activated.connect(lambda reason: self.activate() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
            self.tray.show()
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_worker_health)
        self.health_timer.start(2000)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)
        header = QHBoxLayout()
        brand = label(f"ATLAS  /  WATCHDOG  ·  {__version__}")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        self.monitor_button = QPushButton("Start monitoring")
        self.monitor_button.setObjectName("primary")
        self.monitor_button.setMinimumHeight(42)
        self.monitor_button.clicked.connect(self.toggle_monitor)
        self.alerts_button = QPushButton("Start alerts")
        self.alerts_button.setMinimumHeight(42)
        self.alerts_button.clicked.connect(self.toggle_alerts)
        header.addWidget(self.monitor_button)
        header.addWidget(self.alerts_button)
        outer.addLayout(header)
        self.banner = label("Monitoring stopped  ·  External alerts off")
        self.banner.setObjectName("banner")
        outer.addWidget(self.banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)
        side = QWidget()
        side.setMinimumWidth(365)
        side.setMaximumWidth(540)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 10, 0)
        self.settings_tabs = QTabWidget()
        side_layout.addWidget(self.settings_tabs, 1)
        self.build_settings()
        self.apply_button = QPushButton("Apply settings and rules")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply_settings)
        side_layout.addWidget(self.apply_button)
        side_layout.addWidget(label("Changes affect future records. Path or source-mode changes restart the source session using your selected start policy.", True))
        splitter.addWidget(side)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 0, 0, 0)
        cards = QHBoxLayout()
        self.source_cards = {}
        for source in ("engine", "execution"):
            box = QGroupBox(source.upper())
            box_layout = QVBoxLayout(box)
            state = label("Stopped")
            state.setObjectName("cardState")
            path = label("No source selected", True)
            detail = label("Waiting for configuration", True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box_layout.addWidget(state)
            box_layout.addWidget(path)
            box_layout.addWidget(detail)
            self.source_cards[source] = (box,state,path,detail)
            cards.addWidget(box)
        center_layout.addLayout(cards)
        self.view_tabs = QTabWidget()
        center_layout.addWidget(self.view_tabs, 1)
        self.build_events()
        self.build_live()
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setMaximumBlockCount(500)
        self.results.setPlaceholderText("Validation, rule-test and notification-test results appear here. Provider acceptance does not prove receipt on a phone.")
        self.view_tabs.addTab(self.results, "Tests && diagnostics")
        splitter.addWidget(center)
        splitter.setSizes([410, 950])
        self.status = label("Initializing local worker…", True)
        outer.addWidget(self.status)

    def scroll_tab(self, widget, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        self.settings_tabs.addTab(scroll, name)

    def build_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.mode = combo([("Both logs", "both"), ("Engine only", "engine"), ("Execution only", "execution")])
        self.poll = spin(1, 3600, 10, " s")
        self.instrument = QLineEdit()
        self.instrument.setPlaceholderText("Computer or instrument label")
        self.job = QLineEdit()
        self.job.setPlaceholderText("Optional experiment label")
        self.start_mode = combo([("New entries only (default)", "new"), ("Resume valid checkpoint", "resume"), ("Review existing contents", "review")])
        self.historical_alerts = QCheckBox("Explicitly allow alerts on historical review")
        self.grouping = spin(0, 3600, 30, " s")
        self.paths_optin = QCheckBox("Include full paths in external notifications")
        self.context_optin = QCheckBox("Include preceding context in external notifications")
        self.minimize_close = QCheckBox("Close window to tray; monitoring continues")
        self.minimize_close.setChecked(True)
        self.local_notify = QCheckBox("Local tray notification for new faults")
        for title, item in [("Log sources",self.mode),("Global polling",self.poll),("Instrument / computer",self.instrument),("Job",self.job),("Start policy",self.start_mode),("",self.historical_alerts),("Burst grouping",self.grouping),("",self.paths_optin),("",self.context_optin),("",self.minimize_close),("",self.local_notify)]:
            form.addRow(title,item)
        layout.addLayout(form)
        layout.addWidget(label("Alerts control Gmail and Telegram sending. Detection, local history and acknowledgment continue when alerts are off. Neither control is automatically restored on launch.", True))
        layout.addWidget(label("Undelivered messages from a previous session require a deliberate resend or discard. Rearming alerts applies to future eligible events.", True))
        queue_row = QHBoxLayout()
        resend = QPushButton("Resend old queue…")
        resend.clicked.connect(lambda: self.confirm_queue("replay_queue"))
        discard = QPushButton("Discard old queue…")
        discard.clicked.connect(lambda: self.confirm_queue("discard_queue"))
        queue_row.addWidget(resend)
        queue_row.addWidget(discard)
        layout.addLayout(queue_row)
        demo = QGroupBox("DEMO — temporary simulated logs")
        demo_grid = QGridLayout(demo)
        for i,(title,action) in enumerate([("Start demo","start"),("Pause","pause"),("Resume","resume"),("Burst","burst"),("Rotate","rotate"),("Truncate","truncate")]):
            button=QPushButton(title)
            button.clicked.connect(lambda _=False,a=action:self.send("demo",{"action":a}))
            demo_grid.addWidget(button,i//3,i%3)
        layout.addWidget(demo)
        exit_demo=QPushButton("Exit demo and restore configured sources")
        exit_demo.clicked.connect(lambda:self.send("demo",{"action":"stop"}))
        layout.addWidget(exit_demo)
        layout.addStretch()
        self.scroll_tab(page,"General")
        self.source_panels={}
        source_page=QWidget()
        source_layout=QVBoxLayout(source_page)
        source_tabs=QTabWidget()
        source_layout.addWidget(source_tabs)
        for source in ("engine","execution"):
            panel=SourcePanel(source)
            self.source_panels[source]=panel
            source_tabs.addTab(panel,source.title())
            panel.validate_button.clicked.connect(lambda _=False,s=source:self.send("validate",{"source":s,"path":self.source_panels[s].full_path()}))
            panel.cycles.valueChanged.connect(self.update_nominal)
            panel.interval.valueChanged.connect(self.update_nominal)
            panel.duration.valueChanged.connect(self.update_nominal)
            panel.activity_mode.currentIndexChanged.connect(self.update_nominal)
        self.poll.valueChanged.connect(self.update_nominal)
        self.scroll_tab(source_page,"Sources")
        self.build_rules()
        self.build_channels()

    def build_rules(self):
        page=QWidget()
        layout=QVBoxLayout(page)
        self.rule_source=combo([("Engine rules","engine"),("Execution rules","execution")])
        self.rule_source.currentIndexChanged.connect(self.render_rules)
        layout.addWidget(self.rule_source)
        self.rule_list=QListWidget()
        self.rule_list.setMinimumHeight(240)
        self.rule_list.itemDoubleClicked.connect(lambda _:self.edit_rule())
        self.rule_list.itemChanged.connect(self.rule_toggled)
        layout.addWidget(self.rule_list)
        row=QHBoxLayout()
        for text,method in [("Add",self.add_rule),("Edit",self.edit_rule),("Remove",self.remove_rule)]:
            button=QPushButton(text)
            button.clicked.connect(method)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(label("Optional WMAcqError and detector presets need operational validation. Literal EHT variants are separate rules. An Error level match never depends on the word ‘error’.",True))
        self.rule_test=QPlainTextEdit()
        self.rule_test.setPlaceholderText("Paste one sample log line or message. Testing never creates a real alert.")
        self.rule_test.setMaximumHeight(130)
        layout.addWidget(self.rule_test)
        tester=QPushButton("Test sample text against saved rules")
        tester.clicked.connect(lambda:self.send("test_rule",{"source":self.rule_source.currentData(),"text":self.rule_test.toPlainText()}))
        layout.addWidget(tester)
        layout.addStretch()
        self.scroll_tab(page,"Rules")

    def build_channels(self):
        tabs=QTabWidget()
        self.channel_widgets={}
        instructions={
            "gmail":"1. Choose a dedicated Gmail account.\n2. Enable two-step verification.\n3. Create an app password, if available for your account.\n4. Enter the Gmail sender and recipients below.\n5. Save the app password securely and send a test.\n6. Verify receipt and the spam folder.\n\nUse an app password, never your regular account password. Account policy can prevent app passwords; changing the Google password revokes existing app passwords. No browser session is needed at runtime.",
            "telegram":"1. Open verified @BotFather in Telegram.\n2. Use /newbot to create a dedicated bot.\n3. Open that bot and press Start or send /start.\n4. Save its token, then Check bot.\n5. Find my chat or enter a private chat ID.\n6. Send a test and verify phone sound/popups.\n\nA webhook or another update consumer can conflict with discovery. The app never removes webhooks or discards updates. No Premium subscription, inbound port or hosted bot is required."}
        for channel in ("gmail","telegram"):
            page=QWidget()
            layout=QVBoxLayout(page)
            layout.addWidget(label(instructions[channel],True))
            if channel=="gmail":
                links=QLabel('<a href="https://support.google.com/accounts/answer/185833">Google app-password help</a> · <a href="https://myaccount.google.com/apppasswords">Create app password</a>')
            else:
                links=QLabel('<a href="https://core.telegram.org/bots/tutorial">Official bot setup guide</a>')
            links.setOpenExternalLinks(True)
            links.setWordWrap(True)
            layout.addWidget(links)
            form=QFormLayout()
            enabled=QCheckBox("Enable this external notification channel")
            secret=QLineEdit()
            secret.setEchoMode(QLineEdit.EchoMode.Password)
            secret.setPlaceholderText("Enter replacement secret; never exported")
            persistent=QCheckBox("Store in Windows Credential Manager")
            persistent.setChecked(True)
            state=label("No credential status yet",True)
            widgets={"enabled":enabled,"secret":secret,"persistent":persistent,"state":state}
            form.addRow("",enabled)
            if channel=="gmail":
                sender=QLineEdit()
                recipients=QLineEdit()
                recipients.setPlaceholderText("recipient@example.org, second@example.org")
                port=combo([("465 — implicit TLS","465"),("587 — mandatory STARTTLS","587")])
                widgets.update(sender=sender,recipients=recipients,port=port)
                form.addRow("Gmail sender",sender)
                form.addRow("Recipient(s)",recipients)
                form.addRow("SMTP port",port)
            else:
                chat=QLineEdit()
                chat.setPlaceholderText("Numeric private chat ID")
                widgets["chat_id"]=chat
                form.addRow("Chat ID",chat)
            form.addRow("App password" if channel=="gmail" else "Bot token",secret)
            form.addRow("",persistent)
            form.addRow("Credential",state)
            layout.addLayout(form)
            row=QHBoxLayout()
            save=QPushButton("Save / replace secret")
            save.clicked.connect(lambda _=False,c=channel:self.save_secret(c))
            remove=QPushButton("Remove secret")
            remove.clicked.connect(lambda _=False,c=channel:self.send("credential",{"channel":c,"remove":True}))
            row.addWidget(save)
            row.addWidget(remove)
            layout.addLayout(row)
            if channel=="telegram":
                row=QHBoxLayout()
                check=QPushButton("Check bot")
                check.clicked.connect(lambda:self.send("telegram_check",{}))
                discover=QPushButton("Find my chat")
                discover.clicked.connect(lambda:self.send("telegram_chats",{}))
                row.addWidget(check)
                row.addWidget(discover)
                layout.addLayout(row)
            else:
                check=QPushButton("Check SMTP connection (no email)")
                check.clicked.connect(self.check_gmail_connection)
                layout.addWidget(check)
            test=QPushButton("Send TEST email" if channel=="gmail" else "Send TEST notification")
            test.clicked.connect(lambda _=False,c=channel:self.test_channel(c))
            layout.addWidget(test)
            layout.addWidget(label("Tests send only the requested TEST message and do not arm automatic alerts. Save settings first. Provider acceptance is not proof that a message was read. Network access and phone settings affect delivery.",True))
            layout.addStretch()
            self.channel_widgets[channel]=widgets
            scroll=QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            tabs.addTab(scroll,channel.title())
        self.settings_tabs.addTab(tabs,"Delivery")

    def build_events(self):
        page=QWidget()
        layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.event_search=QLineEdit()
        self.event_search.setPlaceholderText("Filter message, source, severity, rule…")
        self.event_search.textChanged.connect(self.render_events)
        self.event_source=combo([("All sources","all"),("Engine","engine"),("Execution","execution")])
        self.event_source.currentIndexChanged.connect(self.render_events)
        self.unacked=QCheckBox("Unacknowledged only")
        self.unacked.stateChanged.connect(self.render_events)
        self.current_session_only=QCheckBox("Current session only")
        self.current_session_only.setChecked(True)
        self.current_session_only.setToolTip("Show events detected during this monitoring session. Uncheck to browse stored history.")
        self.current_session_only.stateChanged.connect(self.render_events)
        row.addWidget(self.event_search,1)
        row.addWidget(self.event_source)
        row.addWidget(self.current_session_only)
        row.addWidget(self.unacked)
        layout.addLayout(row)
        split=QSplitter(Qt.Orientation.Vertical)
        self.table=QTableWidget(0,10)
        self.table.setMinimumHeight(160)
        self.table.setHorizontalHeaderLabels(["Source","Severity / level","Detected","Logged time","Message","Count","Gmail","Telegram","Acknowledged","Rules"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(4,370)
        self.table.setWordWrap(False)
        self.table.itemSelectionChanged.connect(self.show_details)
        split.addWidget(self.table)
        self.details=QPlainTextEdit()
        self.details.setMinimumHeight(90)
        self.details.setReadOnly(True)
        self.details.setMaximumBlockCount(1000)
        self.details.setPlaceholderText("Select an event for its complete message, original line, preceding source context and delivery evidence.")
        split.addWidget(self.details)
        split.setSizes([380,190])
        layout.addWidget(split,1)
        row=QHBoxLayout()
        ack=QPushButton("Acknowledge selected")
        ack.clicked.connect(self.acknowledge)
        older=QPushButton("Older history")
        older.clicked.connect(self.older_history)
        newest=QPushButton("Latest events")
        newest.clicked.connect(self.latest_events)
        clear=QPushButton("Clear display")
        clear.clicked.connect(self.clear_display)
        export=QPushButton("Export history…")
        export.clicked.connect(self.export_history)
        for button in (ack,older,newest,clear,export):
            row.addWidget(button)
        layout.addLayout(row)
        self.view_tabs.addTab(page,"Events && history")

    def build_live(self):
        page=QWidget()
        layout=QVBoxLayout(page)
        row=QHBoxLayout()
        self.live_search=QLineEdit()
        self.live_search.setPlaceholderText("Search retained live lines")
        self.live_search.textChanged.connect(self.render_live)
        self.pause_scroll=QCheckBox("Pause auto-scroll")
        self.matched_only=QCheckBox("Matched records only")
        self.matched_only.stateChanged.connect(self.render_live)
        row.addWidget(self.live_search,1)
        row.addWidget(self.pause_scroll)
        row.addWidget(self.matched_only)
        layout.addLayout(row)
        tabs=QTabWidget()
        self.live_views={}
        for source in ("engine","execution"):
            view=QPlainTextEdit()
            view.setReadOnly(True)
            view.setMaximumBlockCount(1000)
            view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            view.setFont(QFont("Consolas",10))
            self.live_views[source]=view
            tabs.addTab(view,source.upper())
        layout.addWidget(tabs,1)
        layout.addWidget(label("Live display is bounded. Older matched events remain in local SQLite history according to retention settings. Log contents are always displayed as plain text.",True))
        self.view_tabs.addTab(page,"Live logs")

    def build_menu(self):
        file=self.menuBar().addMenu("File")
        file.addAction("Import configuration…",self.import_config)
        file.addAction("Export configuration (no secrets)…",self.export_config)
        file.addAction("Export event history…",self.export_history)
        file.addAction("Export support bundle…",self.export_support)
        file.addSeparator()
        file.addAction("Delete stored event history…",self.delete_history)
        file.addSeparator()
        file.addAction("Quit and stop monitoring",self.quit_app)
        view=self.menuBar().addMenu("View")
        view.addAction("Clear current event display",self.clear_display)
        view.addAction("Show latest events",self.latest_events)
        help_menu=self.menuBar().addMenu("Help")
        help_menu.addAction("Operational limits",lambda:QMessageBox.information(self,"Operational limits","ATLAS Watchdog only observes logs. Silence can indicate a possible stall but cannot prove a crash. This PC cannot immediately report its own power loss, OS failure or total network failure.\n\nShared read flags permit ATLAS writes and renames, but cannot override an exclusive ATLAS handle. Complete Windows acceptance testing with an expendable acquisition before unattended use.\n\nLocal event history can contain experiment data. No telemetry or automatic log uploads are enabled."))

    def send(self,command,payload=None):
        # Queued Python signal objects are shared references; freeze each command.
        self.command_requested.emit(command,copy.deepcopy(payload or {}))

    def collect_config(self):
        config=copy.deepcopy(self.config)
        config.update(mode=self.mode.currentData(),poll_seconds=self.poll.value(),instrument=self.instrument.text().strip(),job=self.job.text().strip(),grouping_seconds=self.grouping.value(),include_paths=self.paths_optin.isChecked(),include_context=self.context_optin.isChecked(),close_to_tray=self.minimize_close.isChecked(),local_notifications=self.local_notify.isChecked(),geometry=bytes(self.saveGeometry().toBase64()).decode("ascii"))
        config["sources"]={source:panel.value() for source,panel in self.source_panels.items()}
        channels=config.setdefault("channels",{})
        for channel,widgets in self.channel_widgets.items():
            settings=channels.setdefault(channel,{})
            settings["enabled"]=widgets["enabled"].isChecked()
            if channel=="gmail":
                settings.update(sender=widgets["sender"].text().strip(),recipients=[x.strip() for x in widgets["recipients"].text().replace(";",",").split(",") if x.strip()],port=int(widgets["port"].currentData()))
            else:
                settings["chat_id"]=widgets["chat_id"].text().strip()
        return config

    def apply_settings(self):
        if not self.loaded:
            return
        previous=self.config
        value=self.collect_config()
        path_changed=previous.get("mode")!=value.get("mode") or any((previous.get("sources",{}).get(s,{}).get("folder"),previous.get("sources",{}).get(s,{}).get("filename"))!=(value["sources"][s]["folder"],value["sources"][s]["filename"]) for s in ("engine","execution"))
        running=self.current_snapshot.get("monitoring",False)
        if path_changed and running:
            self.send("stop")
            self.pending_start={"mode":self.start_mode.currentData(),"historical_alerts":self.historical_alerts.isChecked()}
        self.config=value
        self.send("configure",value)

    def load_config(self,config):
        self.config=copy.deepcopy(config)
        set_combo(self.mode,config.get("mode","both"))
        self.poll.setValue(int(config.get("poll_seconds",10)))
        self.instrument.setText(config.get("instrument",""))
        self.job.setText(config.get("job",""))
        self.grouping.setValue(int(config.get("grouping_seconds",30)))
        self.paths_optin.setChecked(config.get("include_paths",False))
        self.context_optin.setChecked(config.get("include_context",False))
        self.minimize_close.setChecked(config.get("close_to_tray",True))
        self.local_notify.setChecked(config.get("local_notifications",False))
        for source,panel in self.source_panels.items():
            panel.load(config.get("sources",{}).get(source,{}))
        for channel,widgets in self.channel_widgets.items():
            settings=config.get("channels",{}).get(channel,{})
            widgets["enabled"].setChecked(settings.get("enabled",False))
            if channel=="gmail":
                widgets["sender"].setText(settings.get("sender",""))
                widgets["recipients"].setText(", ".join(settings.get("recipients",[])))
                set_combo(widgets["port"],str(settings.get("port",465)))
            else:
                widgets["chat_id"].setText(str(settings.get("chat_id","")))
            widgets["state"].setText("Saved secure/session credential reference" if settings.get("credential_ref") else "No credential saved")
        self.render_rules()
        self.update_nominal()
        if not self.loaded and config.get("geometry"):
            from PySide6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(config["geometry"].encode("ascii")))
        self.loaded=True

    def update_nominal(self):
        for panel in getattr(self,"source_panels",{}).values():
            interval=panel.interval.value() or self.poll.value()
            nominal=panel.cycles.value()*interval if panel.activity_mode.currentData()=="cycles" else panel.duration.value()
            panel.nominal.setText(f"Poll every {interval} s; threshold {nominal:,} s; grace {panel.grace.value()} s")

    def toggle_monitor(self):
        if self.current_snapshot.get("monitoring"):
            self.send("stop")
        else:
            self.pending_start={"mode":self.start_mode.currentData(),"historical_alerts":self.historical_alerts.isChecked()}
            self.apply_settings()

    def toggle_alerts(self):
        if not self.current_snapshot.get("alerts", False) and not any(
            settings.get("enabled", False) for settings in self.config.get("channels", {}).values()
        ):
            QMessageBox.information(
                self, "No delivery channel enabled",
                "Enable Gmail or Telegram in Delivery, click Apply settings and rules, then Start alerts. "
                "A successful TEST message does not enable automatic alerts.",
            )
            return
        self.send("alerts",{"armed":not self.current_snapshot.get("alerts",False)})

    def render_rules(self):
        self.rule_list.blockSignals(True)
        self.rule_list.clear()
        rules=self.config.get("rules",{}).get(self.rule_source.currentData(),[])
        for rule in rules:
            text=("IGNORE · " if rule.get("ignore") else "")+rule.get("name",rule.get("pattern","Rule"))
            item=QListWidgetItem(text)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rule.get("enabled",True) else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole,rule.get("id"))
            item.setToolTip(json.dumps(rule,ensure_ascii=False,indent=2))
            self.rule_list.addItem(item)
        self.rule_list.blockSignals(False)

    def rule_toggled(self,item):
        for rule in self.config.get("rules",{}).get(self.rule_source.currentData(),[]):
            if rule.get("id")==item.data(Qt.ItemDataRole.UserRole):
                rule["enabled"]=item.checkState()==Qt.CheckState.Checked

    def add_rule(self):
        dialog=RuleDialog(parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.config.setdefault("rules",{}).setdefault(self.rule_source.currentData(),[]).append(dialog.value())
            self.render_rules()

    def edit_rule(self):
        index=self.rule_list.currentRow()
        rules=self.config.get("rules",{}).get(self.rule_source.currentData(),[])
        if index<0 or index>=len(rules):
            return
        dialog=RuleDialog(rules[index],self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            rules[index]=dialog.value()
            self.render_rules()

    def remove_rule(self):
        index=self.rule_list.currentRow()
        rules=self.config.get("rules",{}).get(self.rule_source.currentData(),[])
        if 0<=index<len(rules):
            rules.pop(index)
            self.render_rules()

    def save_secret(self,channel):
        widgets=self.channel_widgets[channel]
        secret=widgets["secret"].text()
        if not secret.strip():
            QMessageBox.information(self,"Secret required","Enter the app password or bot token in the masked field.")
            return
        self.send("credential",{"channel":channel,"secret":secret,"persistent":widgets["persistent"].isChecked()})
        widgets["secret"].clear()

    def test_channel(self,channel):
        self.pending_test_channel=channel
        self.apply_settings()

    def check_gmail_connection(self):
        self.pending_gmail_check=True
        self.apply_settings()

    def confirm_queue(self,command):
        text="Deliberately resend persisted undelivered items? Provider acceptance may be uncertain; duplicate messages are possible." if command=="replay_queue" else "Discard persisted undelivered notification items? Event history will remain."
        if QMessageBox.question(self,"Stored notification queue",text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.send(command)

    @Slot(dict)
    def receive_snapshot(self,snapshot):
        self.last_snapshot_at=time.monotonic()
        previous=self.current_snapshot
        self.current_snapshot=snapshot
        if snapshot.get("monitor_session") and snapshot.get("monitor_session")!=previous.get("monitor_session"):
            self.history_offset=0
            self.current_session_only.setChecked(True)
        if not self.loaded and snapshot.get("config"):
            self.load_config(snapshot["config"])
        elif snapshot.get("config"):
            # Credentials can be changed without overwriting unsaved text fields.
            for channel,widgets in self.channel_widgets.items():
                ref=snapshot["config"].get("channels",{}).get(channel,{}).get("credential_ref","")
                self.config.setdefault("channels",{}).setdefault(channel,{})["credential_ref"]=ref
                widgets["state"].setText("Session-only credential (not persistent)" if ref.startswith("session:") else "Windows credential saved" if ref else "No credential saved")
        monitoring=bool(snapshot.get("monitoring"))
        alerts=bool(snapshot.get("alerts"))
        self.monitor_button.setText("Stop monitoring" if monitoring else "Start monitoring")
        self.alerts_button.setText("Stop alerts" if alerts else "Start alerts")
        self.monitor_button.setEnabled(self.loaded)
        self.alerts_button.setEnabled(self.loaded)
        status="Monitoring running" if monitoring else "Monitoring stopped"
        status+="  ·  External alerts armed" if alerts else "  ·  External alerts off"+(" — detection and history continue" if monitoring else "")
        if alerts and not monitoring:
            status+="; waiting for monitoring"
        session=snapshot.get("monitor_session")
        outstanding=sum(1 for event in snapshot.get("events",[]) if session and event.get("monitor_session")==session and not event.get("acknowledged") and str(event.get("severity","")).lower() in ("error","critical"))
        if outstanding:
            status+=f"  ·  {outstanding} unacknowledged fault(s)"
        if snapshot.get("demo"):
            status="DEMO · "+status
        self.banner.setText(status)
        for source,(box,state,path,detail) in self.source_cards.items():
            data=snapshot.get("sources",{}).get(source,{})
            state.setText(str(data.get("state","Stopped")))
            path.setText(str(data.get("path",self.source_panels[source].full_path())))
            settings=snapshot.get("config",{}).get("sources",{}).get(source,{})
            interval=settings.get("interval") or snapshot.get("config",{}).get("poll_seconds",10)
            threshold=settings.get("cycles",30)*interval if settings.get("inactivity_mode","cycles")=="cycles" else settings.get("duration",300)
            detail.setText("\n".join([
                f"Last read: {compact_time(data.get('last_read'))}",
                f"New bytes: {compact_time(data.get('last_bytes'))}",
                f"Record: {compact_time(data.get('last_record'))}",
                f"Log time: {data.get('log_timestamp') or '—'}",
                f"Next check in: {float(data.get('next_check',0) or 0):.1f} s · backlog {data.get('backlog',0):,} B",
                f"Quiet: {float(data.get('quiet_seconds',0) or 0):.0f} s · {data.get('empty_cycles',0)} empty polls",
                f"Watch: {data.get('watch_status') or ('ARMED' if settings.get('expect_activity') else 'NOT ARMED')} · threshold {threshold} s",
                f"Recent errors: {data.get('recent_errors',0)}",
            ]))
            enabled=snapshot.get("config",{}).get("mode","both") in ("both",source)
            box.setEnabled(enabled)
        self.events=snapshot.get("events",[])[:500]
        self.render_events()
        self.render_live()
        if self.tray:
            self.tray.setToolTip(f"ATLAS Watchdog · {'Running' if monitoring else 'Stopped'} · Alerts {'armed' if alerts else 'off'}")
            old_ids={e.get("id") for e in previous.get("events",[])}
            new_faults=[e for e in snapshot.get("events",[]) if e.get("id") not in old_ids and str(e.get("severity","")).lower() in ("error","critical")]
            if self.loaded and self.local_notify.isChecked() and new_faults:
                event=new_faults[0]
                self.tray.showMessage("ATLAS Watchdog · "+str(event.get("source","")).upper(),str(event.get("message",""))[:220],QSystemTrayIcon.MessageIcon.Warning,8000)
        statuses=snapshot.get("channel_status",{})
        channel_summaries=[]
        for channel in ("gmail","telegram"):
            state=statuses.get(channel,{})
            if isinstance(state,dict):
                channel_summaries.append(channel.title()+": "+str(state.get("state","Off"))+(" · last accepted "+str(state["last_success"]) if state.get("last_success") else "")+(" · "+str(state["last_error"]) if state.get("last_error") else ""))
                old_state=previous.get("channel_status",{}).get(channel,{})
                if state.get("test_result") and state.get("test_result")!=old_state.get("test_result"):
                    command="gmail_check" if state["test_result"].startswith("gmail_check:") else "test_channel"
                    self.receive_result(command,{"channel":channel,"result":state["test_result"]})
                if channel=="telegram" and state.get("chats") and state.get("chats")!=old_state.get("chats"):
                    self.receive_result("telegram_chats",{"chats":state["chats"]})
            else:
                channel_summaries.append(channel.title()+": "+str(state))
        self.status.setText(f"Local history · {snapshot.get('pending_count',0)} undelivered item(s)   |   "+"   |   ".join(channel_summaries))
        if bool(snapshot.get("demo"))!=bool(previous.get("demo")):
            self.load_config(snapshot.get("config",self.config))
        self.alerts_button.setEnabled(self.loaded and not snapshot.get("demo",False))
        self.alerts_button.setToolTip("Demo keeps automatic external alerts off. Explicit TEST buttons are available in Delivery." if snapshot.get("demo") else "Arm external sending for future eligible events")
        diagnostics=snapshot.get("diagnostics",[])
        if diagnostics!=getattr(self,"last_diagnostics",None):
            self.last_diagnostics=copy.deepcopy(diagnostics)
            for diagnostic in diagnostics[-3:]:
                self.results.appendPlainText(str(diagnostic))

    def render_events(self):
        selected_id=self.selected_event_id()
        search=self.event_search.text().casefold()
        source=self.event_source.currentData()
        filtered=[]
        for event in self.events[:500]:
            if self.current_session_only.isChecked() and "monitor_session" in self.current_snapshot:
                session=self.current_snapshot["monitor_session"]
                if not session or event.get("monitor_session")!=session:
                    continue
            if event.get("id") in self.display_cleared:
                continue
            if source!="all" and event.get("source")!=source:
                continue
            if self.unacked.isChecked() and event.get("acknowledged"):
                continue
            if search and search not in " ".join(str(event.get(key,"")) for key in ("message","source","severity","level","rule_names")).casefold():
                continue
            filtered.append(event)
        self.visible_events=filtered
        self.table.blockSignals(True)
        self.table.setRowCount(len(filtered))
        restore=-1
        for row,event in enumerate(filtered):
            deliveries=event.get("deliveries",{})
            values=[str(event.get("source","")).upper(),str(event.get("severity",""))+" / "+str(event.get("level","")),compact_time(event.get("receipt_local",event.get("detected_at",""))),event.get("timestamp_original","—"),event.get("message",""),str(event.get("count",1)),self.delivery_text(deliveries.get("gmail","—")),self.delivery_text(deliveries.get("telegram","—")),"Yes" if event.get("acknowledged") else "No",", ".join(event.get("rule_names",event.get("rules",[])))]
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column==1 and str(event.get("severity","")).lower() in ("error","critical"):
                    item.setForeground(QColor("#a82b32"))
                self.table.setItem(row,column,item)
            self.table.setRowHeight(row,32)
            if event.get("id")==selected_id:
                restore=row
        if restore>=0:
            self.table.selectRow(restore)
        elif filtered:
            self.table.selectRow(0)
        self.table.blockSignals(False)
        self.show_details()

    @staticmethod
    def delivery_text(value):
        if isinstance(value,dict):
            return str(value.get("status",value))
        if isinstance(value,list):
            return "; ".join(MainWindow.delivery_text(v) for v in value)
        return str(value)

    def selected_event_id(self):
        row=self.table.currentRow()
        if 0<=row<len(getattr(self,"visible_events",[])):
            return self.visible_events[row].get("id")
        return None

    def show_details(self):
        row=self.table.currentRow()
        if not 0<=row<len(getattr(self,"visible_events",[])):
            return
        event=self.visible_events[row]
        fields=[("Complete message",event.get("message")),("Source",str(event.get("source","")).upper()),("Alert severity / logged level",str(event.get("severity",""))+" / "+str(event.get("level",""))),("Event ID",event.get("id")),("Full path",event.get("path")),("Historical",event.get("historical",False)),("Logged timestamp (as recorded)",event.get("timestamp_original")),("Detection time",event.get("receipt_local")),("Matched rules",event.get("rule_names",event.get("rules",[]))),("Occurrence count",event.get("count",1)),("Original source line",event.get("raw_line")),("Parse / read diagnostic",event.get("diagnostic")),("Preceding context (same source)",event.get("context",[])),("Delivery status",event.get("deliveries",{})),("Delivery attempts (provider acceptance evidence)",event.get("attempts",[]))]
        text=[]
        for title,value in fields:
            if isinstance(value,(dict,list)):
                value=json.dumps(value,ensure_ascii=False,indent=2)
            text.append(title+":\n"+str(value or "—"))
        self.details.setPlainText("\n\n".join(text))

    def render_live(self):
        search=self.live_search.text().casefold()
        for source,view in self.live_views.items():
            if self.matched_only.isChecked():
                lines=[e.get("raw_line") or e.get("message","") for e in reversed(self.current_snapshot.get("events",[])[:500]) if e.get("source")==source]
            else:
                lines=self.current_snapshot.get("live",{}).get(source,[])[-1000:]
            lines=[str(line) for line in lines if not search or search in str(line).casefold()]
            text="\n".join(lines)
            if text==view.toPlainText():
                continue
            scroll=view.verticalScrollBar().value()
            view.setPlainText(text)
            view.verticalScrollBar().setValue(scroll if self.pause_scroll.isChecked() else view.verticalScrollBar().maximum())

    def acknowledge(self):
        event_id=self.selected_event_id()
        if event_id:
            self.send("acknowledge",{"id":event_id})

    def older_history(self):
        self.current_session_only.setChecked(False)
        self.history_offset+=200
        self.send("history",{"offset":self.history_offset,"limit":200})

    def latest_events(self):
        self.current_session_only.setChecked(True)
        self.history_offset=0
        self.send("history",{"offset":0,"limit":300})
        self.display_cleared.clear()
        self.events=self.current_snapshot.get("events",[])[:500]
        self.render_events()

    def clear_display(self):
        self.display_cleared.update(event.get("id") for event in self.events)
        self.render_events()
        self.details.clear()

    def export_history(self):
        path,selected=QFileDialog.getSaveFileName(self,"Export event history","atlas-events.json","JSON (*.json);;CSV (*.csv)")
        if path:
            include=QMessageBox.question(self,"Scientific context","Include raw source lines, full paths and preceding scientific context? Choose No to export event summaries only.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
            self.send("export_history",{"path":path,"format":"csv" if "CSV" in selected else "json","include_context":include})

    def export_config(self):
        path,_=QFileDialog.getSaveFileName(self,"Export configuration without secrets","atlas-config.json","JSON (*.json)")
        if path:
            self.apply_settings()
            self.send("export_config",{"path":path})

    def export_support(self):
        path,_=QFileDialog.getSaveFileName(self,"Export local support bundle","atlas-support.json","JSON (*.json)")
        if path:
            include=QMessageBox.question(self,"Support bundle privacy","Include raw scientific messages, full paths and source context? Choose No for redacted identifiers and messages. The bundle is saved locally and is not uploaded.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
            self.send("support_bundle",{"path":path,"include_context":include})

    def import_config(self):
        path,_=QFileDialog.getOpenFileName(self,"Import configuration (credentials must be re-entered)","","JSON (*.json)")
        if path:
            self.send("import_config",{"path":path})

    def delete_history(self):
        if QMessageBox.warning(self,"Delete stored history","Delete local stored event history? This is separate from clearing the current display.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.send("clear_history")

    @Slot(str,object)
    def receive_result(self,command,result):
        self.results.appendPlainText(command.upper()+"\n"+(json.dumps(result,ensure_ascii=False,indent=2,default=str) if not isinstance(result,str) else result)+"\n")
        if command in ("test_channel","test_rule","validate","error","telegram_check","telegram_chats","gmail_check") or isinstance(result,dict) and result.get("error"):
            self.view_tabs.setCurrentWidget(self.results)
        if command=="history" and (isinstance(result,list) or isinstance(result,dict) and "events" in result):
            self.events=(result.get("events",[]) if isinstance(result,dict) else result or [])[:500]
            self.render_events()
        if command=="import_config" and isinstance(result,dict) and not result.get("error"):
            config=result.get("config")
            if config:
                self.load_config(config)
            else:
                self.loaded=False
        if command=="configure" and isinstance(result,dict) and result.get("config"):
            self.load_config(result["config"])
        if command=="configure" and self.pending_start:
            if not (isinstance(result,dict) and result.get("error")):
                self.send("start",self.pending_start)
            self.pending_start=None
        if command=="configure" and self.pending_test_channel:
            if not (isinstance(result,dict) and result.get("error")):
                self.send("test_channel",{"channel":self.pending_test_channel})
            self.pending_test_channel=None
        if command=="configure" and self.pending_gmail_check:
            if not (isinstance(result,dict) and result.get("error")):
                self.send("gmail_check",{"channel":"gmail"})
            self.pending_gmail_check=False
        if command=="telegram_chats":
            chats=result.get("chats",[]) if isinstance(result,dict) else result if isinstance(result,list) else []
            if chats:
                titles=[str(chat.get("name") or chat.get("title") or chat.get("first_name") or chat.get("username") or "Private chat")+" · "+str(chat.get("id",chat.get("chat_id",""))) for chat in chats]
                choice,ok=QInputDialog.getItem(self,"Choose the intended private Telegram chat","Select your chat deliberately:",titles,0,False)
                if ok:
                    chat=chats[titles.index(choice)]
                    self.channel_widgets["telegram"]["chat_id"].setText(str(chat.get("id",chat.get("chat_id",""))))

    def check_worker_health(self):
        age=time.monotonic()-self.last_snapshot_at
        if age>15:
            self.banner.setText(f"Coverage warning — watchdog worker has not reported for {age:.0f} seconds. Source health is unknown.")

    def activate(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self,event):
        if self.shutting_down:
            event.accept()
        elif self.tray and self.minimize_close.isChecked():
            self.hide()
            self.tray.showMessage("ATLAS Watchdog remains running","Use the tray menu to show the window or Quit and stop monitoring.",QSystemTrayIcon.MessageIcon.Information,4000)
            event.ignore()
        else:
            self.quit_app()
            event.accept()

    def shutdown(self):
        if self.shutting_down:
            return
        self.shutting_down=True
        self.health_timer.stop()
        if self.tray:
            self.tray.hide()
        self.shutdown_requested.emit()
        # Process queued signals while waiting, so shutdown never touches worker-owned state.
        deadline=time.monotonic()+35
        while self.thread.isRunning() and time.monotonic()<deadline:
            QApplication.processEvents()
            self.thread.wait(20)
        if self.thread.isRunning():
            # Network transports have bounded timeouts. Leave the thread alive until it exits.
            self.thread.finished.connect(QApplication.instance().quit)

    def quit_app(self):
        self.shutdown()
        self.close()
        if not self.thread.isRunning():
            QApplication.instance().quit()


STYLE="""
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #213444; }
QMainWindow, QDialog { background: #f3f6f8; }
QLabel#brand { font-size: 20pt; font-weight: 700; color: #164f67; padding: 4px 0; }
QLabel#muted { color: #576b78; font-size: 9pt; }
QLabel#banner { background: #e3eef2; color: #164f67; border: 1px solid #b8d0da; border-radius: 7px; padding: 12px; font-weight: 600; }
QLabel#cardState { font-size: 15pt; font-weight: 600; color: #164f67; }
QGroupBox { border: 1px solid #d3dfe5; border-radius: 7px; margin-top: 10px; padding: 12px 8px 8px; background: white; }
QGroupBox::title { subcontrol-origin: margin; padding: 0 7px; color: #164f67; font-weight: 600; }
QPushButton { background: white; border: 1px solid #b9c9d2; border-radius: 5px; padding: 7px 10px; }
QPushButton:hover { background: #eaf2f5; border-color: #7096a6; }
QPushButton:pressed { background: #d5e7ee; }
QPushButton#primary { background: #164f67; color: white; border-color: #164f67; font-weight: 600; }
QPushButton#primary:hover { background: #20627e; }
QPushButton:disabled { color: #81929c; background: #e4e9ed; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QListWidget { background: white; border: 1px solid #bfced6; border-radius: 4px; padding: 5px; selection-background-color: #d0e8f1; selection-color: #163b4e; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #287c9e; }
QTabWidget::pane { border: 1px solid #d5dfe5; background: #f8fafb; border-radius: 4px; }
QTabBar::tab { padding: 9px 11px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #164f67; border-bottom: 2px solid #247797; font-weight: 600; background: #f8fafb; }
QTableWidget { background: white; alternate-background-color: #f3f7f9; border: 1px solid #d4dfe5; gridline-color: #e8eef1; }
QHeaderView::section { background: #eaf0f4; border: none; border-bottom: 1px solid #ccd9e0; padding: 8px; font-weight: 600; }
QTableWidget::item:selected { background: #d4eaf3; color: #153b4c; }
QScrollArea { background: transparent; }
QSplitter::handle { background: #dbe4ea; }
"""


class SingleInstance:
    """Crash-safe OS lock plus local IPC; no duplicate readers or alert queues."""
    def __init__(self,state_dir):
        # QLockFile creates only an application-state lock, never source directories.
        from .config import ConfigStore, safe_destination
        state_dir=safe_destination(state_dir,ConfigStore(Path(state_dir)).load(),state=True)
        Path(state_dir).mkdir(parents=True,exist_ok=True)
        import hashlib
        self.name="ATLASWatchdog-"+hashlib.sha256(str(Path(state_dir).resolve()).casefold().encode()).hexdigest()[:24]
        self.lock=QLockFile(str(Path(state_dir)/"instance.lock"))
        self.lock.setStaleLockTime(0)
        self.server=None

    def acquire(self):
        if self.lock.tryLock(0):
            QLocalServer.removeServer(self.name)
            self.server=QLocalServer()
            return self.server.listen(self.name)
        socket=QLocalSocket()
        socket.connectToServer(self.name)
        if socket.waitForConnected(1500):
            socket.write(b"activate")
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
        return False

    def connect_window(self,window):
        def activate():
            while self.server.hasPendingConnections():
                connection=self.server.nextPendingConnection()
                connection.disconnectFromServer()
                connection.deleteLater()
            window.activate()
        self.server.newConnection.connect(activate)


def run(state_dir=None,demo=False,smoke_test=False,screenshot=None):
    app=QApplication.instance() or QApplication([])
    app.setApplicationName("ATLAS Watchdog")
    app.setOrganizationName("ATLASWatchdog")
    app.setWindowIcon(icon())
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    state_dir=state_dir or str(Path(os.environ.get("LOCALAPPDATA",str(Path.home()/".local"/"share")))/"ATLASWatchdog")
    instance=SingleInstance(state_dir)
    if not instance.acquire():
        return 0
    window=MainWindow(state_dir=state_dir,enable_tray=not smoke_test)
    instance.connect_window(window)
    window.show()
    if smoke_test:
        QTimer.singleShot(700,window.toggle_monitor)
        QTimer.singleShot(1200,window.toggle_monitor)
    if demo:
        QTimer.singleShot(1600 if smoke_test else 600,lambda:window.send("demo",{"action":"start"}))
    if screenshot:
        def capture():
            from .config import safe_destination
            try:
                destination=safe_destination(screenshot,window.current_snapshot.get("config",window.config))
                destination.parent.mkdir(parents=True,exist_ok=True)
                if window.table.rowCount():
                    window.table.selectRow(0)
                    window.show_details()
                window.grab().save(str(destination))
            except (OSError,ValueError):
                window.receive_result("screenshot",{"error":"Screenshot destination must be writable and outside monitored source / ATLAS directories."})
        QTimer.singleShot(7000 if smoke_test else 5000,capture)
    if smoke_test:
        QTimer.singleShot(8000,window.quit_app)
    app.aboutToQuit.connect(window.shutdown)
    result=app.exec()
    instance.lock.unlock()
    return result
