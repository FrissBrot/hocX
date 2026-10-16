FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

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

RUN groupadd --gid 5001 hocx-storage \
    && useradd --create-home --uid 5000 --gid 5001 hocx

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R hocx:hocx-storage /app

USER hocx

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "75"]
