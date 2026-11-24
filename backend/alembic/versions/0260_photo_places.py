"""Foto-Standorte: Ortsnamen aus GPS, Ortssuche mit Umkreis, Ort von Hand (hocX 1.6).

Globale Referenzdaten (kein Mandantendatum, darum ohne ``tenant_id``/RLS):

- ``geo_place``: Orte aus GeoNames (CC BY 4.0, weltweit ``cities500`` + Länderdateien der
  Nachbarländer) und swisstopo swissNAMES3D (Gipfel, Hütten, Pässe, Seen, Flurnamen, Weiler). Je
  Ort Art (``kind``), WGS84-Koordinate, Kanton/Region, Bedeutung (Suche) und gefaltete Namen
  (``search_names``, alle Schreibweisen, GIN-Trigramm). Für die Umkreissuche zwei Teil-GiST-
  Indizes über ``point(longitude, latitude)`` (Kern-Postgres, kein PostGIS: das offizielle
  ``postgres:18``-Image bringt es nicht mit; ``cube``/``earthdistance`` wären vorhanden, die
  Kern-Typen ``point``/``box`` reichen aber für Bounding-Box + Haversine).
- ``geo_place_import`` (UNLOGGED): Zwischenablage des Imports. Nur sie darf die Import-Rolle
  ``hocx_geo`` beschreiben; ``hocx_geo_import_apply`` (SECURITY DEFINER, prüft Quelle, Schlüsselpräfix,
  Mindestmenge und Schwund) übernimmt sie in ``geo_place``. ``geo_place`` und ``geo_dataset``
  sind für ``hocx_app`` nur lesbar.
- ``geo_dataset``: Stand je Quelle (Version, SHA-256, Grösse, Zeilen, Generation).
- Eigene DB-Rolle ``hocx_geo`` (Passwort ``GEO_DB_PASSWORD``, User-Entscheid nach dem
  Security-Review): nur sie darf in ``geo_place_import`` schreiben und ``hocx_geo_import_apply``
  ausführen; Lesen auf ``geo_place``/``geo_dataset``, kein Zugriff auf Mandantentabellen. Der
  job-worker nutzt sie nur für den Import (``GEO_DATABASE_URL``). ``hocx_app`` liest die
  Ortsdaten nur und hat keinen Zugriff auf die Zwischenablage.

Mandantendaten:

- ``photo_location``: Ort je Foto (``tenant_id`` NOT NULL per Trigger aus ``stored_file``, RLS
  ``tenant_isolation``). ``source`` = ``gps`` (aus ``stored_file.gps_*``, vom Trigger gepflegt)
  oder ``manual`` (von Hand gesetzt; überschreibt nie echtes GPS, GPS ersetzt einen manuellen
  Ort). Wirksame Koordinate (GPS bzw. Ort), präziser Ort (Hütte, Gipfel …) und Ortschaft mit
  Kanton/Land denormalisiert, ``search_text`` für das Suchdokument, ``geo_generation`` für das
  Nachtragen nach einem Datenupdate. Index ``(tenant_id, latitude, longitude)`` für die
  Umkreissuche (Bounding-Box im Index, Haversine nur für die Kandidaten).
- ``place_change_batch``/``place_change_item``: Rückgängig für «Ort setzen/entfernen» (wie
  0251 für Datumskorrekturen), ``tenant_id`` NOT NULL + RLS, Items über (tenant_id, batch_id).

Funktionen: ``hocx_geo_fold`` (Faltung wie die Fotosuche plus ä=ae), ``hocx_geo_distance_m``
(Haversine), ``hocx_geo_reverse`` (Rangfolge präziser Ort → Ortschaft), ``hocx_geo_describe``
(Beschreibung eines gewählten Orts), ``hocx_photo_location_refresh`` (SECURITY DEFINER, vom
Statement-Trigger auf ``stored_file`` und vom Nachtrage-Job). ``hocx_photo_search_refresh``
(0204/0217) nimmt die Ortsnamen in die starken Wörter auf; ein Trigger auf ``photo_location``
baut das Suchdokument neu.

Revision ID: 0260_photo_places
Revises: 0252_upload_history_abgabebox
Create Date: 2026-11-23
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0260_photo_places"
down_revision = "0252_upload_history_abgabebox"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"

KINDS = (
    "city", "town", "village", "hamlet", "district", "peak", "pass", "hut", "lake", "glacier",
    "poi", "station", "field", "region",
)
# Gleiche Listen wie app/services/photo_places.py (Migrationen importieren keinen App-Code).
PRECISE_KINDS_SQL = "('hamlet', 'district', 'peak', 'pass', 'hut', 'lake', 'glacier', 'poi', 'station', 'field')"
LOCALITY_KINDS_SQL = "('city', 'town', 'village')"


GEO_ROLE = "hocx_geo"


def _read_password(env_var: str) -> str | None:
    # Wie 0067 (eigenständige Kopie: Revisionen importieren einander nicht für Rollen-Helfer)
    password = os.environ.get(env_var)
    if not password and (password_file := os.environ.get(f"{env_var}_FILE")):
        with open(password_file, encoding="utf-8") as secret_file:
            password = secret_file.read().rstrip("\r\n")
    return password or None


def _ensure_geo_role() -> None:
    """Rolle anlegen (Passwort Pflicht) bzw. bei vorhandener Rolle das Passwort nur setzen, wenn
    eines übergeben wird. So laufen auch Migrationen des backup-workers auf wiederhergestellten
    Datenbanken (Restore, Restore-Test) ohne GEO_DB_PASSWORD, und eine temporäre Restore-DB setzt
    das clusterweite Passwort nicht neu (Security-Review)."""
    exists = op.get_bind().execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": GEO_ROLE}).scalar()
    password = _read_password("GEO_DB_PASSWORD")
    if not exists and not password:
        raise RuntimeError(
            "GEO_DB_PASSWORD muss vor dieser Migration gesetzt sein "
            f"(Passwort fuer die eingeschraenkte Postgres-Rolle '{GEO_ROLE}')."
        )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{GEO_ROLE}') THEN
                CREATE ROLE {GEO_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 4;
            END IF;
        END
        $$;
        """  # sql-ok: fester Rollenname
    )
    # Rolleneinstellungen wie die übrigen Laufzeitrollen (0135, restore_core.APP_ROLE_SETTINGS)
    op.execute(f"ALTER ROLE {GEO_ROLE} SET idle_in_transaction_session_timeout = '15min'")  # sql-ok: fester Rollenname
    if password:
        # Passwort als gebundener Wert geht in ALTER ROLE nicht; Literal mit verdoppelten Hochkommas
        escaped = password.replace("'", "''")
        op.execute(f"ALTER ROLE {GEO_ROLE} PASSWORD '{escaped}'")  # sql-ok: fester Rollenname, Passwort maskiert

