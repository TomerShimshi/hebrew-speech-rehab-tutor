FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY prompts ./prompts

# Cloud Run injects $PORT (8080 by default).
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
