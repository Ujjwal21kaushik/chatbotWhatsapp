"""Twilio WhatsApp sending helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_MAX_MESSAGE_LENGTH,
    TWILIO_WHATSAPP_FROM,
)


@dataclass(frozen=True)
class TwilioSendResult:
    """Small result object for easier logging and testing."""

    success: bool
    sent_count: int
    error: str | None = None


def _get_client() -> Client:
    """Create a Twilio client from environment variables."""

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
        raise RuntimeError(
            "Twilio environment variables are missing. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM."
        )

    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def split_message(message: str, max_length: int = TWILIO_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split long replies before sending to prevent Twilio error 21617."""

    if len(message) <= max_length:
        return [message]

    chunks: list[str] = []
    remaining = message

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at < max_length // 2:
            split_at = max_length

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    return [chunk for chunk in chunks if chunk]


def send_whatsapp_reply(to_number: str, reply: str) -> TwilioSendResult:
    """Send one or more WhatsApp messages through Twilio.

    Twilio expects WhatsApp addresses such as "whatsapp:+919999999999".
    The incoming From value from Twilio already uses that format, so it can be
    passed directly as the recipient.
    """

    try:
        client = _get_client()
        chunks = split_message(reply)

        for chunk in chunks:
            client.messages.create(
                body=chunk,
                from_=TWILIO_WHATSAPP_FROM,
                to=to_number,
            )

        return TwilioSendResult(success=True, sent_count=len(chunks))
    except TwilioRestException as exc:
        logging.exception("Twilio API error while sending WhatsApp reply")
        return TwilioSendResult(success=False, sent_count=0, error=str(exc))
    except Exception as exc:
        logging.exception("Unexpected error while sending WhatsApp reply")
        return TwilioSendResult(success=False, sent_count=0, error=str(exc))



def send_welcome_template(to_number: str):
    client = _get_client()

    client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,
        to=to_number,
        content_sid="HXa47e899aa6dfb3a577e706b67be069a6",
    )