"""Gemensam testuppsättning.

Miljövariablerna måste sättas innan appen importeras, eftersom databasens
och bildmappens sökvägar räknas ut vid import.
"""
import os
import tempfile

import pytest

TEST_USER = "testanvandare"
TEST_PASSWORD = "testlosenord"

_DATA_DIR = tempfile.mkdtemp(prefix="recept-test-")
os.environ["DATA_DIR"] = _DATA_DIR
os.environ["AUTH_USERNAME"] = TEST_USER
os.environ["AUTH_PASSWORD"] = TEST_PASSWORD
# Tom nyckel: inga anrop till Claude API under testerna (load_dotenv skriver inte över).
os.environ["ANTHROPIC_API_KEY"] = ""


@pytest.fixture(scope="session")
def data_dir():
    return _DATA_DIR


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="session")
def client(app):
    """Inloggad klient. `with` kör appens lifespan, som skapar databasen."""
    from fastapi.testclient import TestClient
    with TestClient(app, follow_redirects=False) as c:
        c.auth = (TEST_USER, TEST_PASSWORD)
        yield c


@pytest.fixture(scope="session")
def anon_client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def make_recipe(client):
    """Skapar ett recept via formuläret och returnerar dess id."""
    def _make(name="Testlax med potatis", category="fisk", ingredients=None):
        if ingredients is None:
            ingredients = [
                {"name": "laxfilé", "quantity": "400 g", "group_name": ""},
                {"name": "potatis", "quantity": "8 st", "group_name": ""},
            ]
        import json
        resp = client.post("/add", data={
            "name": name,
            "source_type": "url",
            "source_link": "",
            "servings": "4",
            "category": category,
            "notes": "Testanteckning",
            "ingredients_json": json.dumps(ingredients),
            "tags": ["laktosfri", "snabb"],
        })
        assert resp.status_code == 303, resp.text
        location = resp.headers["location"]
        assert location.startswith("/recipe/")
        return int(location.rsplit("/", 1)[-1])
    return _make
