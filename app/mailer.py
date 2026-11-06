"""Sending email through any SMTP server the operator points us at (ADR-052): BillionMail, a mail provider, a company relay.

Off until SMTP_HOST and SMTP_FROM are set. Settings, all server-side:

    SMTP_HOST, SMTP_PORT (default 587), SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_SECURITY = starttls (default) | ssl | none,  SMTP_FROM = "GRC <no-reply@example.com>"
    SMTP_SUPPORT_REPLY_TO = the mailbox a person monitors; replies to a welcome email go there (optional)

Nothing here logs or returns a message body, a recipient's full address or a password. `send` never raises: it returns
(ok, short reason), where the reason is an error class, so a failure can be shown without leaking what was being sent.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage

TIMEOUT_S = 15.0
_ADDRESS = re.compile(r"^[^\s@<>,;\"']+@[^\s@<>,;\"']+\.[^\s@<>,;\"']+$")


def enabled() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def valid_address(address: str) -> bool:
    """One plain address: no spaces, no angle brackets, no line breaks (which would let a caller inject headers)."""
    return bool(_ADDRESS.match(address or "")) and len(address) <= 254


def send(to: str, subject: str, body: str, reply_to: str | None = None) -> tuple[bool, str]:
    """Send one plain-text email. Returns (ok, reason); reason is empty on success. `reply_to` is where a reply goes."""
    if not enabled():
        return False, "email is not set up on this server"
    if not valid_address(to):
        return False, "that does not look like an email address"
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = os.environ["SMTP_FROM"], to, subject.replace("\r", " ").replace("\n", " ")
    reply = reply_to or os.environ.get("SMTP_SUPPORT_REPLY_TO")
    if reply:
        if not valid_address(reply):
            return False, "the reply-to setting is not a plain email address"
        message["Reply-To"] = reply
    message.set_content(body)
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    security = os.environ.get("SMTP_SECURITY", "starttls").lower()
    try:
        context = ssl.create_default_context()
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT_S, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT_S)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if os.environ.get("SMTP_USERNAME"):
                server.login(os.environ["SMTP_USERNAME"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(message)
    except Exception as exc:  # noqa: BLE001 - class only: the message of an SMTP error can echo the recipient or the server's banner
        return False, f"could not send ({type(exc).__name__})"
    return True, ""
