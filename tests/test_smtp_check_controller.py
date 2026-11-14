from atlas_watchdog.controller import Controller
from atlas_watchdog.notifications import DeliveryResult


class NetworkOnly:
    def __init__(self): self.checked=[]
    def check_connection(self,config):
        self.checked.append(config["port"])
        return dict(status="connection_ok",port=config["port"],authenticated=False,email_sent=False)
    def send(self,*args):
        raise AssertionError("A network check must never send")


def test_controller_connection_check_needs_no_credential_and_does_not_mark_acceptance(tmp_path):
    gmail=NetworkOnly()
    c=Controller(tmp_path/"state",transports={"gmail":gmail,"telegram":NetworkOnly()})
    try:
        assert not c.config["channels"]["gmail"]["credential_ref"]
        c.handle("gmail_check")
        c.jobs[0][2].result(timeout=2)
        c.tick()
        status=c.snapshot()["channel_status"]["gmail"]
        assert status["connection_check"]["status"]=="connection_ok"
        assert status["last_success"]==""
        assert not c.monitoring and not c.alerts
        assert gmail.checked==[465]
    finally: c.close()


def test_explicit_test_preserves_retry_result_without_automatic_resend(tmp_path):
    class RetryTransport(NetworkOnly):
        def send(self,*args):return DeliveryResult("retry","Simulated transient timeout")
    c=Controller(tmp_path/"state",transports={"gmail":RetryTransport(),"telegram":NetworkOnly()})
    try:
        c.config["channels"]["gmail"].update(sender="sender@example.com",recipients=["recipient@example.com"])
        c.handle("credential",dict(channel="gmail",secret="mock-test-only",persistent=False))
        c.handle("test_channel",dict(channel="gmail"))
        c.jobs[0][2].result(timeout=2)
        c.tick()
        text=c.channel_status["gmail"]["test_result"]
        assert "TEST gmail: retry" in text and "not automatically resent" in text
        assert not c.jobs and not c.monitoring and not c.alerts
    finally:c.close()
