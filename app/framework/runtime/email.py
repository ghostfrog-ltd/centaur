from __future__ import annotations

import smtplib
from email.message import EmailMessage


class EmailNotificationError(RuntimeError):
    """Raised when SMTP delivery of an operator email fails."""


class SmtpEmailClient:
    """Minimal one-way SMTP client for operator notifications.

    Email is an outbound reporting surface only. It must not become a control
    path for trading mutations or approval workflows.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 465,
        username: str = "",
        password: str = "",
        use_ssl: bool = True,
        timeout_seconds: int = 10,
    ) -> None:
        self.host = str(host or "").strip()
        self.port = max(1, int(port or 465))
        self.username = str(username or "").strip()
        self.password = str(password or "")
        self.use_ssl = bool(use_ssl)
        self.timeout_seconds = max(1, int(timeout_seconds or 10))

    def send_message(
        self,
        *,
        subject: str,
        body: str,
        from_address: str,
        to_addresses: tuple[str, ...] | list[str],
    ) -> None:
        if not self.host:
            raise EmailNotificationError("smtp_host_missing")
        sender = str(from_address or "").strip()
        if not sender:
            raise EmailNotificationError("smtp_from_missing")
        recipients = [str(item or "").strip() for item in to_addresses if str(item or "").strip()]
        if not recipients:
            raise EmailNotificationError("smtp_to_missing")

        message = EmailMessage()
        message["Subject"] = str(subject or "").strip() or "Project Centaur operator summary"
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(str(body or ""))

        try:
            if self.use_ssl:
                with smtplib.SMTP_SSL(
                    self.host,
                    self.port,
                    timeout=self.timeout_seconds,
                ) as server:
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(
                    self.host,
                    self.port,
                    timeout=self.timeout_seconds,
                ) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(message)
        except smtplib.SMTPException as exc:
            raise EmailNotificationError(f"smtp_send_failed: {exc}") from exc
        except OSError as exc:
            raise EmailNotificationError(f"smtp_connection_failed: {exc}") from exc
