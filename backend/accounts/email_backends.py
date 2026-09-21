"""Send mail over HTTPS instead of SMTP.

Render's free web services block outbound SMTP (ports 25, 465 and 587) as an
anti-spam measure, so a sign-in link can never leave the machine — the
connection simply times out. Resend also exposes an HTTPS API on 443, which is
not blocked anywhere, so that is what this backend uses.

Set ``RESEND_API_KEY`` and this backend takes over from ``EMAIL_URL``. Nothing
else in the app changes: it is a normal Django email backend, so ``send_mail``
and the magic-link flow work unaltered.
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

log = logging.getLogger(__name__)

ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10


class ResendAPIBackend(BaseEmailBackend):
    """Django email backend that posts to Resend rather than talking SMTP."""

    def __init__(self, fail_silently: bool = False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = getattr(settings, "RESEND_API_KEY", "")

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0
        if not self.api_key:
            if self.fail_silently:
                return 0
            raise ValueError("RESEND_API_KEY is not set, so no mail can be sent.")

        sent = 0
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            for message in email_messages:
                if self._send(client, message):
                    sent += 1
        return sent

    def _send(self, client: httpx.Client, message) -> bool:
        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
            "text": message.body,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)

        # An HTML alternative, when one was attached.
        for content, mimetype in getattr(message, "alternatives", []) or []:
            if mimetype == "text/html":
                payload["html"] = content
                break

        try:
            response = client.post(
                ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as exc:
            log.error("Resend request failed: %s", exc)
            if self.fail_silently:
                return False
            raise

        if response.status_code >= 400:
            # The body says which address is unverified, or that the key is
            # wrong — worth having in the log, since the screen cannot show it.
            log.error("Resend refused the message (HTTP %s): %s", response.status_code, response.text[:400])
            if self.fail_silently:
                return False
            raise RuntimeError(f"Resend returned HTTP {response.status_code}: {response.text[:200]}")

        return True
