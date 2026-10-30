import html
import json
import logging
import smtplib
from email.message import EmailMessage
import urllib.error
import urllib.request
from typing import Any, Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class EmailService(Protocol):
    """Protocol defining the interface for decoupled email delivery services."""

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send an email to a single recipient."""
        ...


class ConsoleEmailService:
    """Logs email contents to stdout/logger. Ideal for development and debugging."""

    def __init__(self, from_email: str | None = None):
        self.from_email = from_email or settings.EMAIL_FROM
        self.last_sent: dict[str, Any] | None = None

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        self.last_sent = {
            "from": self.from_email,
            "to": to_email,
            "subject": subject,
            "html": html_body,
            "text": text_body or "",
        }
        logger.info(
            "\n========== [CONSOLE EMAIL DISPATCH] ==========\n"
            "From: %s\n"
            "To: %s\n"
            "Subject: %s\n"
            "Text Preview:\n%s\n"
            "===============================================",
            self.from_email,
            to_email,
            subject,
            (text_body or html_body)[:300],
        )
        return True


class MockEmailService:
    """In-memory email recorder for automated testing."""

    def __init__(self, from_email: str | None = None):
        self.from_email = from_email or settings.EMAIL_FROM
        self.sent_emails: list[dict[str, Any]] = []

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        self.sent_emails.append({
            "from": self.from_email,
            "to": to_email,
            "subject": subject,
            "html": html_body,
            "text": text_body or "",
        })
        return True

    def clear(self) -> None:
        self.sent_emails.clear()


class SMTPEmailService:
    """Delivers transactional emails via standard SMTP server (Mailpit, Sendgrid SMTP, AWS SES)."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool | None = None,
        from_email: str | None = None,
    ):
        self.host = host or settings.SMTP_HOST
        self.port = port or settings.SMTP_PORT
        self.username = username or settings.SMTP_USERNAME
        self.password = password or settings.SMTP_PASSWORD
        self.use_tls = use_tls if use_tls is not None else settings.SMTP_USE_TLS
        self.from_email = from_email or settings.EMAIL_FROM

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to_email

        plain_content = text_body or "Please view this email in an HTML-compatible client."
        msg.set_content(plain_content)
        msg.add_alternative(html_body, subtype="html")

        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port) as server:
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port) as server:
                    if self.use_tls:
                        server.starttls()
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            return True
        except Exception as exc:
            logger.error("Failed to send email via SMTP to %s: %s", to_email, exc)
            return False


