"""Hämtar erbjudanden från ICA Maxi Östersund via ICAs publika API."""
import re
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ICA_STORE_ID = 13422
ICA_OFFERS_API = f"https://apimgw-pub.ica.se/sverige/digx/offerreader/v1/offers/store/{ICA_STORE_ID}"
ICA_TOKEN_PAGE = "https://www.ica.se/butiker/maxi/ostersund/maxi-ica-stormarknad-ostersund-1003733/erbjudanden/"

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Matkategorier från ICAs API (articleGroupId)
_FOOD_CATEGORY_IDS = {
    1,   # Chark & ost
    2,   # Fisk & skaldjur
    3,   # Bröd, kex & bageri
    4,   # Frukt & Grönt
    5,   # Kött
    6,   # Mejeri, ägg
    7,   # Fryst
    8,   # Dryck
    9,   # Skafferivaror
    10,  # Glass & godis
}

# Nyckelord för icke-matprodukter (sekundärt filter)
_NON_FOOD_WORDS = [
    "schampo", "balsam", "tandkräm", "tvål", "tvättmedel", "sköljmedel",
    "bomullsrondell", "bomullspinnar", "hundpåsar", "kattmat", "kattfoder",
    "wc rengöring", "wc-rengöring", "ansiktsvård", "dagcreme", "dagkräm",
    "nattcreme", "nattkräm", "ögoncreme", "ögonkräm", "duschcreme",
    "duschkräm", "hudvård", "ansiktskräm", "deodorant", " deo,",
    "eltandborste", "tandborstrefill",
]


def _get_public_token() -> str | None:
    """Hämtar en anonym access token från ICAs butikssida."""
    try:
        resp = requests.get(ICA_TOKEN_PAGE, timeout=15, headers={
            "User-Agent": _USER_AGENT,
        })
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Kunde inte hämta ICA-sidan: {e}")
        return None

    match = re.search(r'"publicAccessToken"\s*:\s*"([^"]+)"', resp.text)
    if match:
        return match.group(1)

    logger.error("Hittade ingen publicAccessToken i ICA-sidans HTML")
    return None


def fetch_ica_deals(food_only: bool = True) -> list[dict]:
    """Hämtar veckans erbjudanden från ICA Maxi Östersund.

    Args:
        food_only: Om True, filtreras icke-matprodukter bort.

    Returnerar lista med dicts:
        product_name, price, original_price, category, valid_from, valid_to
    """
    token = _get_public_token()
    if not token:
        return []

    try:
        resp = requests.get(ICA_OFFERS_API, timeout=30, headers={
            "User-Agent": _USER_AGENT,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        })
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Kunde inte hämta erbjudanden från ICA API: {e}")
        return []

    try:
        data = resp.json()
    except ValueError:
        logger.error("Ogiltigt JSON-svar från ICA API")
        return []

    offers = data if isinstance(data, list) else data.get("offers", [])

    results = []
    for offer in offers:
        parsed = _parse_offer(offer, food_only)
        if parsed:
            results.append(parsed)

    logger.info(f"Hämtade {len(results)} erbjudanden från ICA Maxi Östersund")
    return results


def _parse_offer(offer: dict, food_only: bool) -> dict | None:
    """Parsar ett enskilt erbjudande från API-svaret."""
    details = offer.get("details", {})
    category_info = offer.get("category", {})

    name = details.get("name", "").strip()
    if not name:
        return None

    # Filtrera på matkategorier + nyckelordfilter
    if food_only:
        group_id = category_info.get("articleGroupId", 0)
        if group_id not in _FOOD_CATEGORY_IDS:
            return None
        name_lower = name.lower()
        if any(w in name_lower for w in _NON_FOOD_WORDS):
            return None

    # Produktnamn med märke
    brand = details.get("brand", "").strip()
    package_info = details.get("packageInformation", "").strip()
    full_name = name
    if brand:
        full_name = f"{name}, {brand}"
    if package_info:
        full_name = f"{full_name}, {package_info}"

    # Pristext
    price = details.get("mechanicInfo", "")
    if not price:
        parsed_mech = offer.get("parsedMechanics", {})
        v1 = parsed_mech.get("value1", "")
        v2 = parsed_mech.get("value2", "")
        if v1 and v2:
            price = f"{v1} {v2} kr"

    # Ordinarie pris
    original_price = ""
    stores = offer.get("stores", [])
    if stores:
        ref_text = stores[0].get("referencePriceText", "")
        if ref_text:
            original_price = ref_text.replace("Ord.pris ", "").rstrip(".")
        else:
            price_from = stores[0].get("regularPriceFrom", 0)
            price_to = stores[0].get("regularPriceTo", 0)
            if price_from:
                if price_from == price_to:
                    original_price = f"{price_from:.2f} kr".replace(".", ":")
                else:
                    original_price = f"{price_from:.2f}-{price_to:.2f} kr".replace(".", ":")

    # Giltighetsdatum
    valid_from = (offer.get("validFrom") or "")[:10]
    valid_to = (offer.get("validTo") or "")[:10]

    # Kategori
    category = category_info.get("articleGroupName", "")

    return {
        "product_name": full_name,
        "price": price,
        "original_price": original_price,
        "category": category,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def save_deals_to_db(db, deals: list[dict]) -> dict:
    """Sparar hämtade erbjudanden till databasen.

    Returnerar {"saved": int, "week": int, "year": int, "cleared": int}
    """
    from app.models import Deal

    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()

    cleared = db.query(Deal).filter(
        Deal.year == year,
        Deal.week_number == week,
    ).delete()

    saved = 0
    for deal_data in deals:
        deal = Deal(
            product_name=deal_data["product_name"],
            price=deal_data["price"],
            original_price=deal_data.get("original_price") or None,
            week_number=week,
            year=year,
            valid_from=deal_data.get("valid_from") or None,
            valid_to=deal_data.get("valid_to") or None,
        )
        db.add(deal)
        saved += 1

    db.commit()
    return {"saved": saved, "week": week, "year": year, "cleared": cleared}
