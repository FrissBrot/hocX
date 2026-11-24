"""Foto-Standorte: Ortssuche, Umkreisfilter, Ort von Hand, Nachtragen (Migration 0260_photo_places).

- **Ortsname am Foto** (``photo_location``): für GPS-Fotos pflegt die Datenbank ihn selbst (Trigger
  auf ``stored_file`` → ``hocx_photo_location_refresh`` → ``hocx_geo_reverse``), also für jeden
  Upload-Weg (Galerie, ZIP, Cloud-Import, Abgabebox, Protokollbilder, Mandanten-Import), sobald der
  Metadaten-Scan GPS gesetzt hat. Sichtbar für alle, die das Foto im eigenen Mandanten sehen
  (``attach_places``); Partner geteilter Alben und öffentliche Links bekommen ihn nie.
- **Ortssuche** (``search_places``): unscharf über alle Schreibweisen (``hocx_geo_fold``: klein,
  ohne Akzente, ä=ae=a), gerankt nach Treffergüte und Bedeutung, Dubletten zusammengefasst.
- **Umkreis** (``near_subquery``): Bounding-Box im Index ``idx_photo_location_coords``
  (tenant_id, latitude, longitude), Haversine nur für die Kandidaten. Standardradius je Ortsart.
- **Ort von Hand** (``assign``/``clear``/``undo``): nur Fotos ohne GPS; Rückgängig wie die
  Datumskorrekturen (``place_change_batch``).
- **Nachtragen** (``resolve_backlog``, Job ``photo_places_resolve``): Fotos, deren Beschriftung
  älter als die Ortsdaten ist (``geo_generation``), je Mandant in Stücken; wiederaufnehmbar.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import BigInteger, Float, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.sql_like import contains_pattern, prefix_pattern
from app.models.place_entities import PhotoLocation, PlaceChangeBatch, PlaceChangeItem
from app.schemas.photo_places import PhotoPlaceRead
from app.services import geo_places

KEY_PATTERN = re.compile(r"^(gn:[0-9]{1,12}|sn:[0-9a-f-]{36})$")
# Umkreis je Ortsart (km): Gipfel/Hütte/Punkt ~2, Dorf ~5, Stadt/Region ~20
RADIUS_KM = {
    "peak": 2.0, "hut": 2.0, "pass": 2.0, "poi": 2.0, "station": 2.0, "field": 2.0, "hamlet": 2.0,
    "lake": 3.0, "glacier": 3.0, "district": 3.0, "village": 5.0, "town": 10.0, "city": 20.0, "region": 20.0,
}
MAX_RADIUS_KM = 200.0
# Kleinster Umkreis für Konten ohne Recht auf Koordinaten (files.manage/meetings.edit)
MIN_COARSE_RADIUS_KM = 2.0
MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 80
SEARCH_TIMEOUT_MS = 2000
# Ortschaft ohne präzisen Ort: «Nähe X», sobald das Foto weiter weg ist als das Ortsgebiet
_LOCALITY_EXTENT_M = {"village": 2000, "town": 4000, "city": 8000}
MAX_BULK = 500
BATCH_REUSE_WINDOW = timedelta(hours=2)
RESOLVE_CHUNK = 500
RESOLVE_PER_TICK = 5000


def valid_key(key: str | None) -> str | None:
    key = (key or "").strip().lower()
    return key if KEY_PATTERN.match(key) else None


def current_generation(db: Session) -> int:
    return int(db.scalar(text("SELECT coalesce(max(generation), 0) FROM geo_dataset")) or 0)


# --- Ortssuche ----------------------------------------------------------------------------------


def _locality_label(row) -> dict:
    return {"locality_name": row.locality_name, "admin1_code": row.admin1_code, "country_code": row.country_code}


def search_places(db: Session, query: str, *, limit: int = 8) -> list[dict]:
    """Orte zu einer Eingabe (mind. 3 Zeichen) - ohne Koordinaten in der Antwort."""
    raw = (query or "").strip()[:MAX_QUERY_LENGTH]
    if len(raw) < MIN_QUERY_LENGTH:
        return []
    folded = db.scalar(text("SELECT public.hocx_geo_fold(:q)"), {"q": raw}) or ""
    folded = re.sub(r"\s+", " ", folded).strip()
    if len(folded) < MIN_QUERY_LENGTH:
        return []
    params = {
        "f": folded,
        "prefix": prefix_pattern(folded),
        "contains": contains_pattern(folded),
        "fuzzy": len(folded) >= 4,
    }
    sql = text(
        r"""
        SELECT g.place_key, g.name, g.name_fold, g.kind, g.admin1_code, g.admin1_name, g.country_code,
               g.latitude, g.longitude,
               CASE WHEN g.name_fold = :f THEN 4
                    WHEN g.name_fold LIKE :prefix ESCAPE '\' THEN 3
                    WHEN g.search_names LIKE :contains ESCAPE '\' THEN 2 ELSE 0 END
               + public.word_similarity(:f, g.search_names) AS match,
               g.importance
          FROM geo_place g
         WHERE g.search_names LIKE :contains ESCAPE '\'
            OR (:fuzzy AND :f OPERATOR(public.<%) g.search_names)
         ORDER BY match DESC, g.importance DESC, g.place_key
         LIMIT 60
        """
    )
    db.execute(text("SAVEPOINT geo_place_search"))
    try:
        db.execute(text(f"SET LOCAL statement_timeout = {int(SEARCH_TIMEOUT_MS)}"))  # sql-ok: feste Zahl
        rows = db.execute(sql, params).all()
        db.execute(text("SET LOCAL statement_timeout = DEFAULT"))
        db.execute(text("RELEASE SAVEPOINT geo_place_search"))
    except OperationalError:
        db.execute(text("ROLLBACK TO SAVEPOINT geo_place_search"))
        db.execute(text("RELEASE SAVEPOINT geo_place_search"))
        return []
    picked: list = []
    for row in rows:
        group = "locality" if row.kind in geo_places.LOCALITY_KINDS else row.kind
        duplicate = any(
            other.name_fold == row.name_fold
            and ("locality" if other.kind in geo_places.LOCALITY_KINDS else other.kind) == group
            and _distance_m(other.latitude, other.longitude, row.latitude, row.longitude) < 3000
            for other in picked
        )
        if not duplicate:
            picked.append(row)
        if len(picked) >= limit:
            break
    result = []
    for row in picked:
        entry = {
            "key": row.place_key, "name": row.name, "kind": row.kind, "admin1_code": row.admin1_code,
            "admin1_name": row.admin1_name, "country_code": row.country_code, "locality_name": None,
            "radius_km": RADIUS_KM.get(row.kind, 5.0),
        }
        if row.kind not in geo_places.LOCALITY_KINDS:
            context = db.execute(
                text("SELECT (r).locality_name, (r).admin1_code, (r).country_code FROM (SELECT public.hocx_geo_reverse(:lat, :lon) AS r) x"),
                {"lat": row.latitude, "lon": row.longitude},
            ).one()
            entry["locality_name"] = context[0]
            entry["admin1_code"] = context[1] or entry["admin1_code"]
            entry["country_code"] = context[2] or entry["country_code"]
        result.append(entry)
    return result


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(value)))


# --- Umkreis ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NearFilter:
    key: str
    name: str
    kind: str
    latitude: float
    longitude: float
    radius_km: float
    tenant_id: int


def resolve_near(
    db: Session, key: str | None, radius_km: float | None, tenant_id: int, *, precise: bool = True
) -> NearFilter | None:
    """Ort + Umkreis für die Fotoliste; unbekannter Ort → 404 (ohne Hinweis auf Fotos).
    precise=False (Konten ohne Recht auf Koordinaten): nie enger als der Standardradius der
    Ortsart, sonst liesse sich der Aufnahmeort mit vielen kleinen Kreisen eingrenzen."""
    if key is None:
        return None
    normalized = valid_key(key)
    row = db.execute(
        text("SELECT place_key, name, kind, latitude, longitude FROM geo_place WHERE place_key = :key"), {"key": normalized}
    ).first() if normalized else None
    if row is None:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    default = RADIUS_KM.get(row.kind, 5.0)
    radius = default if radius_km is None else float(radius_km)
    radius = min(max(radius, 0.5 if precise else max(default, MIN_COARSE_RADIUS_KM)), MAX_RADIUS_KM)
    return NearFilter(row.place_key, row.name, row.kind, row.latitude, row.longitude, radius, tenant_id)


def near_subquery(near: NearFilter):
    """(stored_file_id, distance_m) aller Fotos des Mandanten im Umkreis."""
    dlat = near.radius_km * 1000 / 111_320.0
    dlon = dlat / max(math.cos(math.radians(near.latitude)), 0.05)
    lon0, lon1 = near.longitude - dlon, near.longitude + dlon
    # Datumsgrenze: zweiter Längenbereich auf der anderen Seite (sonst leer)
    wrap0, wrap1 = (lon0 + 360, 180.0) if lon0 < -180 else ((-180.0, lon1 - 360) if lon1 > 180 else (1.0, 0.0))
    params = {
        "n_lat": near.latitude, "n_lon": near.longitude, "n_tenant": near.tenant_id, "n_r": near.radius_km * 1000,
        "n_lat0": near.latitude - dlat, "n_lat1": near.latitude + dlat, "n_lon0": lon0, "n_lon1": lon1,
        "n_w0": wrap0, "n_w1": wrap1,
    }
    sql = text(
        """
        SELECT pl.stored_file_id,
               public.hocx_geo_distance_m(:n_lat, :n_lon, pl.latitude, pl.longitude) AS distance_m
          FROM photo_location pl
         WHERE pl.tenant_id = :n_tenant
           AND pl.latitude BETWEEN :n_lat0 AND :n_lat1
           AND (pl.longitude BETWEEN :n_lon0 AND :n_lon1 OR pl.longitude BETWEEN :n_w0 AND :n_w1)
           AND public.hocx_geo_distance_m(:n_lat, :n_lon, pl.latitude, pl.longitude) <= :n_r
        """
    )
    return sql.bindparams(**params).columns(stored_file_id=BigInteger, distance_m=Float).subquery("near_places")


# --- Anzeige ------------------------------------------------------------------------------------


def place_payload(row, *, distance_m: float | None = None) -> PhotoPlaceRead | None:
    if row is None or (row.place_name is None and row.locality_name is None):
        return None
    near = row.place_name is not None or (
        row.locality_distance_m is not None and row.locality_distance_m > _LOCALITY_EXTENT_M.get(row.locality_kind or "", 2000)
    )
    return PhotoPlaceRead(**{
        "key": row.place_key or row.locality_key,
        "name": row.place_name,
        "kind": row.place_kind,
        "locality_name": row.locality_name,
        "locality_kind": row.locality_kind,
        "admin1_code": row.admin1_code,
        "country_code": row.country_code,
        "near": near,
        "source": row.source,
        "distance_m": round(distance_m) if distance_m is not None else None,
    })


def places_for_files(db: Session, tenant_id: int, stored_file_ids: list[int]) -> dict[int, object]:
    if not stored_file_ids:
        return {}
    rows = db.execute(
        select(PhotoLocation).where(PhotoLocation.tenant_id == tenant_id, PhotoLocation.stored_file_id.in_(stored_file_ids))
    ).scalars()
    return {row.stored_file_id: row for row in rows}


def attach_places(db: Session, tenant_id: int, items: list, *, near: NearFilter | None = None, with_distance: bool = False) -> None:
    """item.place für Fotos des eigenen Mandanten (Partnerfotos geteilter Alben bleiben ohne Ort)."""
    if not items:
        return
    from app.models.entities import StoredFile

    ids = {
        row.public_id: row.id
        for row in db.execute(
            select(StoredFile.public_id, StoredFile.id).where(
                StoredFile.tenant_id == tenant_id, StoredFile.public_id.in_([item.id for item in items])
            )
        )
    }
    locations = places_for_files(db, tenant_id, list(ids.values()))
    for item in items:
        location = locations.get(ids.get(item.id, -1))
        if location is None:
            continue
        distance = None
        if near is not None and with_distance:
            distance = _distance_m(near.latitude, near.longitude, location.latitude, location.longitude)
        item.place = place_payload(location, distance_m=distance)


# --- Ort von Hand -------------------------------------------------------------------------------


@dataclass
class AssignOutcome:
    updated_ids: list[uuid.UUID] = field(default_factory=list)
    unchanged_ids: list[uuid.UUID] = field(default_factory=list)
    skipped_gps_ids: list[uuid.UUID] = field(default_factory=list)
    not_found_ids: list[uuid.UUID] = field(default_factory=list)
    changes: list[tuple[int, str | None, str | None]] = field(default_factory=list)


def _current_rows(db: Session, tenant_id: int, public_ids: list[uuid.UUID]):
    return db.execute(
        text(
            """
            SELECT sf.id, sf.public_id, sf.gps_latitude IS NOT NULL AS has_gps, pl.source,
                   coalesce(pl.place_key, pl.locality_key) AS current_key
              FROM stored_file sf
              LEFT JOIN photo_location pl ON pl.stored_file_id = sf.id
             WHERE sf.tenant_id = :tenant AND sf.public_id = ANY(:ids) AND sf.mime_type LIKE 'image/%'
            """
        ),
        {"tenant": tenant_id, "ids": public_ids},
    ).all()


def _write_manual(db: Session, stored_file_ids: list[int], key: str, user_id: int | None) -> None:
    if not stored_file_ids:
        return
    db.execute(
        text(
            """
            INSERT INTO photo_location AS pl (
                stored_file_id, tenant_id, source, latitude, longitude, place_key, place_name, place_kind,
                place_distance_m, locality_key, locality_name, locality_kind, locality_distance_m,
                admin1_code, admin1_name, country_code, search_text, geo_generation, set_by, updated_at
            )
            SELECT sf.id, sf.tenant_id, 'manual', d.latitude, d.longitude, (d.label).place_key, (d.label).place_name,
                   (d.label).place_kind, (d.label).place_distance_m, (d.label).locality_key, (d.label).locality_name,
                   (d.label).locality_kind, (d.label).locality_distance_m, (d.label).admin1_code, (d.label).admin1_name,
                   (d.label).country_code, coalesce((d.label).search_text, ''),
                   (SELECT coalesce(max(generation), 0) FROM geo_dataset), :user_id, now()
              FROM stored_file sf
             CROSS JOIN public.hocx_geo_describe(:key) d
             WHERE sf.id = ANY(:ids) AND sf.gps_latitude IS NULL
            ON CONFLICT (stored_file_id) DO UPDATE
               SET source = 'manual', latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
                   place_key = EXCLUDED.place_key, place_name = EXCLUDED.place_name, place_kind = EXCLUDED.place_kind,
                   place_distance_m = EXCLUDED.place_distance_m, locality_key = EXCLUDED.locality_key,
                   locality_name = EXCLUDED.locality_name, locality_kind = EXCLUDED.locality_kind,
                   locality_distance_m = EXCLUDED.locality_distance_m, admin1_code = EXCLUDED.admin1_code,
                   admin1_name = EXCLUDED.admin1_name, country_code = EXCLUDED.country_code,
                   search_text = EXCLUDED.search_text, geo_generation = EXCLUDED.geo_generation,
                   set_by = EXCLUDED.set_by, updated_at = now()
             WHERE pl.source = 'manual'
            """
        ),
        {"ids": stored_file_ids, "key": key, "user_id": user_id},
    )


def _delete_manual(db: Session, stored_file_ids: list[int]) -> None:
    if stored_file_ids:
        db.execute(
            text("DELETE FROM photo_location WHERE stored_file_id = ANY(:ids) AND source = 'manual'"), {"ids": stored_file_ids}
        )


def place_exists(db: Session, key: str | None) -> str:
    normalized = valid_key(key)
    if normalized is None or db.scalar(text("SELECT 1 FROM geo_place WHERE place_key = :key"), {"key": normalized}) is None:
        raise HTTPException(status_code=404, detail="Ort nicht gefunden")
    return normalized


def assign(db: Session, tenant_id: int, public_ids: list[uuid.UUID], key: str | None, *, user_id: int | None) -> AssignOutcome:
    """Ort setzen (key) bzw. entfernen (None) - nur Fotos ohne GPS. Committet nicht."""
    outcome = AssignOutcome()
    rows = {row.public_id: row for row in _current_rows(db, tenant_id, public_ids)}
    targets: list[int] = []
    for public_id in public_ids:
        row = rows.get(public_id)
        if row is None:
            outcome.not_found_ids.append(public_id)
            continue
        if row.has_gps:
            outcome.skipped_gps_ids.append(public_id)
            continue
        current = row.current_key if row.source == "manual" else None
        if current == key:
            outcome.unchanged_ids.append(public_id)
            continue
        targets.append(row.id)
        outcome.updated_ids.append(public_id)
        outcome.changes.append((row.id, current, key))
    if key is None:
        _delete_manual(db, targets)
    else:
        _write_manual(db, targets, key, user_id)
    return outcome


def open_batch(
    db: Session, user, *, batch_id: uuid.UUID | None, mode: str, params: dict, upload_job_id: uuid.UUID | None
) -> PlaceChangeBatch:
    """Neue Ortsänderung oder - bei gestückelten Aufrufen - die eigene des ersten Stücks (sonst 404)."""
    if batch_id is not None:
        batch = db.scalar(
            select(PlaceChangeBatch)
            .where(
                PlaceChangeBatch.id == batch_id,
                PlaceChangeBatch.tenant_id == user.current_tenant_id,
                PlaceChangeBatch.created_by == user.user_id,
                PlaceChangeBatch.undone_at.is_(None),
                PlaceChangeBatch.mode == mode,
                PlaceChangeBatch.created_at >= datetime.now(UTC) - BATCH_REUSE_WINDOW,
            )
            .with_for_update()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="Änderung nicht gefunden")
        return batch
    batch = PlaceChangeBatch(
        tenant_id=user.current_tenant_id, created_by=user.user_id, mode=mode, params=params, upload_job_id=upload_job_id
    )
    db.add(batch)
    db.flush()
    return batch


def record(db: Session, batch: PlaceChangeBatch, changes: list[tuple[int, str | None, str | None]]) -> None:
    if not changes:
        return
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    inserted = db.execute(
        pg_insert(PlaceChangeItem)
        .values([
            {"batch_id": batch.id, "tenant_id": batch.tenant_id, "stored_file_id": file_id, "prev_place_key": prev, "new_place_key": new}
            for file_id, prev, new in changes
        ])
        .on_conflict_do_nothing()
        .returning(PlaceChangeItem.id)
    ).scalars().all()
    db.execute(
        update(PlaceChangeBatch)
        .where(PlaceChangeBatch.id == batch.id, PlaceChangeBatch.tenant_id == batch.tenant_id)
        .values(updated_count=PlaceChangeBatch.updated_count + len(inserted))
        .execution_options(synchronize_session=False)
    )


@dataclass
class UndoOutcome:
    restored_ids: list[uuid.UUID] = field(default_factory=list)
    conflict_ids: list[uuid.UUID] = field(default_factory=list)
    not_found_ids: list[uuid.UUID] = field(default_factory=list)
    skipped: int = 0


def undo(db: Session, batch: PlaceChangeBatch, *, user_id: int | None, writable) -> UndoOutcome:
    """Vorherigen Ort je Foto wiederherstellen, wo seither nichts geändert wurde. Committet nicht."""
    from app.models.entities import StoredFile

    outcome = UndoOutcome()
    items = list(
        db.scalars(
            select(PlaceChangeItem)
            .where(PlaceChangeItem.batch_id == batch.id, PlaceChangeItem.tenant_id == batch.tenant_id)
            .order_by(PlaceChangeItem.id)
        )
    )
    for start in range(0, len(items), MAX_BULK):
        chunk = items[start : start + MAX_BULK]
        files = {
            stored.id: stored
            for stored in db.scalars(
                select(StoredFile)
                .where(StoredFile.tenant_id == batch.tenant_id, StoredFile.id.in_([item.stored_file_id for item in chunk]))
                .with_for_update()
            )
        }
        current = {
            row.id: row
            for row in _current_rows(db, batch.tenant_id, [stored.public_id for stored in files.values()])
        }
        restore: dict[str | None, list[int]] = {}
        for item in chunk:
            stored = files.get(item.stored_file_id)
            if stored is None or not writable(stored):
                # nicht lesbare Fotos nur zählen, ihre IDs nicht nennen (Security-Review)
                outcome.skipped += 1
                continue
            row = current.get(stored.id)
            now_key = row.current_key if row is not None and row.source == "manual" else None
            if row is None or row.has_gps or now_key != item.new_place_key:
                outcome.conflict_ids.append(stored.public_id)
                continue
            if item.prev_place_key is not None and db.scalar(
                text("SELECT 1 FROM geo_place WHERE place_key = :key"), {"key": item.prev_place_key}
            ) is None:
                outcome.conflict_ids.append(stored.public_id)
                continue
            restore.setdefault(item.prev_place_key, []).append(stored.id)
            outcome.restored_ids.append(stored.public_id)
        for key, ids in restore.items():
            if key is None:
                _delete_manual(db, ids)
            else:
                _write_manual(db, ids, key, user_id)
    batch.undone_at = datetime.now(UTC)
    batch.undone_by = user_id
    return outcome


def list_for_job(db: Session, tenant_id: int, upload_job_id: uuid.UUID) -> list[PlaceChangeBatch]:
    return list(
        db.scalars(
            select(PlaceChangeBatch)
            .where(PlaceChangeBatch.tenant_id == tenant_id, PlaceChangeBatch.upload_job_id == upload_job_id)
            .order_by(PlaceChangeBatch.created_at.desc())
            .limit(100)
        )
    )


def remaining_items(db: Session, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not batch_ids:
        return {}
    return dict(
        db.execute(
            select(PlaceChangeItem.batch_id, func.count()).where(PlaceChangeItem.batch_id.in_(batch_ids)).group_by(PlaceChangeItem.batch_id)
        ).all()
    )


# --- Nachtragen (Job photo_places_resolve) ------------------------------------------------------


def resolve_backlog(db: Session, *, per_tick: int = RESOLVE_PER_TICK, chunk: int = RESOLVE_CHUNK) -> dict:
    """Beschriftet Fotos, deren Ort älter ist als die Ortsdaten (bzw. GPS-Fotos ohne Zeile), je
    Mandant in Stücken mit eigenem Commit. Ohne Ortsdaten nichts zu tun. Wiederaufnehmbar: der
    Fortschritt steht in photo_location.geo_generation."""
    generation = current_generation(db)
    if generation == 0:
        db.commit()
        return {"skipped": "no_geo_data"}
    done = 0
    tenants = 0
    tenant_ids = list(
        db.scalars(
            text(
                """
                SELECT tenant_id FROM photo_location WHERE geo_generation < :g
                UNION
                SELECT sf.tenant_id FROM stored_file sf
                 WHERE sf.gps_latitude IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM photo_location pl WHERE pl.stored_file_id = sf.id)
                """
            ),
            {"g": generation},
        )
    )
    db.commit()
    for tenant_id in sorted(tenant_ids):
        tenants += 1
        while done < per_tick:
            ids = list(
                db.scalars(
                    text(
                        """
                        (SELECT stored_file_id FROM photo_location
                          WHERE tenant_id = :t AND geo_generation < :g ORDER BY stored_file_id LIMIT :n)
                        UNION
                        (SELECT sf.id FROM stored_file sf
                          WHERE sf.tenant_id = :t AND sf.gps_latitude IS NOT NULL
                            AND NOT EXISTS (SELECT 1 FROM photo_location pl WHERE pl.stored_file_id = sf.id)
                          ORDER BY sf.id LIMIT :n)
                        """
                    ),
                    {"t": tenant_id, "g": generation, "n": min(chunk, per_tick - done)},
                )
            )
            if not ids:
                break
            db.execute(text("SELECT public.hocx_photo_location_refresh(CAST(:ids AS bigint[]))"), {"ids": ids})
            db.commit()
            done += len(ids)
        if done >= per_tick:
            break
    remaining = int(db.scalar(text("SELECT count(*) FROM photo_location WHERE geo_generation < :g"), {"g": generation}) or 0)
    db.commit()
    return {"resolved": done, "tenants": tenants, "remaining": remaining, "generation": generation}
