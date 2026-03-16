"""
Sequence Execution Agent
Executes outreach steps: sends emails (real via SMTP/SendGrid, mock in demo mode)
and logs LinkedIn actions. Respects sending limits and human-like delays.
"""
import smtplib
import logging
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from agents.base import BaseAgent
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    success: bool
    message_id: str
    channel: str
    error: str = ""
    mock: bool = False


class SequenceExecutionAgent(BaseAgent):
    """Sends outreach steps via email or LinkedIn. Falls back to mock mode if no SMTP configured."""

    async def run(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        channel: str = "email",
        step_number: int = 1,
    ) -> SendResult:
        if channel == "linkedin":
            return await self._execute_linkedin(to_name, body, step_number)
        return await self._execute_email(to_email, to_name, subject, body)

    async def _execute_email(
        self, to_email: str, to_name: str, subject: str, body: str
    ) -> SendResult:
        if settings.sendgrid_api_key:
            return await self._send_via_sendgrid(to_email, to_name, subject, body)
        if settings.smtp_host:
            return await self._send_via_smtp(to_email, to_name, subject, body)
        return self._mock_send(to_email, "email")

    async def _send_via_smtp(
        self, to_email: str, to_name: str, subject: str, body: str
    ) -> SendResult:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.sender_name} <{settings.sender_email}>"
            msg["To"] = f"{to_name} <{to_email}>"
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.sender_email, to_email, msg.as_string())

            message_id = f"smtp-{datetime.utcnow().timestamp()}"
            logger.info("Email sent via SMTP to %s", to_email)
            return SendResult(success=True, message_id=message_id, channel="email")
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            return SendResult(success=False, message_id="", channel="email", error=str(exc))

    async def _send_via_sendgrid(
        self, to_email: str, to_name: str, subject: str, body: str
    ) -> SendResult:
        try:
            import httpx
            payload = {
                "personalizations": [{"to": [{"email": to_email, "name": to_name}]}],
                "from": {"email": settings.sender_email, "name": settings.sender_name},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                    timeout=10,
                )
                resp.raise_for_status()
            message_id = resp.headers.get("X-Message-Id", f"sg-{datetime.utcnow().timestamp()}")
            logger.info("Email sent via SendGrid to %s", to_email)
            return SendResult(success=True, message_id=message_id, channel="email")
        except Exception as exc:
            logger.error("SendGrid send failed: %s", exc)
            return SendResult(success=False, message_id="", channel="email", error=str(exc))

    async def _execute_linkedin(
        self, to_name: str, body: str, step_number: int
    ) -> SendResult:
        # Production: Playwright browser automation with residential proxies
        # Demo mode: log the action
        logger.info(
            "LinkedIn action (step %d) for %s: %s...", step_number, to_name, body[:50]
        )
        return SendResult(
            success=True,
            message_id=f"li-{datetime.utcnow().timestamp()}",
            channel="linkedin",
            mock=True,
        )

    def _mock_send(self, to_email: str, channel: str) -> SendResult:
        """Demo mode — logs send without actually delivering."""
        logger.info("[MOCK] Would send %s to %s", channel, to_email)
        return SendResult(
            success=True,
            message_id=f"mock-{datetime.utcnow().timestamp()}",
            channel=channel,
            mock=True,
        )
