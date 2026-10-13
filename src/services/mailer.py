"""Outgoing email for verification and password-reset codes.

With SMTP configured (``SMTP_HOST`` ...) messages go out over SMTP. Without it
the message is written to the console and the log, so the app stays usable in
local development.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from config.settings import settings

logger = logging.getLogger(__name__)


class Mailer:
    def send(self, to: str, subject: str, body: str) -> None:
        if not settings.smtp_host:
            notice = f"[dev mail] To: {to} | {subject}\n{body}"
            logger.warning(notice)
            print("\n" + "=" * 60 + "\n" + notice + "\n" + "=" * 60, flush=True)
            return
        message = EmailMessage()
        message["From"] = settings.smtp_from or settings.smtp_user
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        if settings.smtp_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if not settings.smtp_ssl:
                server.starttls(context=context)
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password or "")
            server.send_message(message)
        logger.info("Sent '%s' email", subject)
