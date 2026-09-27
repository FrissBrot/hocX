"""Manueller Transporttest im isolierten Container; keine Produktivdaten/DB.

server: Uvicorn mit echtem Galerie-Parser, Admission und Staging, ohne Auth/DB.
client: sendet ein gültiges ZIP64 mit exakt --gib GiB aus konstant grossem Puffer.
Nicht Teil der normalen Testsuite: schreibt tatsächlich mehrere GiB auf Platte.
"""
import argparse
import http.client
import io
import json
import os
from pathlib import Path
import resource
import struct
import time
import urllib.parse
import zlib


def make_app():
    from fastapi import APIRouter, FastAPI, File, UploadFile
    from app import gallery_upload_route
    from app.core.config import settings
    from app.services.upload_pipeline import GALLERY_REQUEST_MAX_BYTES, GALLERY_ZIP_MAX_BYTES, inspect_gallery_zip, stage_upload_to_disk
    from app.upload_admission import UploadAdmissionMiddleware
    # Nur dieser wegwerfbare Testprozess hat eine bewusst unautorisierte Test-Route.
    gallery_upload_route.authorize_gallery_upload = lambda request: None
    root = Path(settings.upload_root)
    root.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.add_middleware(UploadAdmissionMiddleware, path='/api/files/gallery-uploads', max_bytes=GALLERY_REQUEST_MAX_BYTES, storage_dir=str(root))
    router = APIRouter(route_class=gallery_upload_route.GalleryUploadRoute)
    @router.post('/api/files/gallery-uploads')
    async def receive(files: list[UploadFile] = File(...)):
        source_inode = files[0].file.path.stat().st_ino
        target = await stage_upload_to_disk(files[0], target_dir=root / '_staging' / 'gallery', max_bytes=GALLERY_ZIP_MAX_BYTES, suffix='.zip')
        try:
            return {'zip_bytes': target.stat().st_size, 'expanded_bytes': inspect_gallery_zip(target),
                    'same_inode': source_inode == target.stat().st_ino,
                    'process_peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
        finally:
            target.unlink(missing_ok=True)
    app.include_router(router)
    return app


def send_zip(url: str, gib: int):
    # ZIP64: ein Eintrag, ohne Kompression. Header/Verzeichnis bleiben wenige hundert Bytes.
    size = gib * 1024**3
    name = b'payload.bin'
    overhead = 30 + len(name) + 20 + 46 + len(name) + 20 + 56 + 20 + 22
    payload_size = size - overhead
    block = b'x' * (1024 * 1024)
    crc = 0
    remaining = payload_size
    while remaining:
        chunk = block[:min(remaining, len(block))]
        crc = zlib.crc32(chunk, crc)
        remaining -= len(chunk)
    extra = struct.pack('<HHQQ', 1, 16, payload_size, payload_size)
    local = struct.pack('<IHHHHHIIIHH', 0x04034b50, 45, 0, 0, 0, 33, crc, 0xffffffff, 0xffffffff, len(name), len(extra)) + name + extra
    central_offset = len(local) + payload_size
    central = struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 45, 45, 0, 0, 0, 33, crc, 0xffffffff, 0xffffffff, len(name), len(extra), 0, 0, 0, 0, 0) + name + extra
    zip64_offset = central_offset + len(central)
    ending = (struct.pack('<IQHHIIQQQQ', 0x06064b50, 44, 45, 45, 0, 0, 1, 1, len(central), central_offset)
              + struct.pack('<IIQI', 0x07064b50, 0, zip64_offset, 1)
              + struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, 1, 1, len(central), 0xffffffff, 0))
    assert len(local) + payload_size + len(central) + len(ending) == size
    head = b'--upload-audit\r\nContent-Disposition: form-data; name="files"; filename="photos.zip"\r\nContent-Type: application/zip\r\n\r\n'
    tail = b'\r\n--upload-audit--\r\n'
    parsed = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=10800)
    connection.putrequest('POST', '/api/files/gallery-uploads')
    connection.putheader('Content-Type', 'multipart/form-data; boundary=upload-audit')
    connection.putheader('Content-Length', str(len(head) + size + len(tail)))
    connection.endheaders()
    started = time.monotonic()
    connection.send(head + local)
    remaining = payload_size
    last_report = started
    while remaining:
        chunk = block[:min(remaining, len(block))]
        connection.send(chunk)
        remaining -= len(chunk)
        if time.monotonic() - last_report > 15:
            print(f'Übertragen: {(payload_size-remaining)/1024**3:.1f} GiB', flush=True)
            last_report = time.monotonic()
    connection.send(central + ending + tail)
    response = connection.getresponse()
    result = response.read().decode()
    print(json.dumps({'status': response.status, 'seconds': round(time.monotonic()-started, 2), 'response': result}), flush=True)
    assert response.status == 200, result
    data = json.loads(result)
    assert data['zip_bytes'] == size and data['same_inode']
    connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['server', 'client'])
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--gib', type=int, default=10)
    args = parser.parse_args()
    if args.mode == 'server':
        import uvicorn
        uvicorn.run(make_app(), host='0.0.0.0', port=8000)
    else:
        send_zip(args.url, args.gib)
