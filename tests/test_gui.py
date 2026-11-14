"""Desktop tests use temporary source logs, a worker-owned controller and fake providers."""
import copy
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

from atlas_watchdog.config import defaults
from atlas_watchdog.controller import Controller
from atlas_watchdog.gui import MainWindow, RuleDialog, SingleInstance
from atlas_watchdog.notifications import DeliveryResult


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def until(app,predicate,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Qt condition not reached")


@pytest.fixture
def window(app,tmp_path):
    item=MainWindow(state_dir=str(tmp_path/"state"),enable_tray=False)
    item.show()
    until(app,lambda:item.loaded)
    yield item
    item.shutdown()
    item.close()


def test_real_worker_paths_rules_error_attribution_and_independent_controls(app,window,tmp_path):
    source_dir=tmp_path/"sources"
    source_dir.mkdir()
    engine=source_dir/"engine.log"
    execution=source_dir/"execution.log"
    engine.write_bytes(b"")
    execution.write_bytes(b"")
    for source,path in (("engine",engine),("execution",execution)):
        window.source_panels[source].folder.setText(str(path.parent))
        window.source_panels[source].filename.setText(path.name)
    window.poll.setValue(1)
    QTest.mouseClick(window.monitor_button,Qt.MouseButton.LeftButton)
    until(app,lambda:window.current_snapshot.get("monitoring") and window.current_snapshot["sources"]["execution"]["last_read"])
    assert not window.current_snapshot["alerts"]
    window.send("validate",{"source":"engine","path":str(engine)})
    message="The connection or the microscope does not respond. <b>plain text</b>"
    with execution.open("ab") as out:
        out.write(("13/11/2026\t12:00:01.123\tError\tImaging\t\t"+message+"\r\n").encode())
    until(app,lambda:any(e.get("message")==message for e in window.events))
    event=next(e for e in window.events if e.get("message")==message)
    assert event["source"]=="execution"
    assert "EXECUTION"==window.table.item(0,0).text()
    window.table.selectRow(0)
    assert message in window.details.toPlainText()
    assert "<b>plain text</b>" in window.details.toPlainText()
    assert not window.current_snapshot["alerts"]
    window.acknowledge()
    until(app,lambda:any(e.get("id")==event["id"] and e.get("acknowledged") for e in window.events))
    window.channel_widgets["gmail"]["enabled"].setChecked(True)
    window.apply_settings()
    until(app,lambda:window.current_snapshot["config"]["channels"]["gmail"]["enabled"])
    QTest.mouseClick(window.alerts_button,Qt.MouseButton.LeftButton)
    until(app,lambda:window.current_snapshot.get("alerts"))
    QTest.mouseClick(window.monitor_button,Qt.MouseButton.LeftButton)
    until(app,lambda:not window.current_snapshot.get("monitoring"))
    assert window.current_snapshot["alerts"]
    assert "waiting for monitoring" in window.banner.text()
    assert "read-only access ok" in window.results.toPlainText().lower()


def test_start_alerts_explains_disabled_channel_after_successful_test(app,window,monkeypatch):
    notices=[]
    monkeypatch.setattr(QMessageBox,"information",lambda _parent,title,message:notices.append((title,message)))
    snapshot=copy.deepcopy(window.current_snapshot)
    snapshot["alerts"]=False
    snapshot["channel_status"]["gmail"]["test_result"]="TEST gmail: accepted"
    window.receive_snapshot(snapshot)
    QTest.mouseClick(window.alerts_button,Qt.MouseButton.LeftButton)
    app.processEvents()
    assert not window.current_snapshot["alerts"]
    assert notices and "Enable Gmail or Telegram" in notices[0][1]
    assert "TEST" in notices[0][1]


def test_separate_rules_and_durable_history_clear_display(app,window):
    execution=copy.deepcopy(window.config["rules"]["execution"])
    window.rule_source.setCurrentIndex(window.rule_source.findData("engine"))
    first=window.rule_list.item(0)
    first.setCheckState(Qt.CheckState.Unchecked)
    assert not window.config["rules"]["engine"][0]["enabled"]
    assert window.config["rules"]["execution"]==execution
    snapshot=copy.deepcopy(window.current_snapshot)
    snapshot["monitor_session"]="test-session"
    snapshot["events"]=[dict(id="abc",source="engine",severity="error",level="Error",message="Error without keyword",receipt_local="today",rule_names=["level"],count=1)]
    snapshot["events"][0]["monitor_session"]="test-session"
    window.receive_snapshot(snapshot)
    assert window.table.rowCount()==1
    window.clear_display()
    assert window.table.rowCount()==0
    assert len(window.events)==1
    window.latest_events()
    assert window.table.rowCount()==1


def test_rule_editor_validation_and_channel_guidance(app,window):
    dialog=RuleDialog(parent=window)
    dialog.validate()
    assert dialog.result()!=QDialog.DialogCode.Accepted
    assert "rule name" in dialog.error.text()
    dialog.name.setText("A fault")
    dialog.validate()
    assert "nonempty" in dialog.error.text()
    dialog.pattern.setText("cannot grab")
    dialog.validate()
    assert dialog.result()==QDialog.DialogCode.Accepted
    rule=dialog.value()
    assert rule["mode"]=="contains" and rule["scope"]=="message"
    assert rule["channels"]==["gmail","telegram"]
    assert window.channel_widgets["gmail"]["secret"].echoMode()==QLineEdit.EchoMode.Password
    assert window.channel_widgets["telegram"]["secret"].echoMode()==QLineEdit.EchoMode.Password
    assert window.poll.minimum()==1 and window.poll.maximum()==3600
    assert window.source_panels["execution"].heartbeat_seconds.value()==300
    assert not window.source_panels["engine"].expect.isChecked()


def test_current_session_view_hides_stored_past_events_by_default(app,window):
    snapshot=copy.deepcopy(window.current_snapshot)
    snapshot["monitor_session"]="current-session"
    snapshot["events"]=[
        dict(id="new",source="execution",severity="error",level="Info",message="Fresh EHT entry",monitor_session="current-session"),
        dict(id="past",source="execution",severity="error",level="Error",message="Past fault",monitor_session="old-session"),
        dict(id="legacy",source="engine",severity="error",level="Error",message="Older version fault"),
    ]
    window.receive_snapshot(snapshot)
    assert window.current_session_only.isChecked()
    assert [event["id"] for event in window.visible_events]==["new"]
    assert "1 unacknowledged fault(s)" in window.banner.text()
    window.current_session_only.setChecked(False)
    assert len(window.visible_events)==3
    window.current_session_only.setChecked(True)
    window.history_offset=200
    snapshot=copy.deepcopy(snapshot)
    snapshot["monitor_session"]="next-session"
    window.receive_snapshot(snapshot)
    assert window.table.rowCount()==0
    assert window.history_offset==0
    window.older_history()
    assert not window.current_session_only.isChecked()


def test_bounded_plain_text_live_and_event_views(app,window):
    snapshot=copy.deepcopy(window.current_snapshot)
    snapshot["monitor_session"]="test-session"
    snapshot["live"]={"engine":["<script>line %d</script>"%i for i in range(1500)],"execution":[]}
    snapshot["events"]=[dict(id=str(i),source="engine",severity="error",level="Error",message="fault %d"%i,receipt_local="now",rule_names=["fault"],monitor_session="test-session") for i in range(1500)]
    window.receive_snapshot(snapshot)
    assert window.table.rowCount()==500
    assert window.live_views["engine"].document().blockCount()<=1000
    assert "<script>line 1499</script>" in window.live_views["engine"].toPlainText()
    window.live_search.setText("1499")
    assert window.live_views["engine"].toPlainText()=="<script>line 1499</script>"
    window.event_source.setCurrentIndex(window.event_source.findData("execution"))
    assert window.table.rowCount()==0


class FakeSecrets:
    available=False
    def set(self,name,value,persistent=True):
        self.value=value
        return "session:"+name
    def get(self,ref):
        return getattr(self,"value","")
    def delete(self,ref):
        self.value=""


class SlowTransport:
    def send(self,*args):
        time.sleep(.35)
        return DeliveryResult("accepted","Fake provider accepted TEST")


def test_explicit_test_sends_off_controls_and_ui_stays_responsive(app,tmp_path):
    def factory(state_dir):
        return Controller(state_dir,transports={"gmail":SlowTransport(),"telegram":SlowTransport()},secrets=FakeSecrets())
    window=MainWindow(controller_factory=factory,state_dir=str(tmp_path/"slow"),enable_tray=False)
    try:
        until(app,lambda:window.loaded)
        gmail=window.channel_widgets["gmail"]
        gmail["sender"].setText("watchdog@gmail.com")
        gmail["recipients"].setText("test@example.org")
        window.send("credential",{"channel":"gmail","secret":"mock-secret","persistent":False})
        window.apply_settings()
        window.send("test_channel",{"channel":"gmail"})
        started=time.monotonic()
        window.event_search.setText("responsive while provider waits")
        app.processEvents()
        assert time.monotonic()-started<.25
        until(app,lambda:"Fake provider accepted TEST" in window.results.toPlainText())
        assert not window.current_snapshot["monitoring"] and not window.current_snapshot["alerts"]
    finally:
        window.shutdown()
        window.close()


def test_crash_safe_single_instance_lock(app,tmp_path):
    one=SingleInstance(tmp_path/"instance")
    two=SingleInstance(tmp_path/"instance")
    try:
        assert one.acquire()
        assert not two.acquire()
    finally:
        if one.server:
            one.server.close()
        one.lock.unlock()


def test_single_instance_refuses_source_directory_before_lock_write(app,tmp_path):
    import json
    source=tmp_path/"logs"
    source.mkdir()
    config=defaults()
    config["sources"]["execution"]["folder"]=str(source)
    (source/"config.json").write_text(json.dumps(config),encoding="utf-8")
    with pytest.raises(ValueError,match="outside source"):
        SingleInstance(source)
    assert not (source/"instance.lock").exists()


def test_invalid_configuration_does_not_start_old_sources(app,window,tmp_path):
    window.source_panels["engine"].filename.setText("../unsafe.log")
    window.toggle_monitor()
    until(app,lambda:"filename" in window.results.toPlainText())
    assert not window.current_snapshot["monitoring"]


def test_failed_configuration_never_sends_test_to_previous_recipient(app,tmp_path):
    class RecordingTransport:
        def __init__(self):
            self.recipients=[]
        def send(self,config,secret,recipient,*args):
            self.recipients.append(recipient)
            return DeliveryResult("accepted","Fake accepted")
    transport=RecordingTransport()
    def factory(state_dir):
        return Controller(state_dir,transports={"gmail":transport,"telegram":RecordingTransport()},secrets=FakeSecrets())
    window=MainWindow(controller_factory=factory,state_dir=str(tmp_path/"test-gate"),enable_tray=False)
    try:
        until(app,lambda:window.loaded)
        gmail=window.channel_widgets["gmail"]
        gmail["sender"].setText("watchdog@gmail.com")
        gmail["recipients"].setText("old@example.org")
        window.send("credential",{"channel":"gmail","secret":"mock-only","persistent":False})
        window.apply_settings()
        until(app,lambda:window.current_snapshot.get("config",{}).get("channels",{}).get("gmail",{}).get("recipients")==["old@example.org"])
        window.results.clear()
        gmail["recipients"].setText("invalid recipient")
        window.test_channel("gmail")
        until(app,lambda:window.pending_test_channel is None)
        assert "error" in window.results.toPlainText().lower()
        assert transport.recipients==[]
        assert not window.current_snapshot["alerts"]
    finally:
        window.shutdown()
        window.close()


def test_no_email_smtp_check_is_gated_on_saved_settings(app,tmp_path):
    class Probe:
        def __init__(self):self.calls=[]
        def check_connection(self,config):
            self.calls.append(config["port"])
            return dict(status="connection_ok",port=config["port"],authenticated=False,email_sent=False)
        def send(self,*args):raise AssertionError("Must not send email during check")
    probe=Probe()
    def factory(state_dir):
        return Controller(state_dir,transports={"gmail":probe,"telegram":Probe()})
    window=MainWindow(controller_factory=factory,state_dir=str(tmp_path/"probe"),enable_tray=False)
    try:
        until(app,lambda:window.loaded)
        widgets=window.channel_widgets["gmail"]
        widgets["port"].setCurrentIndex(widgets["port"].findData("587"))
        window.check_gmail_connection()
        until(app,lambda:window.current_snapshot.get("channel_status",{}).get("gmail",{}).get("connection_check",{}).get("status")=="connection_ok")
        assert probe.calls==[587]
        assert not window.current_snapshot["monitoring"] and not window.current_snapshot["alerts"]
        assert window.current_snapshot["channel_status"]["gmail"]["last_success"]==""
        widgets["recipients"].setText("invalid address")
        window.check_gmail_connection()
        until(app,lambda:not window.pending_gmail_check)
        assert probe.calls==[587]
    finally:
        window.shutdown()
        window.close()
