FROM python:3.14-slim@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache

# PDFs erzeugt die Dokument-Engine mit Typst (Python-Paket, Schriften im Repo) - keine
# Systempakete dafür nötig.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Backup-Worker (app/workers/backup_worker.py, Recovery-CLI app/backup/cli.py): BorgBackup 1.4
# aus Debian (signiert), SSH-Client für die Hetzner Storage Box und der PostgreSQL-Client in der
# Hauptversion des Servers (pg_dump/pg_restore müssen dazu passen - aus dem offiziellen
# PGDG-Repository, Debian liefert nur die neueste Version). Siehe docs-site/docs/technik/backup/.
ARG PG_MAJOR=18
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-common ca-certificates \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends \
       "borgbackup=1.4.*" \
       openssh-client \
       "postgresql-client-${PG_MAJOR}" \
    && borg --version | grep -q "^borg 1\.4\." \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/usr/lib/postgresql/${PG_MAJOR}/bin:${PATH}"

# Dokumentverarbeitung (document-worker, app/services/documents/): LibreOffice ohne GUI für die
# PDF-Konvertierung, Tesseract + Poppler für den OCR-Fallback, metrisch kompatible Schriften für
# Office-Dokumente. Eigene Schicht, damit die Schichten davor im Cache bleiben. Nur der
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
    && useradd --create-home --uid 5000 --gid 5001 hocx \
    && install -d -m 2770 -o hocx -g hocx-storage /var/lib/hocx/geoip
# /var/lib/hocx/geoip: Mountpunkt des Volumes geoip_data (DB-IP-Länderdatenbank, app/core/geoip.py).
# Docker übernimmt Besitzer und Rechte dieses Verzeichnisses beim ersten Anlegen des Volumes - so
# kann der job-worker (uid 5000) dort schreiben, ohne dass deploy.sh Rechte setzen muss.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R hocx:hocx-storage /app

USER hocx

EXPOSE 8000

# Kein Access-Log: Pfade enthalten Freigabe-, Kalender- und Abgabebox-Tokens (Datenschutz-Audit PRIV-025).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75", "--ws-max-size", "65536", "--no-access-log"]
