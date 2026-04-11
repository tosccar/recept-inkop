"""Extraherar receptdata från URL:er med recipe-scrapers och genererar PDF."""
import os
import re
import tempfile
import requests
from recipe_scrapers import scrape_html
from fpdf import FPDF

PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "recipes_pdf")
os.makedirs(PDF_DIR, exist_ok=True)


def extract_recipe_from_url(url: str) -> dict | None:
    """Hämtar en URL och försöker extrahera receptdata.
    Returnerar dict med name, ingredients, servings etc. eller None vid fel."""
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
    except requests.RequestException:
        return None

    try:
        scraper = scrape_html(resp.text, org_url=url)
    except Exception:
        # Sajten stöds inte av recipe-scrapers — försök HTML-fallback
        result = _fallback_extract(resp.text, url)
        if result:
            return result
        # Försök med headless-browser (för JS-renderade sajter som Coop)
        rendered = _render_with_browser(url)
        if rendered:
            # Skicka renderad HTML till Claude — mest pålitligt
            result = _claude_fallback_extract(rendered, url)
            if result and result.get("ingredients"):
                return result
        return _claude_fallback_extract(resp.text, url)

    # Extrahera ingredienser - försök parsa mängd och namn
    raw_ingredients = []
    try:
        raw_ingredients = scraper.ingredients()
    except Exception:
        pass

    parsed_ingredients = []
    for ing_str in raw_ingredients:
        parts = _split_ingredient(ing_str)
        parsed_ingredients.append(parts)

    # Gissa kategori från titel och ingredienser
    category = _guess_category(
        _safe_get(scraper, "title", ""),
        raw_ingredients,
    )

    # Gissa taggar
    from app.tags import suggest_tags
    tags = suggest_tags(
        _safe_get(scraper, "title", ""),
        raw_ingredients,
        category,
    )

    # Hämta tillagningsinstruktioner
    instructions = _safe_get(scraper, "instructions", "")

    # Hämta bild om tillgänglig
    image_url = _safe_get(scraper, "image", "")

    # Generera PDF
    title = _safe_get(scraper, "title", "Recept")
    servings = _safe_int(scraper, "yields", 4)
    pdf_path = _generate_recipe_pdf(
        title=title,
        servings=servings,
        ingredients=raw_ingredients,
        instructions=instructions,
        source_url=url,
        image_url=image_url,
    )

    return {
        "name": title,
        "source_url": url,
        "pdf_path": pdf_path,
        "servings": servings,
        "category": category,
        "ingredients": parsed_ingredients,
        "tags": tags,
        "notes": "",
    }


