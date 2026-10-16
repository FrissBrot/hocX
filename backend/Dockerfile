FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    texlive-xetex \
    texlive-pictures \
    fonts-lmodern \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Dokumentverarbeitung (document-worker, app/services/documents/): LibreOffice ohne GUI für die
# PDF-Konvertierung, Tesseract + Poppler für den OCR-Fallback, metrisch kompatible Schriften für
# Office-Dokumente. Eigene Schicht, damit die TeX-Schicht davor im Cache bleibt. Nur der
# document-worker ruft diese Programme auf - nie der Webprozess.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer-nogui \
    libreoffice-calc-nogui \
    libreoffice-impress-nogui \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-fra \
    tesseract-ocr-ita \
    poppler-utils \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 5001 hocx-storage \
    && useradd --create-home --uid 5000 --gid 5001 hocx

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R hocx:hocx-storage /app

USER hocx

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75"]
