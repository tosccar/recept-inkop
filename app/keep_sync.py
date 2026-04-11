"""Synkar inköpslistan till Google Keep via OAuth2."""
import logging
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent.parent
CREDENTIALS_FILE = PROJECT_DIR / "credentials.json"
TOKEN_FILE = PROJECT_DIR / "keep_token.json"
KEEP_LIST_TITLE = "Inköpslistan"

_keep = None
_logged_in = False


def _get_keep():
    """Loggar in på Google Keep via OAuth2 (sparad token)."""
    global _keep, _logged_in
    if _logged_in and _keep:
        return _keep

    if not TOKEN_FILE.exists():
        logger.error("Ingen Keep-token. Kör /keep-login först.")
        return None

    try:
        import gkeepapi
        token_data = json.loads(TOKEN_FILE.read_text())
        master_token = token_data.get("master_token")
        email = token_data.get("email")

        if not master_token or not email:
            logger.error("Ogiltig token-fil")
            return None

        _keep = gkeepapi.Keep()
        _keep.authenticate(email, master_token)
        _keep.sync()
        _logged_in = True
        logger.info(f"Inloggad i Google Keep som {email}")
        return _keep
    except Exception as e:
        logger.error(f"Keep-inloggning misslyckades: {e}")
        _keep = None
        _logged_in = False
        return None


def do_keep_login(email: str, password: str) -> dict:
    """Loggar in med Google-konto och sparar master token.

    Använder gpsoauth för att hämta master token.
    password kan vara app-lösenord eller vanligt lösenord.
    """
    try:
        import gkeepapi
        keep = gkeepapi.Keep()
        keep.login(email, password)
        master_token = keep.getMasterToken()

        # Spara token
        TOKEN_FILE.write_text(json.dumps({
            "email": email,
            "master_token": master_token,
        }))

        global _keep, _logged_in
        _keep = keep
        _logged_in = True

        return {"status": "ok", "email": email}
    except Exception as e:
        return {"error": str(e)}


def do_keep_login_oauth() -> dict:
    """Loggar in via OAuth2 i webbläsaren.

    Kräver credentials.json från Google Cloud Console.
    """
    if not CREDENTIALS_FILE.exists():
        return {"error": "credentials.json saknas. Ladda ner från Google Cloud Console."}

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        # OAuth2-scope för Keep
        SCOPES = ["https://www.googleapis.com/auth/keep"]

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            scopes=SCOPES,
        )
        creds = flow.run_local_server(port=8099, prompt="consent")

        # Spara credentials
        TOKEN_FILE.write_text(json.dumps({
            "email": "oauth",
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "type": "oauth2",
        }))

        return {"status": "ok", "message": "OAuth-inloggning klar!"}
    except Exception as e:
        return {"error": str(e)}


def sync_shopping_list(items: list[dict]) -> dict:
    """Synkar inköpslistan till Google Keep."""
    keep = _get_keep()
    if not keep:
        return {"error": "Inte inloggad i Google Keep. Gå till Inställningar och logga in."}

    try:
        keep.sync()

        # Hitta befintlig lista eller skapa ny
        existing = None
        for note in keep.all():
            if note.title == KEEP_LIST_TITLE and not note.trashed:
                existing = note
                break

        if existing:
            # Rensa befintliga items
            if hasattr(existing, 'items'):
                for item in list(existing.items):
                    item.delete()
        else:
            existing = keep.createList(KEEP_LIST_TITLE)

        # Gruppera per recept
        groups = {}
        for item in items:
            key = item.get("recipe_name", "Övrigt")
            if key not in groups:
                groups[key] = []
            groups[key].append(item)

        # Lägg till items
        for recipe_name, recipe_items in groups.items():
            existing.add(f"── {recipe_name} ──", False)
            for item in recipe_items:
                qty = item.get("quantity", "").strip()
                name = item.get("name", "").strip()
                text = f"{qty} {name}".strip() if qty else name
                checked = bool(item.get("checked", False))
                existing.add(text, checked)

        keep.sync()
        total = sum(len(v) for v in groups.values())
        logger.info(f"Synkade {total} varor till Google Keep")
        return {"status": "ok", "count": total}

    except Exception as e:
        logger.error(f"Keep-sync-fel: {e}")
        return {"error": f"Kunde inte synka: {str(e)}"}


def is_logged_in() -> bool:
    """Kollar om vi har en sparad Keep-token."""
    return TOKEN_FILE.exists()
