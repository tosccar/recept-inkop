FROM python:3.12-slim

# Hämta Debians säkerhetsrättningar som basimagen ännu inte har tagit in.
# Bygg med `docker compose build --pull --no-cache`, annars återanvänds det här
# steget från cachen och nya rättningar kommer inte med.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Installera med en aktuell pip och ta sedan bort pip ur imagen. Appen behöver inte
# pip när den körs, och basimagens pip (och pips inbyggda kopia av setuptools-delar)
# ger annars sårbarhetsfynd. Tester körs med `python -m ensurepip` i en tillfällig container.
RUN pip install --no-cache-dir --root-user-action=ignore pip==26.3 \
    && pip install --no-cache-dir --root-user-action=ignore -r requirements.txt \
    && pip uninstall -y --root-user-action=ignore pip

COPY app/ app/
COPY upload_temp/ /tmp/upload_temp/

# Kopiera uppladdade filer till persistent disk vid start
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
