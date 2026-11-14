"""Bounded, synchronous provider transports, called only by channel workers.

Accepted means the provider accepted a request, never that a human read it.
No transport retries itself; durable scheduling and session eligibility belong
to the outbox. Each SMTP operation targets exactly one recipient.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email import policy
from email.utils import formatdate, make_msgid, parseaddr
import logging
import re
import smtplib
import socket
import ssl
from typing import Iterable

import httpx


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    detail: str
    retry_after: float = 0
    provider_id: str = ""


class NotificationSetupError(Exception):
    """A deliberately sanitized setup failure safe for the results panel."""


def redact(text: object, secrets: Iterable[str] = ()) -> str:
    """Remove token-bearing URLs and explicitly known secrets from diagnostics."""
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    result = re.sub(r"(?i)(api\.telegram\.org/bot)[^/\s\"'<>]+", r"\1[REDACTED]", result)
    result = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{15,}\b", "[REDACTED]", result)
    return result


class _HTTPRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx INFO request logging includes the token URL. Redact before any
        # handler sees either the format string or its interpolation arguments.
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


for _logger_name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection", "httpcore.proxy"):
    logging.getLogger(_logger_name).addFilter(_HTTPRedactionFilter())


def _address(value: object) -> str:
    value = str(value).strip()
    _, address = parseaddr(value)
    if (not address or "@" not in address or value != address
            or any(c in value for c in "\r\n\x00") or " " in value):
        raise ValueError("Enter a single valid email address without a display name.")
    return address


def _response(code: int, operation: str) -> DeliveryResult:
    if 400 <= code < 500:
        return DeliveryResult("retry", f"Gmail temporarily refused {operation} (SMTP {code}); this error is retryable.")
    return DeliveryResult("failed", f"Gmail refused {operation} (SMTP {code}); check account and recipient settings.")


def _gmail_failure(error: Exception, phase: str, port: int, submitting=False) -> DeliveryResult:
    """Classify known failures without copying provider/exception secrets.

    SMTPException inherits OSError, so SMTP protocol/authentication cases must
    be classified before generic socket errors.
    """
    location = f"smtp.gmail.com:{port} during {phase}"
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return DeliveryResult("failed", f"Gmail authentication failed at {location}. Check the app password and two-step verification; regular passwords are unsupported.")
    if isinstance(error, smtplib.SMTPResponseException):
        outcome = _response(error.smtp_code, phase)
        return DeliveryResult(outcome.status, f"{outcome.detail} Endpoint: {location}.")
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return DeliveryResult("failed", f"Required SMTP TLS/authentication capability is unavailable at {location}; check whether a network SMTP gateway is intercepting the connection.")
    if submitting and isinstance(error, (smtplib.SMTPServerDisconnected, OSError)):
        return DeliveryResult("unknown", f"Connection lost at {location}. Gmail may have accepted the message; inspect the mailbox before an explicit resend.")
    if isinstance(error, ssl.SSLCertVerificationError):
        return DeliveryResult("failed", f"TLS certificate verification failed at {location}. Check the PC clock and trusted certificates with IT; keep verification enabled.")
    if isinstance(error, ssl.SSLError):
        return DeliveryResult("failed", f"TLS connection failed at {location}. Check network/TLS compatibility and trusted certificates.")
    if isinstance(error, socket.gaierror):
        return DeliveryResult("retry", f"DNS lookup failed for {location}. Check name resolution and network connectivity.")
    if isinstance(error, (TimeoutError, socket.timeout)):
        return DeliveryResult("retry", f"Timed out contacting {location}. Check outbound SMTP access or try the other supported port, 465/587.")
    if isinstance(error, ConnectionRefusedError):
        return DeliveryResult("retry", f"Connection refused at {location}. Check outbound SMTP access and application-specific network policy.")
    if isinstance(error, smtplib.SMTPServerDisconnected):
        return DeliveryResult("retry", f"The SMTP server closed the connection at {location}. This may be transient; check SMTP/network policy.")
    if isinstance(error, smtplib.SMTPException):
        return DeliveryResult("failed", f"SMTP protocol error at {location}. Review the configured account and SMTP/network policy.")
    if isinstance(error, OSError):
        code = getattr(error, "winerror", None) or getattr(error, "errno", None)
        code_text = f" (socket code {code})" if isinstance(code, int) else ""
        return DeliveryResult("retry", f"Network/socket failure{code_text} at {location}. Check outbound SMTP access and application-specific network policy.")
    return DeliveryResult("failed", f"Invalid Gmail settings at {location}. Check sender, recipient and TLS port.")


class GmailTransport:
    """Gmail app-password SMTP over verified implicit TLS or mandatory STARTTLS."""

    def send(self, config: dict, secret: str, recipient: str, subject: str, text: str) -> DeliveryResult:
        smtp = None
        submitting = False
        phase = "settings/message preparation"
        port = 465
        try:
            sender = _address(config.get("sender", ""))
            recipient = _address(recipient)
            if not secret:
                return DeliveryResult("failed", "Gmail app password is missing; save credentials in setup.")
            port = int(config.get("port", 465))
            if port not in (465, 587):
                return DeliveryResult("failed", "Gmail port must be 465 (TLS) or 587 (STARTTLS).")
            message = EmailMessage(policy=policy.SMTP)
            message["From"] = sender
            message["To"] = recipient
            message["Subject"] = subject.replace("\r", " ").replace("\n", " ")[:250]
            message["Date"] = formatdate(localtime=True)
            message["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
            # Bound provider payload independently of log/context retention.
            message.set_content(str(text)[:65536])
            context = ssl.create_default_context()
            phase = "connection, TLS and server greeting" if port == 465 else "connection and server greeting"
            if port == 465:
                smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=context)
                phase = "SMTP capability check"
                smtp.ehlo()
            else:
                smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
                phase = "SMTP capability check"
                smtp.ehlo()
                phase = "STARTTLS"
                smtp.starttls(context=context)
                phase = "SMTP capability check after TLS"
                smtp.ehlo()
            phase = "authentication"
            smtp.login(sender, secret.replace(" ", ""))
            # Separate MAIL/RCPT/DATA gives the durable outbox unambiguous
            # recipient results and a conservative submission uncertainty point.
            phase = "sender acceptance"
            code, _ = smtp.mail(sender)
            if code != 250:
                return _response(code, "sender")
            phase = "recipient acceptance"
            code, _ = smtp.rcpt(recipient)
            if code not in (250, 251):
                return _response(code, "recipient")
            submitting = True
            phase = "message submission"
            code, _ = smtp.data(message.as_bytes())
            submitting = False
            if code != 250:
                return _response(code, "message")
            return DeliveryResult("accepted", "Accepted by Gmail for this recipient; receipt by the user is unverified.",
                                  provider_id=str(message["Message-ID"]))
        except (OSError, smtplib.SMTPException, ValueError, TypeError) as error:
            return _gmail_failure(error, phase, port, submitting)
        finally:
            if smtp is not None:
                # QUIT is not needed for acceptance and could itself timeout.
                # close is local, deterministic and never alters the result.
                try:
                    smtp.close()
                except OSError:
                    pass

    def check_connection(self, config: dict) -> dict:
        """DNS/TCP/TLS/EHLO only. Never authenticates, sets recipients or sends."""
        smtp = None
        port = 465
        phase = "settings"
        try:
            port = int(config.get("port", 465))
            if port not in {465, 587}:
                raise ValueError("Unsupported TLS port")
            context = ssl.create_default_context()
            phase = "connection, TLS and server greeting" if port == 465 else "connection and server greeting"
            smtp = smtplib.SMTP_SSL("smtp.gmail.com", port, timeout=15, context=context) if port == 465 else smtplib.SMTP("smtp.gmail.com", port, timeout=15)
            phase = "SMTP capability check"
            code, _ = smtp.ehlo()
            if code != 250:
                raise smtplib.SMTPHeloError(code, b"EHLO rejected")
            if port == 587:
                phase = "STARTTLS"
                smtp.starttls(context=context)
                phase = "SMTP capability check after TLS"
                code, _ = smtp.ehlo()
                if code != 250:
                    raise smtplib.SMTPHeloError(code, b"EHLO rejected")
            if not smtp.has_extn("auth"):
                raise smtplib.SMTPNotSupportedError("Authentication not advertised")
            return dict(status="connection_ok", host="smtp.gmail.com", port=port,
                        detail="Verified TLS and SMTP handshake succeeded from this application. App password not checked; no email sent.",
                        authenticated=False, email_sent=False)
        except (OSError, smtplib.SMTPException, ValueError, TypeError) as error:
            failure = _gmail_failure(error, phase, port)
            return dict(status=failure.status, host="smtp.gmail.com", port=port, detail=failure.detail,
                        authenticated=False, email_sent=False)
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except OSError:
                    pass


def _short_message(subject: str, text: str) -> str:
    message = f"{subject}\n\n{text}"
    budget = 3500
    encoded = message.encode("utf-16-le", errors="replace")
    if len(encoded) // 2 <= budget:
        return message
    suffix = "\n[Truncated; open the event in ATLAS Watchdog for the complete message.]"
    keep = budget - len(suffix.encode("utf-16-le")) // 2
    prefix = encoded[:keep * 2].decode("utf-16-le", errors="ignore")
    # Prefer a natural boundary near the cut without losing a large prefix.
    boundary = max(prefix.rfind("\n"), prefix.rfind(" "))
    if boundary >= len(prefix) - 100:
        prefix = prefix[:boundary]
    return prefix + suffix


class TelegramTransport:
    """Plain-text HTTPS requests. No webhook, command listener or paid broadcast."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    def _call(self, secret: str, method: str, data: dict) -> tuple[DeliveryResult, object]:
        if not secret or not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", secret):
            return DeliveryResult("failed", "Telegram bot token is missing or has an invalid format."), None
        url = f"https://api.telegram.org/bot{secret}/{method}"
        try:
            if self._client is None:
                with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
                    response = client.post(url, json=data)
            else:
                response = self._client.post(url, json=data, timeout=httpx.Timeout(15, connect=5))
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError):
            if method == "sendMessage":
                return DeliveryResult("unknown", "Telegram connection failed during submission; provider acceptance is uncertain. Check the chat before resending."), None
            return DeliveryResult("retry", "Telegram request timed out or the connection was interrupted."), None
        except httpx.TransportError:
            return DeliveryResult("retry", "Cannot connect securely to Telegram; check HTTPS connectivity, proxy, clock and certificates."), None
        except (ValueError, TypeError):
            return DeliveryResult("failed", "Invalid Telegram request settings."), None
        try:
            body = response.json()
        except (ValueError, TypeError):
            status = "retry" if response.status_code >= 500 else "unknown" if method == "sendMessage" else "failed"
            return DeliveryResult(status, "Telegram returned an invalid response; acceptance could not be verified."), None
        if not isinstance(body, dict):
            return DeliveryResult("unknown" if method == "sendMessage" else "failed", "Telegram response format was invalid."), None
        try:
            code = int(body.get("error_code", response.status_code))
        except (TypeError, ValueError):
            code = response.status_code
        if code == 429 or response.status_code == 429:
            try:
                delay = max(1.0, float(body.get("parameters", {}).get("retry_after", 30)))
            except (TypeError, ValueError, AttributeError):
                delay = 30
            return DeliveryResult("retry", "Telegram rate limit reached; waiting for the provider retry interval.", delay), None
        if code == 401 or response.status_code == 401:
            return DeliveryResult("failed", "Telegram rejected the bot token; replace it in setup."), None
        if code == 403 or response.status_code == 403:
            return DeliveryResult("failed", "Telegram chat is blocked or inaccessible. Open the bot, press Start, and verify chat ID."), None
        if code == 409 or response.status_code == 409:
            return DeliveryResult("failed", "Telegram update discovery conflicts with an existing webhook or another consumer. Use a dedicated bot; no webhook was changed."), None
        if code >= 500 or response.status_code >= 500:
            return DeliveryResult("retry", "Telegram server is temporarily unavailable."), None
        if not (200 <= response.status_code < 300) or body.get("ok") is not True:
            # Never copy the provider's description: it may quote submitted data.
            return DeliveryResult("failed", f"Telegram refused the request (HTTP/API {code}); check bot/chat settings."), None
        return DeliveryResult("accepted", "Accepted by Telegram; phone notification and user receipt are unverified."), body.get("result")

    def send(self, config: dict, secret: str, recipient: str, subject: str, text: str) -> DeliveryResult:
        if not re.fullmatch(r"-?\d+", str(recipient).strip()):
            return DeliveryResult("failed", "Enter a numeric Telegram chat ID or use Find my chat.")
        outcome, result = self._call(secret, "sendMessage", {
            "chat_id": str(recipient).strip(), "text": _short_message(subject, text),
            "disable_notification": False,
        })
        if outcome.status == "accepted" and isinstance(result, dict):
            return DeliveryResult(outcome.status, outcome.detail, provider_id=str(result.get("message_id", "")))
        return outcome

    def get_me(self, secret: str) -> dict:
        outcome, result = self._call(secret, "getMe", {})
        if outcome.status != "accepted" or not isinstance(result, dict):
            raise NotificationSetupError(outcome.detail)
        return {key: result[key] for key in ("id", "first_name", "username", "is_bot") if key in result}

    def find_chats(self, secret: str) -> list[dict]:
        # No offset means updates are not explicitly acknowledged/discarded.
        outcome, result = self._call(secret, "getUpdates", {"limit": 100, "timeout": 0})
        if outcome.status != "accepted" or not isinstance(result, list):
            raise NotificationSetupError(outcome.detail)
        chats: dict[str, dict] = {}
        for update in result:
            if not isinstance(update, dict):
                continue
            message = update.get("message", {})
            chat = message.get("chat", {}) if isinstance(message, dict) else {}
            if not isinstance(chat, dict) or chat.get("type") != "private" or not isinstance(chat.get("id"), int):
                continue
            name = " ".join(str(chat.get(key, "")) for key in ("first_name", "last_name")).strip()
            if chat.get("username"):
                name += f" (@{chat['username']})"
            chat_id = str(chat["id"])
            chats[chat_id] = {"id": chat_id, "name": name or chat_id}
        return list(chats.values())