def _load(name: str):
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"hocx_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _search_functions_0217() -> str:
    """Stand der Suchfunktionen nach 0217 (0204-Text mit Keyword-Ersetzungen)."""
    return _load("0217_file_keywords_synonyms.py")._functions_with_keywords(_load("0204_photo_search.py").FUNCTIONS_SQL)


_SEARCH_REPLACEMENTS = (
    (
        "array_to_string(sf.keywords, ' ') AS kw_text,",
        "array_to_string(sf.keywords, ' ') AS kw_text,\n"
        "                   (SELECT pl.search_text FROM photo_location pl WHERE pl.stored_file_id = sf.id) AS place_text,",
    ),
    (
        "public.hocx_search_terms(concat_ws(' ', tag_text, kw_text, ctx_text)) AS strong_terms,",
        "public.hocx_search_terms(concat_ws(' ', tag_text, kw_text, place_text, ctx_text)) AS strong_terms,",
    ),
    (
        "public.hocx_search_fold(concat_ws(' | ', original_name, tag_text, kw_text, ctx_text, meta_text)) AS haystack,",
        "public.hocx_search_fold(concat_ws(' | ', original_name, tag_text, kw_text, place_text, ctx_text, meta_text)) AS haystack,",
    ),
)


def _search_functions_with_places() -> str:
    sql = _search_functions_0217()
    for old, new in _SEARCH_REPLACEMENTS:
        if sql.count(old) != 1:
            raise RuntimeError(f"Suchfunktion unerwartet, Baustein fehlt: {old}")
        sql = sql.replace(old, new)
    return sql


