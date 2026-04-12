#!/bin/bash
# Kopiera väntande filer till persistent disk (körs bara en gång)
if [ -d /tmp/upload_temp ] && [ "$(ls /tmp/upload_temp 2>/dev/null)" ]; then
    mkdir -p /data/recipes_pdf /data/recipe_images
    cp -n /tmp/upload_temp/*.pdf /data/recipes_pdf/ 2>/dev/null || true
    cp -n /tmp/upload_temp/*.jpg /data/recipe_images/ 2>/dev/null || true
    cp -n /tmp/upload_temp/*.png /data/recipe_images/ 2>/dev/null || true
    echo "Kopierade filer till persistent disk"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
