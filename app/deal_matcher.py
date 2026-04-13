"""AI-baserad matchning mellan ingredienser och veckans erbjudanden."""
import json
import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def generate_ai_matches(db) -> int:
    """Genererar AI-matchningar mellan alla unika ingredienser och veckans erbjudanden.

    Returnerar antal matchningar som sparades.
    """
    from app.models import Recipe, Ingredient, Deal, DealMatch
    from sqlalchemy.orm import joinedload

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY saknas, kan inte göra AI-matchning")
        return 0

    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()

    # Kolla om vi redan har matchningar för denna vecka
    existing = db.query(DealMatch).filter(
        DealMatch.year == year, DealMatch.week_number == week
    ).count()
    if existing > 0:
        logger.info(f"AI-matchningar finns redan för v{week} ({existing} st)")
        return existing

    # Hämta veckans erbjudanden
    deals = db.query(Deal).filter(Deal.year == year, Deal.week_number == week).all()
    if not deals:
        return 0

    # Hämta alla unika ingredienser
    ingredients = db.query(Ingredient.name).distinct().all()
    unique_ings = sorted(set(ing[0].strip().lower() for ing in ingredients if ing[0].strip()))

    # Filtrera triviala
    from app.crud import _TRIVIAL_INGREDIENTS
    unique_ings = [i for i in unique_ings if i not in _TRIVIAL_INGREDIENTS]

    # Bygg deal-lista
    deal_list = [f"{d.product_name} ({d.price})" for d in deals]

    # Skicka till Claude
    matches = _ask_claude_for_matches(api_key, unique_ings, deal_list)
    if not matches:
        return 0

    # Spara matchningar
    deal_map = {d.product_name.lower(): d for d in deals}
    saved = 0
    for match in matches:
        ingredient = match.get("ingredient", "").lower().strip()
        deal_name = match.get("deal", "").strip()

        # Hitta deal-objektet
        deal = None
        for dname, d in deal_map.items():
            if deal_name.lower() in dname or dname in deal_name.lower():
                deal = d
                break

        if not deal:
            # Försök matcha på produktnamn
            for d in deals:
                if deal_name.lower() in d.product_name.lower():
                    deal = d
                    break

        if deal and ingredient:
            db.add(DealMatch(
                ingredient=ingredient,
                deal_product=deal.product_name,
                deal_price=deal.price,
                week_number=week,
                year=year,
            ))
            saved += 1

    db.commit()
    logger.info(f"Sparade {saved} AI-matchningar för v{week}")
    return saved


def _ask_claude_for_matches(api_key: str, ingredients: list[str], deals: list[str]) -> list[dict]:
    """Frågar Claude vilka ingredienser som matchar vilka erbjudanden."""
    import anthropic

    # Begränsa storlek
    ing_text = "\n".join(f"- {i}" for i in ingredients[:200])
    deal_text = "\n".join(f"- {d}" for d in deals)

    prompt = f"""Jag har en lista med ingredienser från mina recept och en lista med veckans erbjudanden från ICA.

Matcha ingredienser mot erbjudanden där produkten rimligen kan användas som den ingrediensen.

REGLER:
- Samma djurslag krävs: kycklingfärs matchar INTE nötfärs
- Liknande styckdelar OK: fläskfilé matchar fläskytterfilé
- Generella termer matchar specifika: "kyckling" matchar "kycklingbröstfilé"
- "färs" utan specifikation matchar "blandfärs" eller "nötfärs"
- Mejeriprodukter: "grädde" matchar "vispgrädde", "mjölk" matchar "laktosfri mjölk"
- Grönsaker: "tomater" matchar "plommontomater", "paprika" matchar "röd paprika"
- Matcha INTE om produkterna är fundamentalt olika

Returnera BARA en JSON-lista:
[{{"ingredient": "ingrediensnamn", "deal": "erbjudandenamn"}}]

Om ingen matchning finns för en ingrediens, hoppa över den.

INGREDIENSER:
{ing_text}

ERBJUDANDEN:
{deal_text}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )

        response = msg.content[0].text.strip()

        # Parsa JSON
        if "```" in response:
            lines = [l for l in response.split("\n") if not l.strip().startswith("```")]
            response = "\n".join(lines).strip()

        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])

    except Exception as e:
        logger.error(f"Claude matchnings-fel: {e}")

    return []


def get_ai_match(db, ingredient_name: str) -> dict | None:
    """Hämtar AI-matchning för en ingrediens för aktuell vecka."""
    from app.models import DealMatch
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()

    match = db.query(DealMatch).filter(
        DealMatch.ingredient == ingredient_name.lower().strip(),
        DealMatch.year == year,
        DealMatch.week_number == week,
    ).first()

    if match:
        return {
            "deal": match.deal_product,
            "price": match.deal_price,
        }
    return None


def get_all_ai_matches(db) -> dict:
    """Hämtar alla AI-matchningar för aktuell vecka som dict: ingredient -> deal_info."""
    from app.models import DealMatch
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()

    matches = db.query(DealMatch).filter(
        DealMatch.year == year,
        DealMatch.week_number == week,
    ).all()

    return {
        m.ingredient: {"deal": m.deal_product, "price": m.deal_price}
        for m in matches
    }
