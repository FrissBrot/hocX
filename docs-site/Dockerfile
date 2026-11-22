FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
WORKDIR /docs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdocs build --strict

FROM nginxinc/nginx-unprivileged:alpine@sha256:b5047b9b76845eac124358373c6852377c52e4b05834a47647e955dd91cb8f1e
USER root
# Sicherheitsupdates von Alpine mitnehmen, auch wenn das Basisimage (Digest oben) sie noch nicht
# enthält - z. B. brotli-libs CVE-2026-111497, an der der Trivy-Scan in release.yml scheiterte.
RUN apk upgrade --no-cache && sed -i 's/8080/80/g' /etc/nginx/conf.d/default.conf
COPY nginx-gzip.conf /etc/nginx/conf.d/gzip.conf
COPY --from=build /docs/site /usr/share/nginx/html
USER 101
