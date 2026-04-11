"""Analyserar receptbilder — Claude API (primär) eller OCR+LLM (fallback)."""
import base64
import json
import io
import logging
import os
import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()
logger = logging.getLogger(__name__)

# --- Claude API (primär) ---

_CLAUDE_PROMPT = """Analysera bilden och extrahera receptdata.

Returnera BARA ett JSON-objekt:
{
    "name": "Receptets namn",
    "servings": 4,
    "category": "en av: fisk, färs, korv, kött, kyckling, vegetariskt, pasta, soppa, sallad, dryck, förrätt, efterrätt, kakor/tårtor, snacks, övrigt",
    "ingredients": [
        {"name": "ingrediensnamn", "quantity": "mängd med enhet", "group_name": "grupp"}
    ],
    "instructions": "Tillagningsinstruktioner, steg separerade med radbrytning",
    "notes": ""
}

group_name: kött & fisk, mejeri, grönsaker, frukt, torrvaror, kryddor, eller övrigt.

VIKTIGT: Skriv ALLT på svenska — namn, ingredienser, instruktioner, anteckningar. Översätt INTE till engelska.
Behåll originalspråket om receptet är på svenska. Om det är på annat språk, översätt till svenska.
Om bilden inte innehåller ett recept: {"error": "Bilden innehåller inget recept"}
Returnera BARA JSON."""


def analyze_with_claude(image_data: bytes, content_type: str = "image/jpeg") -> dict | None:
    """Analyserar receptbild med Claude API (vision)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY saknas")
        return {"error": "API-nyckel saknas. Lägg till ANTHROPIC_API_KEY i .env"}

    media_map = {
        "image/jpeg": "image/jpeg", "image/jpg": "image/jpeg",
        "image/png": "image/png", "image/webp": "image/webp",
    }
    media_type = media_map.get(content_type, "image/jpeg")
    b64 = base64.standard_b64encode(image_data).decode("utf-8")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": _CLAUDE_PROMPT},
                ],
            }],
        )
    except Exception as e:
        err = str(e)
        if "credit balance" in err:
            return {"error": "API-krediter slut. Fyll på på console.anthropic.com"}
        logger.error(f"Claude API-fel: {e}")
        return None

    text = msg.content[0].text.strip()
    return _parse_json_response(text)


# --- OCR + LLM (fallback) ---

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
_ocr_reader = None

_STRUCTURE_PROMPT = """Du får OCR-text från en receptbild. Tolka och returnera BARA JSON:

{{
    "name": "Receptets namn",
    "servings": 4,
    "category": "en av: fisk, färs, korv, kött, kyckling, vegetariskt, pasta, soppa, sallad, dryck, förrätt, efterrätt, kakor/tårtor, snacks, övrigt",
    "ingredients": [
        {{"name": "ingrediensnamn", "quantity": "mängd med enhet", "group_name": "grupp"}}
    ],
    "instructions": "Tillagningsinstruktioner",
    "notes": ""
}}

group_name: kött & fisk, mejeri, grönsaker, frukt, torrvaror, kryddor, övrigt.
Svenska. Returnera BARA JSON.

OCR-text:
{ocr_text}"""


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["sv", "en"], gpu=False, verbose=False)
    return _ocr_reader


def extract_text_from_image(image_data: bytes) -> str:
    """Extraherar text ur bild med OCR."""
    try:
        reader = _get_ocr_reader()
        image = Image.open(io.BytesIO(image_data))
        import numpy as np
        results = reader.readtext(np.array(image))
        results.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
        return "\n".join(text for _, text, conf in results if conf > 0.3)
    except Exception as e:
        logger.error("OCR-fel: %s", str(e).encode("ascii", "replace").decode())
        return ""


def structure_text_to_recipe(ocr_text: str) -> dict | None:
    """Strukturerar OCR-text till recept med Ollama/Mistral."""
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": _STRUCTURE_PROMPT.format(ocr_text=ocr_text),
            "stream": False,
            "options": {"temperature": 0.1},
        }, timeout=60)
        resp.raise_for_status()
    except requests.ConnectionError:
        return {"error": "Ollama körs inte. Starta Ollama först."}
    except Exception as e:
        logger.error(f"Ollama-fel: {e}")
        return None

    text = resp.json().get("response", "").strip()
    return _parse_json_response(text)


# --- Gemensamt ---

def _parse_json_response(text: str) -> dict | None:
    """Parsar JSON ur ett LLM-svar."""
    if "```" in text:
        lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Kunde inte parsa JSON: {text[:200]}")
        return None

    if "error" in data:
        return data

    from app.tags import suggest_tags
    raw_ings = [f"{i.get('quantity','')} {i.get('name','')}".strip() for i in data.get("ingredients", [])]
    tags = suggest_tags(data.get("name", ""), raw_ings, data.get("category", ""))

    return {
        "name": data.get("name", "Okänt recept"),
        "servings": data.get("servings", 4),
        "category": data.get("category", ""),
        "ingredients": data.get("ingredients", []),
        "instructions": data.get("instructions", ""),
        "tags": tags,
        "notes": data.get("notes", ""),
    }
