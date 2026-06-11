from __future__ import annotations

import unittest

import app.framework.runtime.email as email_runtime


class EmailRuntimeTests(unittest.TestCase):
    def test_send_message_uses_smtp_ssl_and_login(self) -> None:
        events: list[tuple[str, object]] = []

        class _FakeServer:
            def login(self, username: str, password: str) -> None:
                events.append(("login", (username, password)))

            def send_message(self, message) -> None:
                events.append(("subject", message["Subject"]))
                events.append(("to", message["To"]))

            def __enter__(self):
                events.append(("enter", None))
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                events.append(("exit", None))

        original_ssl = email_runtime.smtplib.SMTP_SSL
        email_runtime.smtplib.SMTP_SSL = lambda *args, **kwargs: _FakeServer()
        try:
            client = email_runtime.SmtpEmailClient(
                host="smtp.example.test",
                port=465,
                username="user",
                password="pass",
                use_ssl=True,
                timeout_seconds=10,
            )
            client.send_message(
                subject="Operator summary",
                body="Hello",
                from_address="from@example.test",
                to_addresses=("to@example.test",),
            )
        finally:
            email_runtime.smtplib.SMTP_SSL = original_ssl

        self.assertIn(("login", ("user", "pass")), events)
        self.assertIn(("subject", "Operator summary"), events)
        self.assertIn(("to", "to@example.test"), events)

    def test_send_message_requires_recipient(self) -> None:
        client = email_runtime.SmtpEmailClient(host="smtp.example.test")
        with self.assertRaises(email_runtime.EmailNotificationError) as exc:
            client.send_message(
                subject="Operator summary",
                body="Hello",
                from_address="from@example.test",
                to_addresses=(),
            )
        self.assertIn("smtp_to_missing", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
