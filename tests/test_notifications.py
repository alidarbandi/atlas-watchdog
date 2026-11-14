"""All provider requests use injected clients; no credentials or real delivery."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import socket
import smtplib
import ssl
from uuid import uuid4

import httpx
import pytest

from atlas_watchdog.notifications import (
    GmailTransport, TelegramTransport, NotificationSetupError, redact,
)
from atlas_watchdog.secrets import SecretStore


TOKEN = "123456789:unit-test-fake-token-only"


class FakeSMTP:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.mail_code = 250
        self.rcpt_code = 250
        self.data_code = 250
        self.closed = False

    def ehlo(self):
        self.calls.append("ehlo")
        return 250, b"OK"

    def has_extn(self, name):
        return name in {"auth", "starttls"}

    def starttls(self, *, context):
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        self.calls.append("starttls")

    def login(self, sender, secret):
        self.calls.append(("login", sender))
        assert secret == "fake-app-password"
        if self.fail and self.fail[0] == "login":
            raise self.fail[1]

    def mail(self, sender):
        self.calls.append(("mail", sender))
        return self.mail_code, b"response"

    def rcpt(self, recipient):
        self.calls.append(("rcpt", recipient))
        return self.rcpt_code, b"response"

    def data(self, payload):
        self.calls.append(("data", payload))
        if self.fail and self.fail[0] == "data":
            raise self.fail[1]
        return self.data_code, b"accepted"

    def close(self):
        self.closed = True


def smtp_client(monkeypatch, fake, *, port=465):
    def factory(host, actual_port, *, timeout, context=None):
        assert host == "smtp.gmail.com"
        assert timeout == 15
        assert actual_port == port
        if port == 465:
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        return fake
    monkeypatch.setattr(smtplib, "SMTP_SSL" if port == 465 else "SMTP", factory)


def send_gmail(fake, monkeypatch, **kwargs):
    port = kwargs.pop("port", 465)
    smtp_client(monkeypatch, fake, port=port)
    return GmailTransport().send({"sender": "watchdog@example.com", "port": port},
                                 "fake-app-password", kwargs.get("recipient", "recipient@example.com"),
                                 "TEST event=123", "ENGINE Error: example <safe> text")


def test_gmail_acceptance_verified_tls_and_single_recipient(monkeypatch):
    fake = FakeSMTP()
    result = send_gmail(fake, monkeypatch)
    assert result.status == "accepted" and result.provider_id
    assert fake.closed
    assert [call for call in fake.calls if isinstance(call, tuple) and call[0] == "rcpt"] == [("rcpt", "recipient@example.com")]
    payload = next(call[1] for call in fake.calls if isinstance(call, tuple) and call[0] == "data")
    assert b"TEST event=123" in payload and b"fake-app-password" not in payload


def test_gmail_starttls_precedes_authentication(monkeypatch):
    fake = FakeSMTP()
    assert send_gmail(fake, monkeypatch, port=587).status == "accepted"
    assert fake.calls[:3] == ["ehlo", "starttls", "ehlo"]
    assert fake.calls[3][0] == "login"


@pytest.mark.parametrize(("stage", "error", "expected"), [
    ("login", smtplib.SMTPAuthenticationError(535, b"secret provider text"), "failed"),
    ("login", TimeoutError("fake-app-password"), "retry"),
    ("login", ssl.SSLCertVerificationError("secret"), "failed"),
    ("data", TimeoutError("fake-app-password"), "unknown"),
    ("data", smtplib.SMTPServerDisconnected("lost"), "unknown"),
    ("data", ssl.SSLError("broken"), "unknown"),
    ("data", smtplib.SMTPDataError(451, b"throttled"), "retry"),
    ("data", smtplib.SMTPDataError(550, b"rejected"), "failed"),
])
def test_gmail_failure_categories_are_secret_free(monkeypatch, stage, error, expected):
    fake = FakeSMTP()
    fake.fail = stage, error
    result = send_gmail(fake, monkeypatch)
    assert result.status == expected
    assert "fake-app-password" not in result.detail and "secret provider text" not in result.detail
    assert fake.closed


def test_gmail_rejected_recipient_cannot_resend_accepted_recipient(monkeypatch):
    fake = FakeSMTP()
    first = send_gmail(fake, monkeypatch)
    fake.rcpt_code = 550
    second = send_gmail(fake, monkeypatch, recipient="other@example.com")
    assert first.status == "accepted" and second.status == "failed"
    assert sum(isinstance(c, tuple) and c[0] == "data" for c in fake.calls) == 1


@pytest.mark.parametrize("port", [465,587])
def test_smtp_connection_check_does_not_authenticate_or_send(monkeypatch,port):
    fake=FakeSMTP()
    smtp_client(monkeypatch,fake,port=port)
    result=GmailTransport().check_connection({"port":port})
    assert result["status"]=="connection_ok" and result["port"]==port
    assert not result["authenticated"] and not result["email_sent"]
    assert not any(isinstance(call,tuple) for call in fake.calls)
    assert fake.closed
    if port==587:
        assert fake.calls==["ehlo","starttls","ehlo"]


@pytest.mark.parametrize(("error","status","fragment"),[
    (smtplib.SMTPNotSupportedError("fake-app-password"),"failed","capability"),
    (smtplib.SMTPException("fake-app-password"),"failed","protocol"),
    (smtplib.SMTPServerDisconnected("fake-app-password"),"retry","server closed"),
    (socket.gaierror(-2,"fake-app-password"),"retry","DNS lookup"),
    (TimeoutError("fake-app-password"),"retry","Timed out"),
    (ConnectionRefusedError(10061,"fake-app-password"),"retry","Connection refused"),
])
def test_smtp_setup_failures_report_safe_stage_and_endpoint(monkeypatch,error,status,fragment):
    def fail(*args,**kwargs):
        raise error
    monkeypatch.setattr(smtplib,"SMTP_SSL",fail)
    result=GmailTransport().send({"sender":"watchdog@example.com","port":465},"fake-app-password","recipient@example.com","TEST","x")
    assert result.status==status
    assert fragment.lower() in result.detail.lower()
    assert "smtp.gmail.com:465" in result.detail and "connection" in result.detail
    assert "fake-app-password" not in result.detail


def test_authentication_timeout_is_not_misreported_as_connection_failure(monkeypatch):
    fake=FakeSMTP()
    fake.fail="login",TimeoutError("fake-app-password")
    result=send_gmail(fake,monkeypatch)
    assert result.status=="retry" and "during authentication" in result.detail
    assert "fake-app-password" not in result.detail


def test_connection_check_cannot_claim_success_without_smtp_auth_support(monkeypatch):
    fake=FakeSMTP()
    fake.has_extn=lambda name:False
    smtp_client(monkeypatch,fake)
    result=GmailTransport().check_connection({"port":465})
    assert result["status"]=="failed" and "capability" in result["detail"]
    assert not result["authenticated"] and not result["email_sent"]


@pytest.mark.parametrize("recipient", ["bad", "user@example.com\r\nBcc: stolen@example.com", "Name <user@example.com>"])
def test_gmail_rejects_bad_addresses_before_network(monkeypatch, recipient):
    def denied(*args, **kwargs):
        pytest.fail("Network constructor must not run")
    monkeypatch.setattr(smtplib, "SMTP_SSL", denied)
    assert GmailTransport().send({"sender": "watchdog@example.com"}, "test", recipient, "x", "x").status == "failed"


def telegram(body=None, status=200, handler=None):
    def respond(request):
        assert str(request.url).startswith("https://api.telegram.org/bot")
        assert request.method == "POST"
        if handler:
            return handler(request)
        return httpx.Response(status, json=body)
    return TelegramTransport(httpx.Client(transport=httpx.MockTransport(respond)))


def test_telegram_plain_text_and_bounded_payload():
    def handler(request):
        body = json.loads(request.content)
        assert body["chat_id"] == "1234"
        assert "parse_mode" not in body and "allow_paid_broadcast" not in body
        assert body["disable_notification"] is False
        assert len(body["text"].encode("utf-16-le")) // 2 <= 3500
        assert "event-id=123" in body["text"] and "Truncated" in body["text"]
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
    result = telegram(handler=handler).send({}, TOKEN, "1234", "TEST event-id=123", "🤖" * 6000)
    assert result.status == "accepted" and result.provider_id == "7"


@pytest.mark.parametrize(("http_status", "body", "expected"), [
    (401, {"ok": False, "error_code": 401}, "failed"),
    (403, {"ok": False, "error_code": 403}, "failed"),
    (429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 66}}, "retry"),
    (503, {"ok": False, "error_code": 503}, "retry"),
    (200, {"ok": False, "error_code": 400, "description": TOKEN}, "failed"),
    (200, [], "unknown"),
])
def test_telegram_failures(http_status, body, expected):
    result = telegram(body, http_status).send({}, TOKEN, "1234", "TEST", "test")
    assert result.status == expected and TOKEN not in result.detail
    if http_status == 429:
        assert result.retry_after == 66


@pytest.mark.parametrize(("error_type", "expected"), [(httpx.ConnectTimeout, "retry"), (httpx.ReadTimeout, "unknown")])
def test_telegram_timeout_is_redacted_and_uncertainty_is_preserved(error_type, expected):
    def handler(request):
        raise error_type(f"Failed {request.url}", request=request)
    result = telegram(handler=handler).send({}, TOKEN, "1234", "TEST", "test")
    assert result.status == expected and TOKEN not in result.detail


def test_telegram_invalid_json_submission_is_unknown():
    def handler(request):
        return httpx.Response(200, content=b"not JSON")
    assert telegram(handler=handler).send({}, TOKEN, "1234", "TEST", "x").status == "unknown"


def test_bot_check_and_private_chat_discovery_never_selects_first():
    def handler(request):
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 6, "username": "demo_bot", "is_bot": True}})
        body = json.loads(request.content)
        assert body == {"limit": 100, "timeout": 0}
        return httpx.Response(200, json={"ok": True, "result": [
            {"message": {"chat": {"id": 1, "type": "private", "first_name": "Alice"}}},
            {"message": {"chat": {"id": 2, "type": "private", "first_name": "Bob"}}},
            {"message": {"chat": {"id": -3, "type": "group", "title": "ignore"}}},
            {"message": {"chat": {"id": 1, "type": "private", "first_name": "Alice"}}},
        ]})
    transport = telegram(handler=handler)
    assert transport.get_me(TOKEN)["username"] == "demo_bot"
    assert transport.find_chats(TOKEN) == [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]


def test_telegram_existing_webhook_conflict_is_explicit():
    transport = telegram({"ok": False, "error_code": 409}, 409)
    with pytest.raises(NotificationSetupError, match="webhook"):
        transport.find_chats(TOKEN)


def test_token_redaction_in_exception_and_httpx_info_log(caplog):
    assert TOKEN not in redact(f"request https://api.telegram.org/bot{TOKEN}/sendMessage")
    assert "secret" not in redact("app password secret", ["secret"])
    with caplog.at_level(logging.INFO, logger="httpx"):
        telegram({"ok": True, "result": {}}).send({}, TOKEN, "1234", "TEST", "test")
    assert TOKEN not in caplog.text


def test_session_secret_storage_has_no_disk_fallback():
    store = SecretStore()
    reference = store.set("unit-test-session", "fake-secret", persistent=False)
    assert reference == "session:unit-test-session"
    assert store.get(reference) == "fake-secret"
    assert SecretStore().get(reference) == ""
    store.delete(reference)
    assert store.get(reference) == ""


def test_unavailable_secret_storage_returns_explicit_session_reference():
    store = SecretStore()
    store.available = False
    reference = store.set("unit-test-unavailable", "fake-secret")
    assert reference.startswith("session:") and store.get(reference) == "fake-secret"


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager integration")
def test_windows_secret_roundtrip_and_remove():
    store = SecretStore()
    if not store.available:
        pytest.skip("Credential Manager unavailable in this Windows logon session")
    name = "unit-test-" + uuid4().hex
    reference = store.set(name, "fake-µ-secret")
    if not reference.startswith("wincred:"):
        pytest.skip("This Windows logon session denied secure persistence")
    try:
        assert SecretStore().get(reference) == "fake-µ-secret"
    finally:
        store.delete(reference)
    assert store.get(reference) == ""