GEO_FUNCTIONS_SQL = rf"""
CREATE OR REPLACE FUNCTION public.hocx_geo_fold(p text) RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE SET search_path = pg_catalog, public
    AS $$ SELECT regexp_replace(public.hocx_search_fold(p), '([aou])e', '\1', 'g') $$;

CREATE OR REPLACE FUNCTION public.hocx_geo_distance_m(lat1 double precision, lon1 double precision,
                                                       lat2 double precision, lon2 double precision)
    RETURNS double precision
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
        SELECT 2 * 6371008.8 * asin(least(1.0, sqrt(
                   power(sin(radians(lat2 - lat1) / 2), 2)
                 + cos(radians(lat1)) * cos(radians(lat2)) * power(sin(radians(lon2 - lon1) / 2), 2))))
    $$;

DROP TYPE IF EXISTS public.hocx_geo_label CASCADE;
CREATE TYPE public.hocx_geo_label AS (
    place_key text, place_name text, place_kind text, place_distance_m integer,
    locality_key text, locality_name text, locality_kind text, locality_distance_m integer,
    admin1_code text, admin1_name text, country_code text, search_text text
);

-- Rangfolge: präziser Ort (Hütte, Gipfel, Pass, See … je mit eigener Reichweite) in der Nähe,
-- sonst nur Ortschaft; dazu immer die Ortschaft (gewichtet nach Grösse) mit Kanton/Land.
CREATE OR REPLACE FUNCTION public.hocx_geo_reverse(p_lat double precision, p_lon double precision)
    RETURNS public.hocx_geo_label
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public
    AS $$
    DECLARE
        result public.hocx_geo_label;
        dlat double precision;
        dlon double precision;
        loc record;
        pre record;
    BEGIN
        IF p_lat IS NULL OR p_lon IS NULL THEN
            RETURN result;
        END IF;
        dlat := 30000 / 111320.0;
        dlon := dlat / greatest(cos(radians(p_lat)), 0.05);
        SELECT c.* INTO loc FROM (
            SELECT g.place_key, g.name, g.kind, g.admin1_code, g.admin1_name, g.country_code, g.search_names,
                   public.hocx_geo_distance_m(p_lat, p_lon, g.latitude, g.longitude) AS d
              FROM geo_place g
             WHERE g.kind IN {LOCALITY_KINDS_SQL}
               AND point(g.longitude, g.latitude) <@ box(point(p_lon - dlon, p_lat - dlat), point(p_lon + dlon, p_lat + dlat))
        ) c
         WHERE c.d <= 30000
         ORDER BY c.d / CASE c.kind WHEN 'city' THEN 3.0 WHEN 'town' THEN 2.0 ELSE 1.3 END, c.place_key
         LIMIT 1;

        dlat := 1500 / 111320.0;
        dlon := dlat / greatest(cos(radians(p_lat)), 0.05);
        SELECT c.* INTO pre FROM (
            SELECT g.place_key, g.name, g.kind, g.search_names,
                   public.hocx_geo_distance_m(p_lat, p_lon, g.latitude, g.longitude) AS d,
                   CASE g.kind
                       WHEN 'hut' THEN 800 WHEN 'peak' THEN 1000
                       WHEN 'pass' THEN 800 WHEN 'lake' THEN 1500 WHEN 'glacier' THEN 1500
                       WHEN 'district' THEN 800 WHEN 'hamlet' THEN 700 WHEN 'station' THEN 300
                       WHEN 'poi' THEN 400 ELSE 400 END AS reach,
                   CASE g.kind
                       WHEN 'hut' THEN 0.6 WHEN 'peak' THEN 0.7 WHEN 'pass' THEN 0.8 WHEN 'lake' THEN 0.9
                       WHEN 'glacier' THEN 0.9 WHEN 'field' THEN 1.4 WHEN 'hamlet' THEN 1.1 ELSE 1.0 END AS factor
              FROM geo_place g
             WHERE g.kind IN {PRECISE_KINDS_SQL}
               AND point(g.longitude, g.latitude) <@ box(point(p_lon - dlon, p_lat - dlat), point(p_lon + dlon, p_lat + dlat))
        ) c
         WHERE c.d <= c.reach
           -- im Dorf/in der Stadt keine Flurnamen und Weiler; Quartiere nur in Städten
           AND (c.kind NOT IN ('field', 'hamlet') OR loc.place_key IS NULL OR loc.d > 1000)
           AND (c.kind <> 'district' OR loc.kind IN ('city', 'town'))
         ORDER BY c.d / c.reach * c.factor, c.place_key
         LIMIT 1;

        IF pre.place_key IS NOT NULL THEN
            result.place_key := pre.place_key;
            result.place_name := pre.name;
            result.place_kind := pre.kind;
            result.place_distance_m := round(pre.d)::integer;
        END IF;
        IF loc.place_key IS NOT NULL THEN
            result.locality_key := loc.place_key;
            result.locality_name := loc.name;
            result.locality_kind := loc.kind;
            result.locality_distance_m := round(loc.d)::integer;
            result.admin1_code := loc.admin1_code;
            result.admin1_name := loc.admin1_name;
            result.country_code := loc.country_code;
        END IF;
        result.search_text := left(concat_ws(' ', pre.name, loc.name, loc.admin1_name,
                                             pre.search_names, loc.search_names), 2000);
        RETURN result;
    END;
    $$;

-- Beschreibung eines gewählten Orts (Ort von Hand): präzise Orte behalten sich selbst als Ort und
-- bekommen die Ortschaft dazu, eine Ortschaft steht allein.
CREATE OR REPLACE FUNCTION public.hocx_geo_describe(p_key text)
    RETURNS TABLE (latitude double precision, longitude double precision, label public.hocx_geo_label)
    LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public
    AS $$
    DECLARE
        g record;
        r public.hocx_geo_label;
    BEGIN
        SELECT p.* INTO g FROM geo_place p WHERE p.place_key = p_key;
        IF g.place_key IS NULL THEN
            RETURN;
        END IF;
        r := public.hocx_geo_reverse(g.latitude, g.longitude);
        IF g.kind IN {LOCALITY_KINDS_SQL} THEN
            r.place_key := NULL; r.place_name := NULL; r.place_kind := NULL; r.place_distance_m := NULL;
            r.locality_key := g.place_key; r.locality_name := g.name; r.locality_kind := g.kind;
            r.locality_distance_m := 0;
            r.admin1_code := g.admin1_code; r.admin1_name := g.admin1_name; r.country_code := g.country_code;
            r.search_text := left(concat_ws(' ', g.name, g.admin1_name, g.search_names), 2000);
        ELSIF g.kind = 'region' THEN
            r.place_key := g.place_key; r.place_name := g.name; r.place_kind := g.kind; r.place_distance_m := 0;
            r.search_text := left(concat_ws(' ', g.name, g.search_names, r.locality_name, r.admin1_name), 2000);
        ELSE
            r.place_key := g.place_key; r.place_name := g.name; r.place_kind := g.kind; r.place_distance_m := 0;
            r.search_text := left(concat_ws(' ', g.name, r.locality_name, r.admin1_name, g.search_names), 2000);
        END IF;
        IF r.country_code IS NULL THEN
            r.country_code := g.country_code;
        END IF;
        latitude := g.latitude;
        longitude := g.longitude;
        label := r;
        RETURN NEXT;
    END;
    $$;

-- GPS-Ort je Foto pflegen (Trigger auf stored_file, Nachtrage-Job). SECURITY DEFINER, weil auch
-- die Abgabebox und der Foto-Worker stored_file schreiben; schreibt nur photo_location, gibt nichts
-- zurück. Ist die Sitzung an einen Mandanten gebunden (hocx_rls_tenant), nur dessen Fotos
-- (Security-Review: kein Umweg über RLS für direkte Aufrufe der Laufzeitrolle). Manuelle Orte: Beschriftung nach einem Datenupdate auffrischen, nie überschreiben -
-- ausser durch echtes GPS.
CREATE OR REPLACE FUNCTION public.hocx_photo_location_refresh(p_ids bigint[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
    AS $$
    DECLARE
        generation bigint;
    BEGIN
        IF p_ids IS NULL OR cardinality(p_ids) = 0 THEN
            RETURN;
        END IF;
        SELECT coalesce(max(d.generation), 0) INTO generation FROM geo_dataset d;

        INSERT INTO photo_location AS pl (
            stored_file_id, tenant_id, source, latitude, longitude,
            place_key, place_name, place_kind, place_distance_m,
            locality_key, locality_name, locality_kind, locality_distance_m,
            admin1_code, admin1_name, country_code, search_text, geo_generation, set_by, updated_at
        )
        SELECT sf.id, sf.tenant_id, 'gps', sf.gps_latitude, sf.gps_longitude,
               (x.r).place_key, (x.r).place_name, (x.r).place_kind, (x.r).place_distance_m,
               (x.r).locality_key, (x.r).locality_name, (x.r).locality_kind, (x.r).locality_distance_m,
               (x.r).admin1_code, (x.r).admin1_name, (x.r).country_code, coalesce((x.r).search_text, ''), generation, NULL, now()
          FROM stored_file sf
         CROSS JOIN LATERAL (SELECT public.hocx_geo_reverse(sf.gps_latitude, sf.gps_longitude) AS r) x
         WHERE sf.id = ANY(p_ids) AND sf.gps_latitude IS NOT NULL AND sf.gps_longitude IS NOT NULL
           AND (public.hocx_rls_tenant() IS NULL OR sf.tenant_id = public.hocx_rls_tenant())
        ON CONFLICT (stored_file_id) DO UPDATE
           SET tenant_id = EXCLUDED.tenant_id, source = 'gps', latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
               place_key = EXCLUDED.place_key, place_name = EXCLUDED.place_name, place_kind = EXCLUDED.place_kind,
               place_distance_m = EXCLUDED.place_distance_m, locality_key = EXCLUDED.locality_key,
               locality_name = EXCLUDED.locality_name, locality_kind = EXCLUDED.locality_kind,
               locality_distance_m = EXCLUDED.locality_distance_m, admin1_code = EXCLUDED.admin1_code,
               admin1_name = EXCLUDED.admin1_name, country_code = EXCLUDED.country_code,
               search_text = EXCLUDED.search_text, geo_generation = EXCLUDED.geo_generation, set_by = NULL,
               updated_at = now()
         WHERE (pl.source, pl.latitude, pl.longitude, pl.place_key, pl.locality_key, pl.search_text, pl.geo_generation)
               IS DISTINCT FROM (EXCLUDED.source, EXCLUDED.latitude, EXCLUDED.longitude, EXCLUDED.place_key,
                                 EXCLUDED.locality_key, EXCLUDED.search_text, EXCLUDED.geo_generation);

        DELETE FROM photo_location pl
         USING stored_file sf
         WHERE pl.stored_file_id = sf.id AND sf.id = ANY(p_ids) AND pl.source = 'gps' AND sf.gps_latitude IS NULL
           AND (public.hocx_rls_tenant() IS NULL OR sf.tenant_id = public.hocx_rls_tenant());

        UPDATE photo_location pl
           SET place_key = (d.label).place_key, place_name = (d.label).place_name, place_kind = (d.label).place_kind,
               place_distance_m = (d.label).place_distance_m, locality_key = (d.label).locality_key,
               locality_name = (d.label).locality_name, locality_kind = (d.label).locality_kind,
               locality_distance_m = (d.label).locality_distance_m, admin1_code = (d.label).admin1_code,
               admin1_name = (d.label).admin1_name, country_code = (d.label).country_code,
               search_text = coalesce((d.label).search_text, ''), latitude = d.latitude, longitude = d.longitude,
               geo_generation = generation, updated_at = now()
          FROM photo_location m
         CROSS JOIN LATERAL public.hocx_geo_describe(coalesce(m.place_key, m.locality_key)) d
         WHERE pl.stored_file_id = m.stored_file_id AND m.stored_file_id = ANY(p_ids) AND m.source = 'manual'
           AND m.geo_generation < generation AND (public.hocx_rls_tenant() IS NULL OR m.tenant_id = public.hocx_rls_tenant());

        -- Manueller Ort, dessen Ort es nach einem Update nicht mehr gibt: Stand behalten, nur abhaken
        UPDATE photo_location pl SET geo_generation = generation
         WHERE pl.stored_file_id = ANY(p_ids) AND pl.source = 'manual' AND pl.geo_generation < generation
           AND (public.hocx_rls_tenant() IS NULL OR pl.tenant_id = public.hocx_rls_tenant());
    END;
    $$;

CREATE OR REPLACE FUNCTION public.hocx_photo_location_touch_stored_file() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
    AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            PERFORM public.hocx_photo_location_refresh(ARRAY(SELECT id FROM nt WHERE gps_latitude IS NOT NULL));
        ELSIF TG_OP = 'UPDATE' THEN
            PERFORM public.hocx_photo_location_refresh(ARRAY(
                SELECT n.id FROM nt n JOIN ot o ON o.id = n.id
                 WHERE (n.gps_latitude, n.gps_longitude) IS DISTINCT FROM (o.gps_latitude, o.gps_longitude)));
        END IF;
        RETURN NULL;
    END;
    $$;

CREATE OR REPLACE FUNCTION public.hocx_photo_location_set_tenant() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public
    AS $$
    BEGIN
        -- tenant_id immer aus der Datei (SECURITY-RULES 2.2), auch bei Schreibzugriffen der App
        NEW.tenant_id := (SELECT sf.tenant_id FROM stored_file sf WHERE sf.id = NEW.stored_file_id);
        RETURN NEW;
    END;
    $$;

CREATE OR REPLACE FUNCTION public.hocx_photo_search_touch_photo_location() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
    AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            PERFORM public.hocx_photo_search_refresh(ARRAY(SELECT DISTINCT stored_file_id FROM nt));
        ELSIF TG_OP = 'UPDATE' THEN
            PERFORM public.hocx_photo_search_refresh(ARRAY(
                SELECT n.stored_file_id FROM nt n JOIN ot o ON o.stored_file_id = n.stored_file_id
                 WHERE n.search_text IS DISTINCT FROM o.search_text));
        ELSIF TG_OP = 'DELETE' THEN
            PERFORM public.hocx_photo_search_refresh(ARRAY(
                SELECT DISTINCT o.stored_file_id FROM ot o JOIN stored_file sf ON sf.id = o.stored_file_id));
        END IF;
        RETURN NULL;
    END;
    $$;

-- Import: Zwischenablage einer Quelle prüfen und in geo_place übernehmen (Upsert je Schlüssel,
-- Fehlendes der Quelle löschen). Läuft als Eigentümer, darum strenge Prüfungen: bekannte Quelle,
-- Schlüssel mit dem Präfix der Quelle, Mindestmenge, höchstens halb so viele Zeilen wie bisher
-- gehen verloren.
-- Ausführen darf nur die Import-Rolle hocx_geo (Security-Review: nicht hocx_app, sonst könnte eine
-- kompromittierte Laufzeitrolle die globalen Ortsnamen verfälschen).
CREATE OR REPLACE FUNCTION public.hocx_geo_import_apply(p_source text, p_version text, p_sha256 text, p_bytes bigint,
                                                         p_min_rows integer)
    RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
    AS $$
    DECLARE
        prefix text;
        staged integer;
        existing integer;
        inserted integer;
        updated integer;
        deleted integer;
        new_generation bigint;
    BEGIN
        prefix := CASE p_source WHEN 'geonames' THEN 'gn:' WHEN 'swissnames3d' THEN 'sn:' END;
        IF prefix IS NULL THEN
            RAISE EXCEPTION 'unbekannte Quelle';
        END IF;
        PERFORM pg_advisory_xact_lock(202600063);
        -- Frisch per COPY gefüllt und UNLOGGED: ohne Statistik plant Postgres das Anti-Join unten
        -- als Nested Loop (Stunden statt Sekunden bei ~1 Mio. Zeilen)
        ANALYZE geo_place_import;
        DELETE FROM geo_place_import i WHERE i.source = p_source AND left(i.place_key, 3) <> prefix;
        SELECT count(DISTINCT i.place_key) INTO staged FROM geo_place_import i WHERE i.source = p_source;
        SELECT count(*) INTO existing FROM geo_place g WHERE g.source = p_source;
        IF staged < greatest(coalesce(p_min_rows, 1), 1) THEN
            RAISE EXCEPTION 'zu wenige Orte (%)', staged;
        END IF;
        IF staged < existing / 2 THEN
            RAISE EXCEPTION 'unplausibler Schwund (% statt %)', staged, existing;
        END IF;

        WITH src AS (
            SELECT DISTINCT ON (i.place_key) i.*
              FROM geo_place_import i
             WHERE i.source = p_source
             ORDER BY i.place_key, i.importance DESC
        ), up AS (
            INSERT INTO geo_place AS g (place_key, source, kind, name, name_fold, latitude, longitude, country_code,
                                        admin1_code, admin1_name, population, elevation_m, importance, search_names)
            SELECT s.place_key, p_source, s.kind, s.name, public.hocx_geo_fold(s.name), s.latitude, s.longitude,
                   s.country_code, s.admin1_code, s.admin1_name, s.population, s.elevation_m, s.importance,
                   left(public.hocx_geo_fold(s.names), 2000)
              FROM src s
            ON CONFLICT (place_key) DO UPDATE
               SET kind = EXCLUDED.kind, name = EXCLUDED.name, name_fold = EXCLUDED.name_fold,
                   latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, country_code = EXCLUDED.country_code,
                   admin1_code = EXCLUDED.admin1_code, admin1_name = EXCLUDED.admin1_name,
                   population = EXCLUDED.population, elevation_m = EXCLUDED.elevation_m,
                   importance = EXCLUDED.importance, search_names = EXCLUDED.search_names
             WHERE g.source = EXCLUDED.source
               AND (g.kind, g.name, g.latitude, g.longitude, g.country_code, g.admin1_code, g.admin1_name,
                    g.population, g.elevation_m, g.importance, g.search_names)
                   IS DISTINCT FROM
                   (EXCLUDED.kind, EXCLUDED.name, EXCLUDED.latitude, EXCLUDED.longitude, EXCLUDED.country_code,
                    EXCLUDED.admin1_code, EXCLUDED.admin1_name, EXCLUDED.population, EXCLUDED.elevation_m,
                    EXCLUDED.importance, EXCLUDED.search_names)
            RETURNING (xmax = 0) AS fresh
        )
        SELECT count(*) FILTER (WHERE fresh), count(*) FILTER (WHERE NOT fresh) INTO inserted, updated FROM up;

        -- Statistik nach dem Upsert (beim ersten Import war geo_place leer): sonst Nested Loop
        ANALYZE geo_place;
        DELETE FROM geo_place g
         USING (
            SELECT p.id FROM geo_place p
              LEFT JOIN geo_place_import i ON i.source = p_source AND i.place_key = p.place_key
             WHERE p.source = p_source AND i.place_key IS NULL
         ) gone
         WHERE g.id = gone.id;
        GET DIAGNOSTICS deleted = ROW_COUNT;
        -- TRUNCATE statt DELETE, wenn sonst nichts wartet: gibt Tabelle und Index sofort frei
        IF EXISTS (SELECT 1 FROM geo_place_import i WHERE i.source <> p_source) THEN
            DELETE FROM geo_place_import i WHERE i.source = p_source;
        ELSE
            TRUNCATE geo_place_import;
        END IF;

        new_generation := nextval('public.geo_place_generation_seq');
        INSERT INTO geo_dataset AS d (source, version, sha256, bytes, row_count, generation, imported_at)
        VALUES (p_source, left(p_version, 200), left(p_sha256, 64), p_bytes, staged, new_generation, now())
        ON CONFLICT (source) DO UPDATE
           SET version = EXCLUDED.version, sha256 = EXCLUDED.sha256, bytes = EXCLUDED.bytes,
               row_count = EXCLUDED.row_count, generation = EXCLUDED.generation, imported_at = EXCLUDED.imported_at;
        RETURN jsonb_build_object('staged', staged, 'inserted', inserted, 'updated', updated, 'deleted', deleted,
                                  'generation', new_generation);
    END;
    $$;
"""

