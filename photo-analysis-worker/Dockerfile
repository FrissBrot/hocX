FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp/.cache

RUN useradd --create-home --uid 5002 photo-worker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# YuNet face detector (MIT-licensed, see opencv_zoo's models/face_detection_yunet/LICENSE) -
# baked into the image at build time rather than fetched at container start: this container
# runs read_only (see docker-compose.*.yml) and never needs outbound network access at
# runtime, only to read/write Postgres and the shared storage mount. Pinned by SHA-256 so a
# silent upstream file change can't swap in a different model without this build noticing.
ARG YUNET_MODEL_URL=https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2026may.onnx
ARG YUNET_MODEL_SHA256=ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0
# No curl in python:3.13-slim (same reasoning as backend's healthcheck comment) - urllib
# from the stdlib is enough for one pinned, hash-verified download at build time.
RUN mkdir -p /app/models && python3 -c "\
import hashlib, sys, urllib.request; \
url, expected_sha256 = sys.argv[1], sys.argv[2]; \
data = urllib.request.urlopen(url, timeout=30).read(); \
actual_sha256 = hashlib.sha256(data).hexdigest(); \
assert actual_sha256 == expected_sha256, f'YuNet model SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}'; \
open('/app/models/face_detection_yunet.onnx', 'wb').write(data)" \
    "$YUNET_MODEL_URL" "$YUNET_MODEL_SHA256"

COPY app ./app

RUN chown -R photo-worker:photo-worker /app
USER photo-worker

CMD ["python", "-m", "app.worker"]
