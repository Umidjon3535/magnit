"""Claude API bilan ishlash: chat-yordamchi, chek va PDF-hisobotlarni tahlil qilish.

ANTHROPIC_API_KEY bo'lmasa, bu moduldagi funksiyalar AIUnavailable xatosini beradi va
chaqiruvchi kod oflayn (regex/OCR) rejimga o'tadi.
"""

import base64
import json
import logging

import anthropic
from django.conf import settings

from .prompts import ASSISTANT_SYSTEM_PROMPT, RECEIPT_EXTRACTION_PROMPT, STATEMENT_EXTRACTION_PROMPT

log = logging.getLogger(__name__)

# Xavfsizlik klassifikatori so'rovni rad etsa, API o'zi mos zaxira modelga o'tadi.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.Anthropic | None = None


class AIUnavailable(Exception):
    """AI o'chirilgan, kalit yo'q yoki API vaqtincha ishlamayapti."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if not settings.AI_ENABLED:
        raise AIUnavailable("ANTHROPIC_API_KEY sozlanmagan")
    if _client is None:
        _client = anthropic.Anthropic(timeout=90.0, max_retries=2)
    return _client


def _create(**kwargs):
    try:
        response = _get_client().beta.messages.create(
            model=settings.CLAUDE_MODEL,
            betas=[_FALLBACK_BETA],
            fallbacks="default",
            **kwargs,
        )
    except anthropic.AuthenticationError as e:
        log.error("Claude: noto'g'ri API kalit")
        raise AIUnavailable("API kalit noto'g'ri") from e
    except anthropic.RateLimitError as e:
        log.warning("Claude: so'rovlar limiti")
        raise AIUnavailable("So'rovlar limiti") from e
    except anthropic.APIStatusError as e:
        log.error("Claude API xatosi %s: %s", e.status_code, e.message)
        raise AIUnavailable(str(e.message)) from e
    except anthropic.APIConnectionError as e:
        log.warning("Claude: tarmoq xatosi")
        raise AIUnavailable("Tarmoq xatosi") from e

    if response.stop_reason == "refusal":
        raise AIUnavailable("So'rov rad etildi")
    return response


def _text(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


def chat(history: list[dict], user_context: str) -> str:
    """history: [{"role": "user"|"assistant", "content": str}, ...] — oxirgisi foydalanuvchi xabari."""
    response = _create(
        max_tokens=16000,
        output_config={"effort": "low"},
        system=[
            # Barqaror qism keshlanadi; foydalanuvchi konteksti undan keyin keladi.
            {"type": "text", "text": ASSISTANT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"Joriy foydalanuvchi haqida ma'lumot:\n{user_context}"},
        ],
        messages=history,
    )
    return _text(response)


_CATEGORY_ENUM = ["education", "kindergarten", "school", "medical", "contract", "other"]

_RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": {"type": ["number", "null"]},
        "date": {"type": ["string", "null"]},
        "stir": {"type": ["string", "null"]},
        "organization": {"type": ["string", "null"]},
        "category": {"type": "string", "enum": _CATEGORY_ENUM},
        "readable": {"type": "boolean"},
    },
    "required": ["amount", "date", "stir", "organization", "category", "readable"],
    "additionalProperties": False,
}

_STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "payments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                    "date": {"type": ["string", "null"]},
                    "stir": {"type": ["string", "null"]},
                    "category": {"type": "string", "enum": _CATEGORY_ENUM},
                },
                "required": ["description", "amount", "date", "stir", "category"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["source", "payments"],
    "additionalProperties": False,
}

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _file_block(data: bytes, mime: str) -> dict:
    b64 = base64.standard_b64encode(data).decode("ascii")
    if mime == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
    if mime in IMAGE_TYPES:
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
    raise AIUnavailable(f"Qo'llab-quvvatlanmaydigan fayl turi: {mime}")


def _structured(data: bytes, mime: str, prompt: str, schema: dict) -> dict:
    response = _create(
        max_tokens=16000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": [_file_block(data, mime), {"type": "text", "text": prompt}]}],
    )
    try:
        return json.loads(_text(response))
    except json.JSONDecodeError as e:
        raise AIUnavailable("AI javobini o'qib bo'lmadi") from e


def extract_receipt(data: bytes, mime: str) -> dict:
    return _structured(data, mime, RECEIPT_EXTRACTION_PROMPT, _RECEIPT_SCHEMA)


def extract_statement(data: bytes) -> dict:
    return _structured(data, "application/pdf", STATEMENT_EXTRACTION_PROMPT, _STATEMENT_SCHEMA)
