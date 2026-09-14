# photo-analysis-worker

Phase 3 of hocX's photo-culling feature ("beste Bilder vorschlagen"): scores the sharpness/
exposure of the most confident detected face in an image, for `stored_file.face_quality_score`.

## Why a separate container

hocX's `backend` container runs on a shared, resource-constrained host (see
`docker-compose.release.yml`'s comment on `backend`'s `mem_limit` history - it was already
hitting the kernel OOM-killer under plain request traffic before this feature existed).
Face detection needs OpenCV + a real (if small) neural network, which is a meaningfully
different resource/dependency profile than the rest of the backend. Running it inline
would risk reproducing that OOM history. Instead this is:

- its own Docker image, with its own `mem_limit`/`cpus` in `docker-compose.*.yml` -
  worst case, only this container is affected;
- its own restricted Postgres role (`hocx_photo_worker`, created by migration
  `0067_photo_analysis_job.py`), scoped to exactly the columns it needs (read a few
  `stored_file` columns, write `face_quality_score`, transition `photo_analysis_job`
  status) - not the full `hocx_app` role's access to the entire multi-tenant schema. If a
  malicious-image parsing bug in OpenCV/onnxruntime ever compromised this process, this is
  the blast radius;
- a plain polling loop (`app/worker.py`, Postgres `FOR UPDATE SKIP LOCKED`), not part of
  `backend`'s asyncio event loop the way the existing rescan sweeps in `backend/app/main.py`
  are - there's no fixed "one loop per app instance" shape to hang an advisory lock off of
  here, and `FOR UPDATE SKIP LOCKED` is the more standard Postgres job-queue pattern anyway.

## Model

`face_detection_yunet_2026may.onnx` from
[opencv/opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
(MIT-licensed, see that directory's own `LICENSE` file - separate from the repo's overall
Apache-2.0 license). Detection only, no recognition/identification: this scores whether a
detected face *region* is sharp/well-exposed, the same way `backend/app/services/
photo_quality.py`'s Phase 1 scores the whole frame - it never computes or stores a face
embedding, and never tries to tell two faces apart or match a face to a person. Baked into
the image at build time (see the `Dockerfile`), pinned by SHA-256, since the container
runs `read_only` and has no reason to reach the network at runtime.

## Test coverage

`tests/test_face_quality.py` covers both the "doesn't crash / correctly finds nothing" path
(blank/random-noise/undecodable input) and positive detection against a real photograph of
a face (`tests/fixtures/nasa_official_portrait.jpg` - public domain, see
`fixtures/ATTRIBUTION.md` for provenance). That real-photo test is what caught a real bug:
YuNet reliably found **nothing at all** on the original ~5200x6500px source image - only
after downscaling did it detect the face (confirmed working up to ~2000px on the longer
side, confirmed broken again at 3000px). `_DETECTION_MAX_DIMENSION` in `face_quality.py`
fixes this for every image the worker processes, not just the fixture; the two real-photo
tests double as the regression test for that fix.

## Local development

```bash
docker compose build photo-analysis-worker
docker compose up photo-analysis-worker
```

Tests (mirrors `backend/`'s `Dockerfile.test` convention):

```bash
./scripts/test.sh photo-analysis-worker
```

## Deploying this to production

The `docker-compose.release.yml` service definition and `.env.example`/
`.env.prod.example`/`.env.test.example` entries (`PHOTO_WORKER_DB_PASSWORD`,
`PHOTO_WORKER_DATABASE_URL`) are in place, but as of this writing `scripts/deploy.sh`,
`scripts/lib/env.sh`, and the GitHub Actions release-image build workflow have **not**
been updated to generate/carry these secrets or build/push this image - they were left
out of this pass rather than guessed at without being able to test a real deploy cycle.
Wire those up (mirroring the existing `ABGABEBOX_DB_PASSWORD`/`ABGABEBOX_DATABASE_URL`
handling in each of those files) before deploying this to a real environment.
