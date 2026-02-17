from app.config import Settings
from app.services import emailer


class _HttpResponse:
    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code = status_code
        self.text = text


def test_send_email_uses_resend_first(monkeypatch):
    called = {}

    def fake_post(url, headers, json, timeout):
        called["url"] = url
        called["headers"] = headers
        called["json"] = json
        called["timeout"] = timeout
        return _HttpResponse(status_code=200)

    def fail_smtp(*args, **kwargs):
        raise AssertionError("SMTP should not be used when Resend succeeds")

    monkeypatch.setattr(emailer.httpx, "post", fake_post)
    monkeypatch.setattr(emailer.smtplib, "SMTP", fail_smtp)

    settings = Settings(
        _env_file=None,
        resend_api_key="re_test_123",
        resend_from_email="hello@example.com",
        smtp_host="smtp.example.com",
    )

    emailer.send_email(
        settings,
        to_email="user@example.com",
        subject="Fax delivered",
        body="Your fax was delivered.",
    )

    assert called["url"] == "https://api.resend.com/emails"
    assert called["headers"]["Authorization"] == "Bearer re_test_123"
    assert called["json"]["to"] == ["user@example.com"]
    assert called["json"]["from"] == "hello@example.com"


def test_send_email_falls_back_to_smtp_when_resend_fails(monkeypatch):
    sent = {"smtp": False}

    def fake_post(url, headers, json, timeout):
        return _HttpResponse(status_code=500, text="resend error")

    class DummySMTP:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            return None

        def login(self, username, password):
            return None

        def send_message(self, msg):
            sent["smtp"] = True
            sent["to"] = msg["To"]
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr(emailer.httpx, "post", fake_post)
    monkeypatch.setattr(emailer.smtplib, "SMTP", DummySMTP)

    settings = Settings(
        _env_file=None,
        resend_api_key="re_test_123",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="smtp-user",
        smtp_password="smtp-pass",
        smtp_from_email="no-reply@example.com",
    )

    emailer.send_email(
        settings,
        to_email="user@example.com",
        subject="Fax delivered",
        body="Your fax was delivered.",
    )

    assert sent["smtp"] is True
    assert sent["to"] == "user@example.com"
    assert sent["subject"] == "Fax delivered"


def test_send_email_no_provider_is_noop():
    settings = Settings(_env_file=None, resend_api_key=None, smtp_host=None)

    emailer.send_email(
        settings,
        to_email="user@example.com",
        subject="Fax delivered",
        body="Your fax was delivered.",
    )