def _fallback_extract(html: str, url: str) -> dict | None:
    """Fallback-parser för sajter som recipe-scrapers inte stöder.
    Letar efter ingredienssektioner i HTML via vanliga mönster."""
    import html as html_module

    # Titel från <h1>
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    title = ""
    if title_match:
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        title = html_module.unescape(title)

    # Hitta ingredienssektionen
    raw_ingredients = []
    ing_match = re.search(
        r'[Ii]ngredienser\s*(?:</[^>]+>\s*)*(?:<[^>]+>\s*)*(.*?)(?:<[^>]*>(?:Tips|Gör så|Tillagning|Instruktion|Steg))',
        html, re.DOTALL
    )
    if not ing_match:
        # Bredare sökning
        ing_match = re.search(r'[Ii]ngredienser.*?(<[^>]+>.*?){3,}', html, re.DOTALL)

    if ing_match:
        section = ing_match.group(1) if ing_match.lastindex else ing_match.group(0)
        # Rensa HTML, behåll radbrytningar
        section = re.sub(r'<br\s*/?>', '\n', section)
        section = re.sub(r'<[^>]+>', '\n', section)
        section = html_module.unescape(section)
        lines = [line.strip() for line in section.split('\n') if line.strip()]
        # Filtrera: behåll rader som ser ut som ingredienser
        unit_pattern = re.compile(r'(?:\d+\s*(?:g|kg|dl|cl|ml|msk|tsk|krm|st|port|liter)\b|\d+\s+\w)')
        skip_pattern = re.compile(r'SEK|http|instagram|pinterest|facebook|twitter|@|View this|A post|Portioner|portioner', re.IGNORECASE)
        for line in lines:
            if skip_pattern.search(line):
                continue
            if unit_pattern.search(line) and len(line) < 80:
                raw_ingredients.append(line)

    if not title and not raw_ingredients:
        return None

    parsed_ingredients = [_split_ingredient(ing) for ing in raw_ingredients]
    category = _guess_category(title, raw_ingredients)
    from app.tags import suggest_tags
    tags = suggest_tags(title, raw_ingredients, category)

    # Hitta instruktioner
    instructions = ""
    inst_match = re.search(
        r'(?:Gör så|Tillagning|Instruktion|Steg)\s*(?:</[^>]+>\s*)*(?:<[^>]+>\s*)*(.*?)(?:<[^>]*>(?:Tips|Dela|Relatera|Kommentar))',
        html, re.DOTALL
    )
    if inst_match:
        section = inst_match.group(1)
        section = re.sub(r'<br\s*/?>', '\n', section)
        section = re.sub(r'<[^>]+>', '\n', section)
        section = html_module.unescape(section)
        instructions = '\n'.join(line.strip() for line in section.split('\n') if line.strip())

    # Försök hitta en receptbild i HTML
    image_url = _extract_image_from_html(html)

    pdf_path = _generate_recipe_pdf(
        title=title or "Recept",
        servings=4,
        ingredients=raw_ingredients,
        instructions=instructions,
        source_url=url,
        image_url=image_url,
    )

    return {
        "name": title,
        "source_url": url,
        "pdf_path": pdf_path,
        "servings": 4,
        "category": category,
        "ingredients": parsed_ingredients,
        "tags": tags,
        "notes": "",
    }