KIND_CHECK = "kind IN (" + ", ".join(f"'{kind}'" for kind in KINDS) + ")"

PLACE_COLUMNS = """
    kind text NOT NULL,
    name text NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    country_code text,
    admin1_code text,
    admin1_name text,
    population integer NOT NULL DEFAULT 0,
    elevation_m integer,
    importance real NOT NULL DEFAULT 0,
"""

PLACE_CHECKS = f"""
    CHECK ({KIND_CHECK}),
    CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180),
    CHECK (length(name) BETWEEN 1 AND 200 AND length(place_key) BETWEEN 4 AND 80),
    CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{{2}}$'),
    CHECK (admin1_code IS NULL OR length(admin1_code) <= 20),
    CHECK (admin1_name IS NULL OR length(admin1_name) <= 200),
    CHECK (population >= 0 AND importance BETWEEN 0 AND 10)
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE geo_place (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            place_key text NOT NULL,
            source text NOT NULL CHECK (source IN ('geonames', 'swissnames3d')),
            {PLACE_COLUMNS}
            name_fold text NOT NULL,
            search_names text NOT NULL,
            CONSTRAINT uq_geo_place_key UNIQUE (place_key),
            CHECK (length(search_names) <= 2000),
            {PLACE_CHECKS}
        )
        """  # sql-ok: feste Spaltenlisten aus diesem Modul
    )
    op.execute(
        f"CREATE INDEX idx_geo_place_precise ON geo_place USING gist (point(longitude, latitude)) "
        f"WHERE kind IN {PRECISE_KINDS_SQL}"  # sql-ok: feste Liste
    )
    op.execute(
        f"CREATE INDEX idx_geo_place_locality ON geo_place USING gist (point(longitude, latitude)) "
        f"WHERE kind IN {LOCALITY_KINDS_SQL}"  # sql-ok: feste Liste
    )
    op.execute("CREATE INDEX idx_geo_place_search ON geo_place USING gin (search_names gin_trgm_ops)")
    op.execute("CREATE INDEX idx_geo_place_source ON geo_place (source)")

    op.execute(
        f"""
        CREATE UNLOGGED TABLE geo_place_import (
            place_key text NOT NULL,
            source text NOT NULL CHECK (source IN ('geonames', 'swissnames3d')),
            {PLACE_COLUMNS}
            names text NOT NULL,
            CHECK (length(names) <= 4000),
            {PLACE_CHECKS}
        )
        """  # sql-ok: feste Spaltenlisten aus diesem Modul
    )
    op.execute("CREATE INDEX idx_geo_place_import_key ON geo_place_import (source, place_key)")
    op.execute("CREATE SEQUENCE public.geo_place_generation_seq")
    op.execute(
        """
        CREATE TABLE geo_dataset (
            source text PRIMARY KEY CHECK (source IN ('geonames', 'swissnames3d')),
            version text NOT NULL,
            sha256 text,
            bytes bigint,
            row_count integer NOT NULL DEFAULT 0,
            generation bigint NOT NULL,
            imported_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE photo_location (
            stored_file_id bigint PRIMARY KEY REFERENCES stored_file(id) ON DELETE CASCADE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            source text NOT NULL CHECK (source IN ('gps', 'manual')),
            latitude double precision NOT NULL,
            longitude double precision NOT NULL,
            place_key text,
            place_name text,
            place_kind text,
            place_distance_m integer,
            locality_key text,
            locality_name text,
            locality_kind text,
            locality_distance_m integer,
            admin1_code text,
            admin1_name text,
            country_code text,
            search_text text NOT NULL DEFAULT '',
            geo_generation bigint NOT NULL DEFAULT 0,
            set_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180),
            CHECK (source = 'gps' OR place_key IS NOT NULL OR locality_key IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX idx_photo_location_coords ON photo_location (tenant_id, latitude, longitude)")
    op.execute("CREATE INDEX idx_photo_location_generation ON photo_location (geo_generation)")

    op.execute(
        """
        CREATE TABLE place_change_batch (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            created_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            mode text NOT NULL CHECK (mode IN ('set', 'clear')),
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            upload_job_id uuid,
            updated_count integer NOT NULL DEFAULT 0,
            undone_at timestamptz,
            undone_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            CONSTRAINT uq_place_change_batch_tenant UNIQUE (tenant_id, id),
            CONSTRAINT fk_place_change_batch_upload_job FOREIGN KEY (tenant_id, upload_job_id)
                REFERENCES upload_job (tenant_id, id) ON DELETE SET NULL (upload_job_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_place_change_batch_job ON place_change_batch (tenant_id, upload_job_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE place_change_item (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id uuid NOT NULL,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            stored_file_id bigint NOT NULL REFERENCES stored_file(id) ON DELETE CASCADE,
            prev_place_key text,
            new_place_key text,
            CONSTRAINT fk_place_change_item_batch FOREIGN KEY (tenant_id, batch_id)
                REFERENCES place_change_batch (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_place_change_item UNIQUE (batch_id, stored_file_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_place_change_item_file ON place_change_item (stored_file_id)")

    for table in ("photo_location", "place_change_batch", "place_change_item"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Tabellen/Policy
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname

    op.execute(GEO_FUNCTIONS_SQL)
    op.execute(
        "CREATE TRIGGER trg_photo_location_tenant BEFORE INSERT OR UPDATE OF stored_file_id, tenant_id ON photo_location "
        "FOR EACH ROW EXECUTE FUNCTION public.hocx_photo_location_set_tenant()"
    )
    op.execute(
        "CREATE TRIGGER trg_photo_location_insert AFTER INSERT ON stored_file REFERENCING NEW TABLE AS nt "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.hocx_photo_location_touch_stored_file()"
    )
    op.execute(
        "CREATE TRIGGER trg_photo_location_update AFTER UPDATE ON stored_file REFERENCING OLD TABLE AS ot NEW TABLE AS nt "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.hocx_photo_location_touch_stored_file()"
    )
    for event, referencing in (
        ("INSERT", "REFERENCING NEW TABLE AS nt"),
        ("UPDATE", "REFERENCING OLD TABLE AS ot NEW TABLE AS nt"),
        ("DELETE", "REFERENCING OLD TABLE AS ot"),
    ):
        op.execute(
            f"CREATE TRIGGER trg_photo_search_{event.lower()} AFTER {event} ON photo_location {referencing} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.hocx_photo_search_touch_photo_location()"  # sql-ok: feste Ereignisse
        )

    # Suchdokument mit Ortsnamen (CREATE OR REPLACE behält Eigentümer und entzogene Rechte)
    op.execute(_search_functions_with_places())

    # Rechte: Referenzdaten nur lesen; die Zwischenablage ist die einzige Schreibstelle des Imports.
    # SECURITY-DEFINER-Funktionen nur für die Laufzeitrolle, die sie braucht.
    for function in (
        "hocx_photo_location_refresh(bigint[])", "hocx_geo_import_apply(text, text, text, bigint, integer)",
        "hocx_photo_location_touch_stored_file()", "hocx_photo_search_touch_photo_location()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC")  # sql-ok: feste Signaturen
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['hocx_app', 'hocx_abgabebox', 'hocx_photo_worker'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON TABLE public.geo_place, public.geo_dataset, public.geo_place_import FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON SEQUENCE public.geo_place_generation_seq FROM %I', role_name);
                END IF;
            END LOOP;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hocx_app') THEN
                GRANT SELECT ON TABLE public.geo_place, public.geo_dataset TO hocx_app;
                GRANT EXECUTE ON FUNCTION public.hocx_photo_location_refresh(bigint[]) TO hocx_app;
            END IF;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON TABLE public.geo_place, public.geo_dataset, public.geo_place_import FROM PUBLIC")

    # Import-Rolle: Zwischenablage schreiben, Übernahme ausführen, Ortsdaten lesen - sonst nichts
    _ensure_geo_role()
    db_name = op.get_bind().execute(sa.text("SELECT current_database()")).scalar()
    op.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO {GEO_ROLE}')  # sql-ok: Datenbankname aus current_database()
    op.execute(f"GRANT USAGE ON SCHEMA public TO {GEO_ROLE}")  # sql-ok: fester Rollenname
    op.execute(f"GRANT SELECT ON TABLE public.geo_place, public.geo_dataset TO {GEO_ROLE}")  # sql-ok: feste Namen
    op.execute(f"GRANT SELECT, INSERT, DELETE ON TABLE public.geo_place_import TO {GEO_ROLE}")  # sql-ok: feste Namen
    op.execute(
        f"GRANT EXECUTE ON FUNCTION public.hocx_geo_import_apply(text, text, text, bigint, integer) TO {GEO_ROLE}"  # sql-ok: feste Namen
    )

    # Bestand: GPS-Fotos bekommen sofort ihre Zeile (ohne Ortsnamen, solange keine Ortsdaten
    # importiert sind) - Umkreissuche über Koordinaten geht damit ab dem ersten Import; die
    # Beschriftung trägt der Job photo_places_resolve in Stücken nach.
    op.execute(
        """
        INSERT INTO photo_location (stored_file_id, tenant_id, source, latitude, longitude, search_text, geo_generation)
        SELECT sf.id, sf.tenant_id, 'gps', sf.gps_latitude, sf.gps_longitude, '', -1
          FROM stored_file sf
         WHERE sf.gps_latitude IS NOT NULL AND sf.gps_longitude IS NOT NULL
        """
    )


def downgrade() -> None:
    # Rechte nur in dieser Datenbank entziehen; die Rolle ist clusterweit und bleibt bestehen, wenn
    # eine andere Datenbank (z. B. hocx_pre_restore_*) noch Rechte für sie hält.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{GEO_ROLE}') THEN
                EXECUTE 'DROP OWNED BY {GEO_ROLE}';
                EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {GEO_ROLE}', current_database());
                BEGIN
                    DROP ROLE {GEO_ROLE};
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    RAISE NOTICE 'Rolle {GEO_ROLE} bleibt: Rechte in anderen Datenbanken';
                END;
            END IF;
        END
        $$;
        """  # sql-ok: fester Rollenname
    )
    op.execute(_search_functions_0217())
    for event in ("insert", "update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_photo_search_{event} ON photo_location")  # sql-ok: feste Namen
    op.execute("DROP TRIGGER IF EXISTS trg_photo_location_insert ON stored_file")
    op.execute("DROP TRIGGER IF EXISTS trg_photo_location_update ON stored_file")
    # Ortsnamen aus den Suchdokumenten nehmen, bevor die Tabelle verschwindet
    op.execute("CREATE TEMP TABLE _photo_places_ids ON COMMIT DROP AS SELECT stored_file_id AS id FROM photo_location")
    op.execute("DROP TABLE IF EXISTS place_change_item")
    op.execute("DROP TABLE IF EXISTS place_change_batch")
    op.execute("DROP TABLE IF EXISTS photo_location")
    op.execute("SELECT public.hocx_photo_search_refresh(ARRAY(SELECT id FROM _photo_places_ids))")
    for function in (
        "hocx_photo_search_touch_photo_location()", "hocx_photo_location_touch_stored_file()",
        "hocx_photo_location_set_tenant()", "hocx_photo_location_refresh(bigint[])",
        "hocx_geo_import_apply(text, text, text, bigint, integer)", "hocx_geo_describe(text)",
        "hocx_geo_reverse(double precision, double precision)",
        "hocx_geo_distance_m(double precision, double precision, double precision, double precision)",
        "hocx_geo_fold(text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS public.{function}")  # sql-ok: feste Signaturen
    op.execute("DROP TYPE IF EXISTS public.hocx_geo_label")
    op.execute("DROP TABLE IF EXISTS geo_dataset")
    op.execute("DROP SEQUENCE IF EXISTS public.geo_place_generation_seq")
    op.execute("DROP TABLE IF EXISTS geo_place_import")
    op.execute("DROP TABLE IF EXISTS geo_place")
