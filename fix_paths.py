"""Fixar pdf_path till relativa filnamn."""
import sqlite3
import os

conn = sqlite3.connect("recipes.db")
c = conn.cursor()

rows = c.execute("SELECT id, pdf_path FROM recipes WHERE pdf_path IS NOT NULL").fetchall()
updated = 0
for rid, path in rows:
    if not path:
        continue
    filename = os.path.basename(path)
    if filename != path:
        c.execute("UPDATE recipes SET pdf_path = ? WHERE id = ?", (filename, rid))
        updated += 1

conn.commit()
print(f"Uppdaterade {updated} sökvägar")

for row in c.execute("SELECT id, pdf_path FROM recipes WHERE pdf_path IS NOT NULL LIMIT 5").fetchall():
    print(f"  {row[0]}: {row[1]}")
conn.close()
