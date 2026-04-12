#!/bin/bash
# Kopiera väntande filer till persistent disk
if [ -d /tmp/upload_temp ] && [ "$(ls /tmp/upload_temp 2>/dev/null)" ]; then
    mkdir -p /data/recipes_pdf /data/recipe_images
    for f in /tmp/upload_temp/*; do
        dest="/data/recipes_pdf/$(basename "$f")"
        # Kopiera om filen inte finns eller är tom
        if [ ! -s "$dest" ]; then
            cp "$f" "$dest"
            echo "Kopierade: $(basename "$f")"
        fi
    done
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
