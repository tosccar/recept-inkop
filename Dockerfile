FROM python:3.12-slim

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
