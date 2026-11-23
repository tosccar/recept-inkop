FROM python:3.12-slim

# Hämta Debians säkerhetsrättningar som basimagen ännu inte har tagit in.
# Bygg med `docker compose build --pull --no-cache`, annars återanvänds det här
# steget från cachen och nya rättningar kommer inte med.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY upload_temp/ /tmp/upload_temp/

# Kopiera uppladdade filer till persistent disk vid start
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