class ResendEmailService:
    """Delivers transactional emails via Resend HTTP REST API."""

    def __init__(self, api_key: str | None = None, from_email: str | None = None):
        self.api_key = api_key or settings.RESEND_API_KEY
        self.from_email = from_email or settings.EMAIL_FROM
        self.endpoint = "https://api.resend.com/emails"

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        if not self.api_key:
            logger.error("Resend API key is not configured; cannot deliver email to %s", to_email)
            return False

        payload = {
            "from": self.from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            payload["text"] = text_body

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "NoteSight/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("Resend API returned HTTP %s for %s: %s", exc.code, to_email, error_body)
            return False
        except Exception as exc:
            logger.error("Resend network error delivering email to %s: %s", to_email, exc)
            return False


_global_mock_service: MockEmailService | None = None


def get_email_service(backend_name: str | None = None) -> EmailService:
    """Factory creating an EmailService instance based on configured backend."""
    global _global_mock_service
    name = (backend_name or settings.EMAIL_BACKEND).lower()

    if name == "mock":
        if _global_mock_service is None:
            _global_mock_service = MockEmailService()
        return _global_mock_service
    if name == "smtp":
        return SMTPEmailService()
    if name == "resend":
        return ResendEmailService()
    return ConsoleEmailService()


# ---------------------------------------------------------------------------
# Beautiful Responsive HTML Email Templates
# ---------------------------------------------------------------------------

def _render_base_email(title: str, preheader: str, content_html: str) -> str:
    """Standard NoteSight responsive branded HTML email layout."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #1e293b;
      line-height: 1.6;
    }}
    .email-container {{
      max-width: 580px;
      margin: 36px auto;
      background: #ffffff;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
    }}
    .email-header {{
      background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
      padding: 28px 32px;
      text-align: center;
      color: #ffffff;
    }}
    .email-header h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    .email-body {{
      padding: 32px 36px;
    }}
    .email-button {{
      display: inline-block;
      background-color: #4f46e5;
      color: #ffffff !important;
      font-weight: 600;
      font-size: 15px;
      padding: 13px 28px;
      border-radius: 8px;
      text-decoration: none;
      margin: 24px 0;
    }}
    .email-footer {{
      background-color: #f8fafc;
      padding: 20px 36px;
      border-top: 1px solid #e2e8f0;
      font-size: 12px;
      color: #64748b;
      text-align: center;
    }}
    .preheader {{
      display: none !important;
      visibility: hidden;
      mso-hide: all;
      font-size: 1px;
      line-height: 1px;
      max-height: 0;
      max-width: 0;
      opacity: 0;
      overflow: hidden;
    }}
  </style>
</head>
<body>
  <span class="preheader">{preheader}</span>
  <div class="email-container">
    <div class="email-header">
      <h1>🎵 NoteSight</h1>
    </div>
    <div class="email-body">
      {content_html}
    </div>
    <div class="email-footer">
      <p style="margin: 0 0 6px 0;">This email was sent by NoteSight — Neural Optical Music Recognition.</p>
      <p style="margin: 0 0 6px 0;">Questions or assistance? Reach us at <a href="mailto:{settings.CONTACT_EMAIL}" style="color: #4f46e5; text-decoration: none;">{settings.CONTACT_EMAIL}</a>.</p>
      <p style="margin: 0;">If you did not request this communication, you can safely ignore it.</p>
    </div>
  </div>
</body>
</html>"""


def build_verification_email(recipient_email: str, verification_link: str) -> tuple[str, str]:
    """Generates HTML and plain text for account activation email."""
    title = "Verify Your NoteSight Account"
    preheader = "Confirm your email address to activate your NoteSight account."
    content_html = f"""
      <h2 style="margin-top: 0; font-size: 20px; color: #0f172a;">Welcome to NoteSight!</h2>
      <p>Thank you for signing up for NoteSight. To ensure your account security and enable high-fidelity neural sheet music transcription, please verify your email address.</p>
      <div style="text-align: center;">
        <a href="{verification_link}" class="email-button" target="_blank">Verify Email Address</a>
      </div>
      <p style="font-size: 13px; color: #64748b;">Or paste this link into your browser:</p>
      <p style="font-size: 12px; word-break: break-all; background: #f1f5f9; padding: 10px; border-radius: 6px; color: #334155;">{verification_link}</p>
      <p style="font-size: 13px; color: #64748b;">This link will expire in 24 hours.</p>
    """
    html = _render_base_email(title, preheader, content_html)
    text = (
        f"Welcome to NoteSight!\n\n"
        f"Please verify your email address by visiting this link:\n"
        f"{verification_link}\n\n"
        f"This link will expire in 24 hours.\n\n"
        f"Need assistance? Reach our team at {settings.CONTACT_EMAIL}\n"
    )
    return html, text


def build_password_reset_email(recipient_email: str, reset_link: str) -> tuple[str, str]:
    """Generates HTML and plain text for password reset email."""
    title = "Reset Your NoteSight Password"
    preheader = "Instructions for resetting your NoteSight account password."
    content_html = f"""
      <h2 style="margin-top: 0; font-size: 20px; color: #0f172a;">Password Reset Request</h2>
      <p>We received a request to reset the password for your NoteSight account (<strong>{recipient_email}</strong>).</p>
      <p>Click the button below to choose a new, secure password:</p>
      <div style="text-align: center;">
        <a href="{reset_link}" class="email-button" target="_blank">Reset Password</a>
      </div>
      <p style="font-size: 13px; color: #64748b;">Or paste this link into your browser:</p>
      <p style="font-size: 12px; word-break: break-all; background: #f1f5f9; padding: 10px; border-radius: 6px; color: #334155;">{reset_link}</p>
      <p style="font-size: 13px; color: #64748b;">For your security, this password reset link is single-use and will expire in 1 hour. If you did not make this request, no action is needed.</p>
    """
    html = _render_base_email(title, preheader, content_html)
    text = (
        f"NoteSight Password Reset Request\n\n"
        f"Click the link below to choose a new password:\n"
        f"{reset_link}\n\n"
        f"This link is single-use and will expire in 1 hour.\n\n"
        f"If you did not request this, please contact {settings.CONTACT_EMAIL}\n"
    )
    return html, text


def build_job_completed_email(
    recipient_email: str,
    score_title: str,
    page_count: int,
    score_link: str,
) -> tuple[str, str]:
    """Generates HTML and plain text notification when background OMR finishes."""
    safe_title = html.escape(score_title)
    title = f"Your Score '{safe_title}' is Ready!"
    preheader = f"NoteSight finished transcribing {safe_title} ({page_count} pages)."
    content_html = f"""
      <h2 style="margin-top: 0; font-size: 20px; color: #0f172a;">Transcription Completed 🎼</h2>
      <p>Great news! NoteSight has finished transcribing <strong>{safe_title}</strong>.</p>
      <ul style="padding-left: 20px; color: #475569; font-size: 14px;">
        <li><strong>Score:</strong> {safe_title}</li>
        <li><strong>Pages Transcribed:</strong> {page_count}</li>
        <li><strong>Status:</strong> Ready in your Score Library &amp; Studio</li>
      </ul>
      <div style="text-align: center;">
        <a href="{score_link}" class="email-button" target="_blank">Open in Notation Studio</a>
      </div>
      <p style="font-size: 13px; color: #64748b;">You can sight-read, edit notes, play synthesized audio, or export to MusicXML, PDF, and MIDI directly from your dashboard.</p>
    """
    html_output = _render_base_email(title, preheader, content_html)
    text = (
        f"Your score '{score_title}' has finished processing!\n\n"
        f"Total pages: {page_count}\n"
        f"Open your score in NoteSight Studio: {score_link}\n"
    )
    return html_output, text


def build_subscription_confirmed_email(
    recipient_email: str,
    tier_name: str,
    storage_mb: int,
    monthly_pages: int,
    dashboard_link: str,
) -> tuple[str, str]:
    """Generates HTML and plain text confirmation when a subscription upgrade completes."""
    title = f"Welcome to NoteSight {tier_name}! 🎼"
    preheader = f"Your subscription is now active with {storage_mb} MB storage and {monthly_pages} pages/month."
    content_html = f"""
      <h2 style="margin-top: 0; font-size: 20px; color: #0f172a;">Subscription Activated 🎉</h2>
      <p>Thank you for subscribing to NoteSight <strong>{tier_name}</strong>! Your account has been upgraded with expanded transcription capacity and cloud storage.</p>
      <ul style="padding-left: 20px; color: #475569; font-size: 14px; line-height: 1.6;">
        <li><strong>Plan:</strong> NoteSight {tier_name}</li>
        <li><strong>Cloud Score Storage:</strong> {storage_mb} MB</li>
        <li><strong>Monthly Transcriptions:</strong> {monthly_pages} pages / month</li>
        <li><strong>Status:</strong> Active (PCI-DSS Level 1 Secure via Stripe)</li>
      </ul>
      <div style="text-align: center; margin: 24px 0;">
        <a href="{dashboard_link}" class="email-button" target="_blank">Open NoteSight Studio</a>
      </div>
      <p style="font-size: 13px; color: #64748b;">You can view and manage your payment methods, download invoices, or change your plan at any time in your NoteSight Settings under Billing.</p>
    """
    html = _render_base_email(title, preheader, content_html)
    text = (
        f"Welcome to NoteSight {tier_name}!\n\n"
        f"Your subscription is now active.\n"
        f"- Cloud Score Storage: {storage_mb} MB\n"
        f"- Monthly Transcriptions: {monthly_pages} pages/month\n\n"
        f"Open NoteSight Studio: {dashboard_link}\n\n"
        f"Manage billing and view invoices at: {dashboard_link}\n"
    )
    return html, text


def build_payment_failed_email(
    recipient_email: str,
    tier_name: str,
    portal_link: str,
) -> tuple[str, str]:
    """Generates HTML and plain text alert when a recurring subscription renewal fails."""
    title = f"Action Required: NoteSight {tier_name} Payment Failed"
    preheader = f"Your latest NoteSight {tier_name} renewal could not be processed."
    content_html = f"""
      <h2 style="margin-top: 0; font-size: 20px; color: #b91c1c;">Subscription Renewal Failed ⚠️</h2>
      <p>We were unable to process the renewal payment for your <strong>NoteSight {tier_name}</strong> subscription.</p>
      <p>To avoid any disruption to your sheet music cloud storage and monthly transcription capacity, please update your payment method in your secure Billing Portal:</p>
      <div style="text-align: center; margin: 24px 0;">
        <a href="{portal_link}" class="email-button" style="background: #dc2626;" target="_blank">Update Payment Method</a>
      </div>
      <p style="font-size: 13px; color: #64748b;">If your card has expired or needs updating, you can update it directly with Stripe without losing your saved scores or annotations.</p>
      <p style="font-size: 13px; color: #64748b;">Need help? Reach out directly to our team at <a href="mailto:{settings.CONTACT_EMAIL}" style="color: #4f46e5;">{settings.CONTACT_EMAIL}</a>.</p>
    """
    html = _render_base_email(title, preheader, content_html)
    text = (
        f"NoteSight {tier_name} Renewal Failed\n\n"
        f"We were unable to process the payment for your NoteSight {tier_name} subscription.\n"
        f"Please update your payment method to keep your expanded storage and transcription capacity:\n"
        f"{portal_link}\n\n"
        f"Need assistance? Contact us at {settings.CONTACT_EMAIL}\n"
    )
    return html, text

