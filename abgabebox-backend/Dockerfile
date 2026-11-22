FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN useradd --create-home --uid 5001 abgabebox

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/storage && chown -R abgabebox:abgabebox /app
USER abgabebox

EXPOSE 8000

# Kein Access-Log: Pfade enthalten Link-Tokens (Datenschutz-Audit PRIV-025). Keep-Alive länger
# als Traefiks Leerlauf-Frist für Upstream-Verbindungen, wie im Backend.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75", "--no-access-log"]
