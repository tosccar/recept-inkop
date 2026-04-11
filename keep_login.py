"""Engångsskript för att logga in på Google Keep.
Kör: python keep_login.py

Lösenordet visas inte i terminalen och sparas aldrig.
Bara en autentiseringstoken sparas lokalt (keep_token.json).
"""
import getpass
import json
import gkeepapi

EMAIL = "carina.m.oscarsson@gmail.com"
TOKEN_FILE = "keep_token.json"

print("=== Google Keep-inloggning ===")
print(f"Konto: {EMAIL}")
print("Ange ditt Google-lösenord (det visas inte medan du skriver):")
password = getpass.getpass("Lösenord: ")

print("Loggar in...")
try:
    keep = gkeepapi.Keep()
    keep.login(EMAIL, password)
    master_token = keep.getMasterToken()

    with open(TOKEN_FILE, "w") as f:
        json.dump({"email": EMAIL, "master_token": master_token}, f)

    print(f"Klart! Token sparad i {TOKEN_FILE}")
    print("Du kan nu använda 'Skicka till Google Keep' i appen.")
    print("Lösenordet har INTE sparats.")
except Exception as e:
    print(f"Fel: {e}")
    print("Kontrollera att lösenordet är korrekt.")
