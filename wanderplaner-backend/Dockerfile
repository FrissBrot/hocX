FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache

# pdflatex fuer den Kartendruck (app/services/hiking_tour_print_service.py).
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    texlive-pictures \
    fonts-lmodern \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 5002 wanderplaner

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R wanderplaner:wanderplaner /app
USER wanderplaner

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75"]
