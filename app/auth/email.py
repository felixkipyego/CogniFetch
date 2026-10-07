import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


async def send_verification_email(to_email: str, token: str) -> None:
    """Send a verification email. No-op when SMTP_HOST is not configured."""
    if not settings.smtp_host:
        return

    verify_url = f"{settings.frontend_url}/verify-email?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Verify your CogniFetch email"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    text = (
        f"Welcome to CogniFetch!\n\n"
        f"Click the link below to verify your email address:\n{verify_url}\n\n"
        f"The link expires in 24 hours.\n\n"
        f"Tip: if you don't see this email in your inbox, check your spam or junk folder.\n\n"
        f"If you didn't create a CogniFetch account you can safely ignore this email."
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a">
  <h2 style="margin-bottom:8px">Welcome to CogniFetch!</h2>
  <p>Click the button below to verify your email address. The link expires in <strong>24 hours</strong>.</p>
  <p style="margin:32px 0">
    <a href="{verify_url}"
       style="background:#4f46e5;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:600">
      Verify email address
    </a>
  </p>
  <p style="font-size:13px;color:#555">
    Or copy and paste this link into your browser:<br>
    <a href="{verify_url}" style="color:#4f46e5;word-break:break-all">{verify_url}</a>
  </p>
  <hr style="border:none;border-top:1px solid #e5e5e5;margin:24px 0">
  <p style="font-size:12px;color:#888">
    <strong>Can't find this email?</strong> Check your <strong>spam or junk folder</strong> —
    verification emails sometimes end up there.
  </p>
  <p style="font-size:12px;color:#888">
    If you didn't create a CogniFetch account you can safely ignore this email.
  </p>
</body>
</html>"""

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_use_tls,
    )
    logger.info("Verification email sent to %s", to_email)
