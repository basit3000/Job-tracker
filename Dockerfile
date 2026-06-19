FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=run.py

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads

EXPOSE 5000

# Run inline (no external .sh) to stay safe from Windows CRLF / exec-bit issues.
# Applies migrations if present, otherwise creates tables, then serves with gunicorn.
CMD ["sh", "-c", "if [ -d migrations ]; then flask db upgrade; else flask init-db; fi && exec gunicorn --bind 0.0.0.0:5000 --workers 3 run:app"]
