from email.message import EmailMessage
import logging
from pathlib import Path
import smtplib
import ssl

from .access import now

log = logging.getLogger("paiddrive.mail")


def process_mail_jobs(db, settings):
    """One app worker retries its durable mail queue; no broker is required."""
    if not settings.email_enabled:
        return
    stamp = now()
    with db.transaction() as con:
        con.execute("UPDATE mail_jobs SET body='',recipient='' WHERE sent_at IS NULL AND expires_at<=?", (stamp,))
        jobs = [dict(r) for r in con.execute("SELECT * FROM mail_jobs WHERE mode=? AND sent_at IS NULL AND expires_at>? AND next_attempt_at<=? AND attempts<5 ORDER BY created_at LIMIT 10", (settings.app_mode, stamp, stamp))]
        for job in jobs:
            con.execute("UPDATE mail_jobs SET next_attempt_at=?,attempts=attempts+1 WHERE id=?", (stamp + 60, job["id"]))
    for job in jobs:
        message = EmailMessage()
        message["From"] = settings.smtp_from or "demo@paiddrive.local"
        message["To"] = job["recipient"]
        message["Subject"] = job["subject"]
        message.set_content(job["body"])
        try:
            if settings.mail_mode == "file":
                directory = Path(settings.mail_file_dir)
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = directory / f"{job['id']}.eml"
                # The outbox is private local data, never mounted as HTTP assets.
                with target.open("wb") as handle:
                    handle.write(message.as_bytes())
                target.chmod(0o600)
            else:
                context = ssl.create_default_context()
                if settings.smtp_port == 465:
                    server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=12, context=context)
                else:
                    server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12)
                with server:
                    if settings.smtp_starttls and settings.smtp_port != 465:
                        server.starttls(context=context)
                    if settings.smtp_user:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(message)
            with db.transaction() as con:
                con.execute("UPDATE mail_jobs SET sent_at=?,body='',recipient='' WHERE id=?", (now(), job["id"]))
        except (OSError, smtplib.SMTPException):
            # Do not log addresses, message bodies, credentials or recovery links.
            log.warning("Email delivery failed; the private queue will retry.")
