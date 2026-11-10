"""Mandanten-Restore: das Manifest der Installation liegt als Hilfstabelle in der temporären
Datenbank statt im Speicher (BORG-006)."""

from __future__ import annotations

import tracemalloc
import uuid

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.backup.manifest import ManifestEntry
from app.backup.pgtools import PgTarget, PgTools
from app.backup.tenant_recovery import HistoricalTenantExport, ManifestLookup, load_manifest_table, resolve_manifest_entries
from app.core.config import settings


def _entries(count: int, chunk: int = 5000):
    for start in range(0, count, chunk):
        yield [ManifestEntry("main", f"uploads/tenant-{i % 50}/datei-{i:08d}.bin", i, f"{i:064x}", 1, f"hocx-pool-{i // 1000}")
               for i in range(start, min(count, start + chunk))]


def test_manifest_table_lookup_and_memory_independent_of_object_count():
    name = f"hocx_tsrc_test_{uuid.uuid4().hex[:8]}"
    target = PgTarget.from_url(settings.database_url)
    with PgTools(target) as pg:
        pg.create_database(name)
        engine = create_engine(target.with_database(name).sqlalchemy_url(), poolclass=NullPool)
        try:
            tracemalloc.start()
            loaded = load_manifest_table(engine, _entries(200_000))
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert loaded == 200_000
            # Ein Dict über alle Einträge bräuchte hier weit über 50 MiB; gestreamt bleibt nur ein Chunk.
            assert peak < 20 * 1024 * 1024, peak
            with engine.connect() as conn:
                lookup = ManifestLookup(conn)
                exporter = HistoricalTenantExport(lookup)
                assert exporter.object_exists("main", "uploads/tenant-7/datei-00000007.bin")
                assert not exporter.object_exists("main", "uploads/tenant-7/fehlt.bin")
                assert not exporter.object_exists("abgabebox", "uploads/tenant-7/datei-00000007.bin")
                resolved = resolve_manifest_entries(conn, [("main", "uploads/tenant-3/datei-00012353.bin"), ("main", "fehlt")])
                assert resolved == {("main", "uploads/tenant-3/datei-00012353.bin"): (f"{12353:064x}", 12353, "hocx-pool-12")}
        finally:
            engine.dispose()
            pg.drop_database(name)


def test_historical_export_still_accepts_a_plain_set():
    exporter = HistoricalTenantExport({("main", "a")})
    assert exporter.object_exists("main", "a") and not exporter.object_exists("main", "b")
