"""Röktester för Recept & Inköp.

Täcker det som berörs av beroendeuppdateringar: inloggning, sidmallar
(Starlette/Jinja2), formulär och filuppladdning (python-multipart), bildhantering
(Pillow), PDF (fpdf2/PyMuPDF), Word (python-docx) och receptinläsning
(recipe-scrapers/beautifulsoup4/soupsieve). Inga anrop görs till internet eller Claude API.

Kör i samma miljö som produktion (Docker-imagen), från projektmappen:

    docker build -t recept-inkop:test .
    docker run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/requirements-dev.txt:/app/requirements-dev.txt:ro" \
        recept-inkop:test sh -c "pip install -q pytest==9.2.0 httpx==0.28.1 && python -m pytest -q tests"
"""
import io
import json
import os

import pytest
from PIL import Image


def _jpeg_bytes(size=(40, 20), orientation=None, color=(200, 30, 30)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


# --- Inloggning ---

def test_requires_login(anon_client):
    resp = anon_client.get("/")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Basic"


def test_wrong_password_rejected(anon_client):
    resp = anon_client.get("/", auth=("testanvandare", "fel"))
    assert resp.status_code == 401


def test_static_files_served(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")


# --- Sidor ---

@pytest.mark.parametrize("path", [
    "/", "/add", "/suggestions", "/deals", "/menu", "/shopping-list",
    "/htmx/recipes", "/shopping-list?shared=1",
])
def test_pages_render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers["content-type"].startswith("text/html")


def test_recipe_flow(client, make_recipe):
    rid = make_recipe(name="Lax <script>alert(1)</script>")

    detail = client.get(f"/recipe/{rid}?added=1")
    assert detail.status_code == 200
    # Autoescape i Jinja2Templates: namnet ska visas som text, inte köras som skript.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail.text
    assert "<script>alert(1)</script>" not in detail.text
    assert "laxfilé" in detail.text

    assert client.get(f"/recipe/{rid}/edit").status_code == 200

    resp = client.post(f"/recipe/{rid}/rate", data={"score": "5", "comment": "Gott"})
    assert resp.status_code == 303

    resp = client.post(f"/recipe/{rid}/edit", data={
        "name": "Lax i ugn",
        "servings": "",  # tomt fält ska ge standardvärdet 4
        "category": "fisk",
        "ingredients_json": json.dumps([{"name": "lax", "quantity": "500 g"}]),
        "tags": ["laktosfri"],
    })
    assert resp.status_code == 303
    page = client.get(f"/recipe/{rid}").text
    assert "Lax i ugn" in page

    listing = client.get("/htmx/recipes", params={"search": "Lax i ugn"})
    assert "Lax i ugn" in listing.text

    dup = client.get("/api/check-duplicate", params={"name": "Lax i ugn"}).json()
    assert dup["duplicates"] and dup["duplicates"][0]["id"] == rid


def test_add_requires_name(client):
    resp = client.post("/add", data={"ingredients_json": "[]"})
    assert resp.status_code == 422


def test_unknown_recipe_redirects(client):
    resp = client.get("/recipe/999999")
    assert resp.status_code == 303


def test_delete_recipe(client, make_recipe):
    rid = make_recipe(name="Ska tas bort")
    assert client.post(f"/recipe/{rid}/delete").status_code == 303
    assert client.get(f"/recipe/{rid}").status_code == 303


# --- Bilder (python-multipart + Pillow) ---

def test_upload_image_applies_exif_rotation_and_rotate(client, make_recipe, data_dir):
    rid = make_recipe(name="Bildrecept")
    # Orientation 6 = ska roteras 90 grader, 40x20 blir 20x40.
    files = {"file": ("foto.jpg", _jpeg_bytes(orientation=6), "image/jpeg")}
    resp = client.post(f"/api/upload-image/{rid}", files=files)
    assert resp.status_code == 200, resp.text
    image_url = resp.json()["image_url"]
    path = os.path.join(data_dir, "recipe_images", os.path.basename(image_url))
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert img.size == (20, 40)

    served = client.get(image_url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"

    resp = client.post(f"/api/rotate-image/{rid}")
    assert resp.status_code == 200
    with Image.open(path) as img:
        assert img.size == (40, 20)


def test_upload_new_image_converts_png_to_jpeg(client, data_dir):
    img = Image.new("RGBA", (30, 30), (0, 128, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    files = {"file": ("bild.png", buf.getvalue(), "image/png")}
    resp = client.post("/api/upload-image-new", files=files)
    assert resp.status_code == 200, resp.text
    path = os.path.join(data_dir, "recipe_images", os.path.basename(resp.json()["image_url"]))
    with Image.open(path) as saved:
        assert saved.format == "JPEG"
        assert saved.mode == "RGB"


def test_upload_rejects_wrong_file_type(client, make_recipe):
    rid = make_recipe(name="Fel filtyp")
    files = {"file": ("virus.exe", b"MZ....", "application/octet-stream")}
    resp = client.post(f"/api/upload-image/{rid}", files=files)
    assert resp.status_code == 400


# --- Meny, inköpslista, erbjudanden och förslag ---

def test_menu_and_shopping_list(client, make_recipe):
    rid = make_recipe(name="Kycklinggryta", category="kyckling",
                      ingredients=[{"name": "kycklingfilé", "quantity": "500 g"},
                                   {"name": "ris", "quantity": "4 dl"}])

    assert client.post("/menu/generate").status_code == 303
    menu = client.get("/menu")
    assert menu.status_code == 200

    resp = client.post(f"/recipe/{rid}/add-to-list", data={"servings": "2"})
    assert resp.status_code == 303
    shopping = client.get("/shopping-list")
    assert shopping.status_code == 200
    assert "kycklingfilé" in shopping.text

    from app.database import SessionLocal
    from app.models import ShoppingItem, MenuSlot
    db = SessionLocal()
    try:
        item_id = db.query(ShoppingItem).first().id
        slot = db.query(MenuSlot).first()
        slot_id = slot.id if slot else None
    finally:
        db.close()

    toggled = client.post(f"/htmx/shopping-list/toggle/{item_id}")
    assert toggled.status_code == 200 and toggled.text.strip()

    if slot_id:
        assert client.post(f"/htmx/menu/reroll/{slot_id}").status_code == 200
        assert client.post(f"/htmx/menu/servings/{slot_id}", data={"servings": "6"}).status_code == 200
        assert client.post(f"/htmx/menu/add-to-list/{slot_id}").status_code == 200

    assert client.post(f"/htmx/shopping-list/remove/{item_id}").status_code == 200
    assert client.post("/shopping-list/clear").status_code == 303


def test_deals_and_suggestions_api(client):
    resp = client.post("/api/deals", data={"product_name": "Laxfilé", "price": "99 kr"})
    assert resp.status_code == 200 and resp.json()["status"] == "created"
    deals = client.get("/api/deals").json()
    assert any(d["product"] == "Laxfilé" for d in deals)
    assert client.get("/api/deals/matches").status_code == 200
    assert client.get("/deals").status_code == 200

    resp = client.post("/api/suggestions", data={"recipe_name": "Fiskgratäng"})
    assert resp.status_code == 200
    sid = resp.json()["id"]
    assert client.post(f"/suggestions/{sid}/accept").status_code == 303
    assert client.get("/api/taste-profile").status_code == 200

    cleared = client.post("/api/deals/clear-week").json()
    assert cleared["cleared"] >= 1


# --- PDF, Word och receptinläsning ---

def test_recipe_pdf_with_image(tmp_path, monkeypatch):
    """fpdf2 bäddar in bilden via Pillow, PyMuPDF läser tillbaka texten."""
    import fitz
    from app import scraper

    img_path = tmp_path / "bild.jpg"
    img_path.write_bytes(_jpeg_bytes(size=(120, 80)))
    monkeypatch.setattr(scraper, "PDF_DIR", str(tmp_path))
    monkeypatch.setattr(scraper, "_download_image", lambda url: str(img_path))

    pdf_path = scraper._generate_recipe_pdf(
        title="Testrecept", servings=4, ingredients=["400 g lax", "8 potatisar"],
        instructions="Sätt ugnen på 200 grader.\nGrädda i 20 minuter.",
        source_url="https://example.test/recept", image_url="https://example.test/bild.jpg",
    )
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        assert page.get_images(), "bilden bäddades inte in i PDF:en"
        text = page.get_text()
    assert "Ingredienser" in text and "400 g lax" in text

    from app.file_importer import extract_text_from_file
    assert "Tillagning" in extract_text_from_file(pdf_path)


def test_docx_import_and_convert(tmp_path):
    from docx import Document
    from app.file_importer import extract_text_from_file, convert_to_pdf

    path = tmp_path / "Pannkakor.docx"
    doc = Document()
    doc.add_paragraph("3 dl vetemjöl")
    doc.add_paragraph("6 dl havredryck")
    doc.save(path)

    assert "havredryck" in extract_text_from_file(str(path))
    pdf = convert_to_pdf(str(path), str(tmp_path))
    assert pdf and os.path.getsize(pdf) > 0


_RECIPE_HTML = """<!doctype html><html lang="sv"><head><title>Pannkakor</title>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Recipe", "name": "Laktosfria pannkakor",
 "recipeYield": "4", "recipeIngredient": ["3 dl vetemjöl", "6 dl havredryck", "3 ägg"],
 "recipeInstructions": [{"@type": "HowToStep", "text": "Vispa ihop allt."}]}
</script></head>
<body><ul class="ingredients"><li>3 dl vetemjöl</li><li>6 dl havredryck</li></ul>
<template><li>ska inte räknas</li></template></body></html>"""


def test_css_selectors_soupsieve():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_RECIPE_HTML, "html.parser")
    items = [li.get_text() for li in soup.select("ul.ingredients > li:nth-child(n)")]
    assert items == ["3 dl vetemjöl", "6 dl havredryck"]


def test_extract_recipe_from_url_offline(client, monkeypatch):
    """Hela flödet för URL-import, med nätverket ersatt av en lokal sida."""
    from app import scraper

    class FakeResponse:
        text = _RECIPE_HTML
        status_code = 200
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(scraper.requests, "get", lambda *a, **kw: FakeResponse())
    monkeypatch.setattr(scraper, "_render_with_browser", lambda url: None)

    resp = client.post("/api/extract-url", data={"url": "https://www.ica.se/recept/laktosfria-pannkakor-123456/"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == "Laktosfria pannkakor"
    names = " ".join(i["name"] for i in data["ingredients"])
    assert "havredryck" in names