def _download_image(image_url: str) -> str | None:
    """Laddar ned en bild till en tempfil. Returnerar sökväg eller None."""
    if not image_url:
        return None
    try:
        resp = requests.get(image_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and not image_url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return None
        # Bestäm filändelse
        if "png" in content_type or image_url.lower().endswith(".png"):
            ext = ".png"
        elif "webp" in content_type or image_url.lower().endswith(".webp"):
            ext = ".webp"
        else:
            ext = ".jpg"
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name
    except Exception:
        return None


def _extract_image_from_html(html: str) -> str:
    """Försöker hitta en receptbild i HTML via Open Graph eller stor <img>."""
    # Open Graph-bild (vanligast för recept)
    og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    if og_match:
        return og_match.group(1)
    # Omvänd ordning på attributen
    og_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
    if og_match:
        return og_match.group(1)
    return ""


def _generate_recipe_pdf(title: str, servings: int, ingredients: list[str],
                          instructions: str, source_url: str,
                          image_url: str = "") -> str:
    """Genererar en snygg PDF med receptet och sparar lokalt."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Titel
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, _clean(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Portioner + källa
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"{servings} portioner", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Källa: {source_url}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Receptbild
    img_path = _download_image(image_url)
    if img_path:
        try:
            # Max bredd 170mm (sidan är 210mm med marginaler)
            pdf.image(img_path, w=170)
            pdf.ln(4)
        except Exception:
            pass
        finally:
            try:
                os.unlink(img_path)
            except OSError:
                pass

    # Ingredienser
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Ingredienser", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for ing in ingredients:
        pdf.cell(0, 7, f"- {_clean(ing)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Tillagning
    if instructions:
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Tillagning", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        steps = [s.strip() for s in instructions.split("\n") if s.strip()]
        for i, step in enumerate(steps, 1):
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(10, 7, f"{i}.")
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 7, _clean(step))
            pdf.ln(2)

    # Spara
    safe_name = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]
    filename = f"{safe_name}.pdf"
    filepath = os.path.join(PDF_DIR, filename)
    pdf.output(filepath)
    return filepath


def _clean(text: str) -> str:
    """Rensa text för PDF-rendering (ta bort ogiltiga tecken)."""
    if not text:
        return ""
    # Ersätt problematiska unicode-tecken med närmaste ASCII/latin1
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2026': '...', '\u00bd': '1/2',
        '\u00bc': '1/4', '\u00be': '3/4',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode('latin-1', errors='replace').decode('latin-1')


def _safe_get(scraper, attr: str, default: str) -> str:
    try:
        val = getattr(scraper, attr)()
        return val if val else default
    except Exception:
        return default


def _safe_int(scraper, attr: str, default: int) -> int:
    try:
        val = getattr(scraper, attr)()
        # yields() returnerar ofta "4 servings" eller "4 portioner"
        if isinstance(val, str):
            digits = "".join(c for c in val if c.isdigit())
            return int(digits) if digits else default
        return int(val)
    except Exception:
        return default


def _split_ingredient(text: str) -> dict:
    """Försöker separera mängd från ingrediensnamn.
    T.ex. '500 g kycklingfilé' → {'quantity': '500 g', 'name': 'kycklingfilé'}"""
    text = text.strip()
    if not text:
        return {"name": "", "quantity": "", "group_name": ""}

    # Hitta var mängden slutar och namnet börjar
    # Mönster: siffror + eventuell enhet i början
    parts = text.split()
    quantity_parts = []
    name_parts = []
    units = {"g", "kg", "dl", "cl", "ml", "l", "msk", "tsk", "st", "krm", "port", "paket", "burk", "pkt"}

    found_name = False
    for i, part in enumerate(parts):
        clean = part.strip(".,")
        if not found_name and (clean.replace(",", "").replace(".", "").replace("/", "").replace("½", "").replace("¼", "").replace("¾", "").isdigit()
                               or clean.lower() in units
                               or clean in ("ca", "ca.")):
            quantity_parts.append(part)
        else:
            found_name = True
            name_parts.append(part)

    return {
        "name": " ".join(name_parts),
        "quantity": " ".join(quantity_parts),
        "group_name": _guess_ingredient_group(" ".join(name_parts)),
    }


def _guess_ingredient_group(name: str) -> str:
    name_lower = name.lower()
    meat = ["kyckling", "fläsk", "nöt", "biff", "korv", "bacon", "skinka", "lamm",
            "färs", "fläskfilé", "kotlett", "entrecôte", "entrecote", "högrev",
            "bresaola", "prosciutto", "salami", "chorizo", "pancetta", "kalv",
            "vilt", "älg", "ren", "hjort", "anka", "and ", "kalkon"]
    fish = ["lax", "torsk", "räk", "fisk", "sej", "tonfisk", "sill", "mussl",
            "krabba", "hummer", "blåmussla", "pilgrimsmussla", "abborre",
            "gös", "rödspätta", "makrill", "sardiner", "ansjovis", "caviar"]
    dairy = ["mjölk", "grädde", "ost", "smör", "yoghurt", "crème", "creme",
             "kvarg", "kesella", "mascarpone", "ricotta", "parmesan",
             "mozzarella", "fetaost", "halloumi", "créme fraîche"]
    veg = ["lök", "tomat", "paprika", "morot", "potatis", "vitlök", "gurka",
           "sallad", "broccoli", "spenat", "squash", "zucchini", "svamp",
           "champinjon", "purjo", "selleri", "blomkål", "vitkål", "rödkål",
           "aubergine", "avokado", "sparris", "ärtor", "majs", "rödbet",
           "fänkål", "sockerärtor", "haricots"]
    dry = ["pasta", "ris", "mjöl", "socker", "nudl", "couscous", "bulgur",
           "linser", "bönor", "kikärtor", "spagetti", "penne", "fusilli",
           "tortilla", "bröd", "naan", "quinoa", "havregryn"]
    spice = ["salt", "peppar", "krydd", "oregano", "basilika", "timjan", "kanel",
             "paprikapulver", "chilipulver", "curry", "spiskummin", "ingefära",
             "koriander", "rosmarin", "dill", "persilja", "mynta", "soja",
             "sambal", "tabasco", "worcestershire", "fisksås", "sriracha"]

    for word in meat:
        if word in name_lower:
            return "kött & fisk"
    for word in fish:
        if word in name_lower:
            return "kött & fisk"
    for word in dairy:
        if word in name_lower:
            return "mejeri"
    for word in veg:
        if word in name_lower:
            return "grönsaker"
    for word in dry:
        if word in name_lower:
            return "torrvaror"
    for word in spice:
        if word in name_lower:
            return "kryddor"
    return ""


# Centrala ordlistor för kött/fisk-detektion (återanvänds i category + tags)
_MEAT_WORDS = [
    "kyckling", "kycklingfilé", "kycklingbröst", "kycklinglår", "kycklingklubba",
    "fläsk", "fläskfilé", "fläskkarré", "nöt", "nötfärs", "biff", "entrecôte",
    "högrev", "korv", "bacon", "skinka", "lamm", "lammfärs", "lammkotlett",
    "lammracks", "lammbog", "lammgryta", "färs", "blandfärs", "kalv",
    "bresaola", "prosciutto", "salami", "chorizo", "pancetta",
    "vilt", "älg", "ren", "hjort", "anka", "kalkon", "kotlett",
]
_FISH_WORDS = [
    "lax", "laxfilé", "torsk", "torskfilé", "räk", "räkor", "fisk",
    "sej", "tonfisk", "sill", "mussla", "blåmussla", "krabba",
    "abborre", "gös", "rödspätta", "makrill", "sardiner", "ansjovis",
]
_ALL_ANIMAL = _MEAT_WORDS + _FISH_WORDS


def _has_any(text: str, words: list[str]) -> bool:
    """Kollar om något ord i listan finns i texten."""
    return any(w in text for w in words)


def _guess_category(title: str, ingredients: list[str]) -> str:
    all_text = (title + " " + " ".join(ingredients)).lower()

    has_fish = _has_any(all_text, _FISH_WORDS)
    has_chicken = _has_any(all_text, ["kyckling", "kycklingfilé", "kycklingbröst",
                                       "kycklinglår", "kycklingklubba"])
    has_mince = _has_any(all_text, ["färs", "nötfärs", "blandfärs", "lammfärs",
                                     "kycklingfärs", "fläskfärs", "köttfärs"])
    has_meat = _has_any(all_text, [w for w in _MEAT_WORDS
                                    if "kyckling" not in w and "färs" not in w])

    # Bakning och dryck först (specifika kategorier)
    if _has_any(all_text, ["tårta", "kaka", "kakor", "muffins", "brownie",
                            "kladdkaka", "sockerkaka", "rulltårta", "cheesecake"]):
        return "kakor/tårtor"
    if _has_any(all_text, ["smoothie", "juice", "drink", "cocktail", "lemonad",
                            "glögg", "punch", "dryck"]):
        return "dryck"
    if _has_any(all_text, ["dessert", "efterrätt", "pannacotta", "mousse",
                            "glass", "sorbet", "crème brûlée", "panna cotta"]):
        return "efterrätt"

    # Kött/fisk
    if has_fish:
        return "fisk"
    if has_chicken:
        return "kyckling"
    if has_mince:
        return "färs"
    if _has_any(all_text, ["korv", "falukorv", "prinskorv", "grillkorv",
                            "bratwurst", "chorizo", "hot dog"]):
        return "korv"
    if has_meat:
        return "kött"

    # Sekundära kategorier
    if _has_any(all_text, ["soppa", "buljong"]):
        return "soppa"
    if _has_any(all_text, ["pasta", "spagetti", "penne", "tagliatelle", "fusilli"]):
        return "pasta"
    if _has_any(all_text, ["sallad"]):
        return "sallad"

    # Om inget kött/fisk hittades kan det vara vegetariskt
    if not _has_any(all_text, _ALL_ANIMAL):
        return "vegetariskt"

    return ""


def _guess_tags(ingredients: list[str], title: str) -> list[str]:
    tags = []
    all_text = (title + " " + " ".join(ingredients)).lower()

    # Veg: bara om inga animaliska ingredienser alls
    if not _has_any(all_text, _ALL_ANIMAL):
        tags.append("veg")

    return tags


def _claude_fallback_extract(html: str, url: str) -> dict | None:
    """Sista utväg: skickar HTML till Claude API för receptextraktion."""
    import os
    import json
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    # Rensa HTML — ta bort scripts/styles men behåll struktur
    import html as html_module
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL)
    text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL)
    text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = html_module.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Ta bort tomma rader, trimma, säkerställ UTF-8
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    text = '\n'.join(lines)
    # Säkerställ korrekt encoding
    text = text.encode('utf-8', errors='replace').decode('utf-8')
    text = text[:12000]

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"""Extrahera receptet från denna webbsidetext. Returnera BARA JSON:
{{
    "name": "Receptets namn",
    "servings": 4,
    "category": "en av: fisk, färs, korv, kött, kyckling, vegetariskt, pasta, soppa, sallad, dryck, förrätt, efterrätt, kakor/tårtor, övrigt",
    "ingredients": [{{"name": "namn", "quantity": "mängd", "group_name": "grupp"}}],
    "instructions": "Tillagningsinstruktioner",
    "notes": ""
}}
group_name: kött & fisk, mejeri, grönsaker, frukt, torrvaror, kryddor, övrigt.
Skriv allt på svenska. BARA JSON.

Text från {url}:
{text}""",
            }],
        )

        response = msg.content[0].text.strip()
        if "```" in response:
            lines = [l for l in response.split("\n") if not l.strip().startswith("```")]
            response = "\n".join(lines).strip()
        start = response.find("{")
        end = response.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        data = json.loads(response[start:end])

        if "error" in data:
            return None

        # Parsa ingredienser
        parsed_ingredients = data.get("ingredients", [])

        category = data.get("category", "")
        from app.tags import suggest_tags
        raw_ings = [f"{i.get('quantity','')} {i.get('name','')}".strip() for i in parsed_ingredients]
        tags = suggest_tags(data.get("name", ""), raw_ings, category)

        title = data.get("name", "Recept")
        servings = data.get("servings", 4)
        instructions = data.get("instructions", "")

        # Hämta bild
        image_url = _safe_get_from_html(html)

        pdf_path = _generate_recipe_pdf(
            title=title,
            servings=servings,
            ingredients=raw_ings,
            instructions=instructions,
            source_url=url,
            image_url=image_url,
        )

        return {
            "name": title,
            "source_url": url,
            "pdf_path": pdf_path,
            "servings": servings,
            "category": category,
            "ingredients": parsed_ingredients,
            "tags": tags,
            "notes": data.get("notes", ""),
        }

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Claude fallback-fel: {e}")
        return None


def _render_with_browser(url: str) -> str | None:
    """Renderar en sida med headless-browser för JS-tunga sajter."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20000)
            page.wait_for_timeout(3000)  # Vänta på JS-rendering
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Browser-rendering misslyckades: {e}")
        return None


def _safe_get_from_html(html: str) -> str:
    """Hämtar og:image från HTML."""
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
    if m:
        return m.group(1)
    m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
    if m:
        return m.group(1)
    return ""
