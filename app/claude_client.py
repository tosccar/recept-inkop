"""Gemensam konfiguration och svarshantering för Claude API-anrop.

Modellen styrs med miljövariabeln RECEPT_CLAUDE_MODEL (standard: claude-sonnet-5-5).
När en modell pensioneras räcker det att ändra RECEPT_CLAUDE_MODEL i .env.
Prefixet RECEPT_ undviker krock med CLAUDE_*-variabler som Claude Code sätter.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.getenv("RECEPT_CLAUDE_MODEL", "claude-sonnet-5-5")

# Tänkandet räknas in i max_tokens, så gränsen måste ha marginal utöver svaret.
CLAUDE_MAX_TOKENS = int(os.getenv("RECEPT_CLAUDE_MAX_TOKENS", "16000"))

# Enkla extraktionsuppgifter: låg effort ger snabba och billiga svar.
CLAUDE_EFFORT = os.getenv("RECEPT_CLAUDE_EFFORT", "low")


def claude_request_kwargs() -> dict:
    """Standardparametrar för messages.create()."""
    return {
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "output_config": {"effort": CLAUDE_EFFORT},
    }


def response_text(msg) -> str:
    """Returnerar svarets text, oavsett ordning på innehållsblocken.

    Nyare modeller kan börja svaret med ett (tomt) thinking-block,
    så texten läses via blocktyp i stället för position.
    Höjer RuntimeError om svaret avvisades, kapades eller saknar text.
    """
    stop_reason = getattr(msg, "stop_reason", None)
    if stop_reason == "refusal":
        raise RuntimeError("Claude avböjde förfrågan (stop_reason=refusal)")
    if stop_reason == "max_tokens":
        raise RuntimeError(
            f"Claude-svaret kapades vid max_tokens={CLAUDE_MAX_TOKENS}; höj RECEPT_CLAUDE_MAX_TOKENS"
        )

    text = "".join(
        block.text for block in msg.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise RuntimeError(f"Claude-svaret innehöll ingen text (stop_reason={stop_reason})")
    return text
