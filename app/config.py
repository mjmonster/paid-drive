from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_mode: str = "demo"
    app_url: str = "http://localhost:8000"
    database_path: Path = BASE_DIR / "data/paiddrive.sqlite3"
    content_root: Path = BASE_DIR / "content"
    mail_mode: str = "file"
    mail_file_dir: Path = BASE_DIR / "data/outbox"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    zpay_base_url: str = ""
    zpay_pid: str = ""
    zpay_key: str = ""
    zpay_pay_type: str = "wxpay"
    session_days: int = 90
    support_qr_path: Path | None = None
    run_background_jobs: bool = True

    @classmethod
    def from_env(cls):
        mode = os.getenv("APP_MODE", "demo").lower()
        return cls(
            app_mode=mode,
            app_url=os.getenv("APP_URL", "http://localhost:8000").rstrip("/"),
            database_path=Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data/paiddrive.sqlite3"))),
            content_root=Path(os.getenv("CONTENT_ROOT", str(BASE_DIR / "content"))),
            mail_mode=os.getenv("MAIL_MODE", "file" if mode == "demo" else "disabled").lower(),
            mail_file_dir=Path(os.getenv("MAIL_FILE_DIR", str(BASE_DIR / "data/outbox"))),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from=os.getenv("SMTP_FROM", ""),
            smtp_starttls=os.getenv("SMTP_STARTTLS", "true").lower() == "true",
            zpay_base_url=os.getenv("ZPAY_BASE_URL", "").rstrip("/"),
            zpay_pid=os.getenv("ZPAY_PID", ""),
            zpay_key=os.getenv("ZPAY_KEY", ""),
            zpay_pay_type=os.getenv("ZPAY_PAY_TYPE", "wxpay").lower(),
            session_days=int(os.getenv("SESSION_DAYS", "90")),
            support_qr_path=Path(os.environ["SUPPORT_QR_PATH"]) if os.getenv("SUPPORT_QR_PATH") else None,
        )

    def validate(self):
        if self.app_mode not in {"demo", "live"}:
            raise ValueError("APP_MODE must be demo or live")
        if self.mail_mode not in {"file", "smtp", "disabled"}:
            raise ValueError("MAIL_MODE must be file, smtp or disabled")
        origin = urlsplit(self.app_url)
        if origin.scheme not in {"http", "https"} or not origin.netloc or origin.username or origin.query or origin.fragment or origin.path not in {"", "/"}:
            raise ValueError("APP_URL must be the site's public origin, without a path or credentials")
        if not 1 <= self.session_days <= 365:
            raise ValueError("SESSION_DAYS must be between 1 and 365")
        if self.app_mode == "live":
            if origin.scheme != "https":
                raise ValueError("Live mode requires an HTTPS APP_URL")
            gateway = urlsplit(self.zpay_base_url)
            if gateway.scheme != "https" or not gateway.netloc or gateway.username or gateway.query or gateway.fragment:
                raise ValueError("Live mode requires your ZPAY_BASE_URL with HTTPS")
            if not self.zpay_pid or not self.zpay_key:
                raise ValueError("Live mode requires ZPAY_PID and ZPAY_KEY")
            if self.zpay_pay_type not in {"alipay", "wxpay"}:
                raise ValueError("ZPAY_PAY_TYPE must be wxpay or alipay")
            if self.mail_mode == "file":
                raise ValueError("File email is demo-only; use SMTP or disable email in live mode")
        if self.mail_mode == "smtp":
            if not self.smtp_host or not self.smtp_from:
                raise ValueError("SMTP_HOST and SMTP_FROM are required for SMTP email")
            if not self.smtp_starttls and self.smtp_port != 465:
                raise ValueError("SMTP must use STARTTLS, or port 465 for implicit TLS")
        if self.support_qr_path and not self.support_qr_path.is_file():
            raise ValueError("SUPPORT_QR_PATH does not point to a file")

    @property
    def email_enabled(self):
        return self.mail_mode != "disabled"
