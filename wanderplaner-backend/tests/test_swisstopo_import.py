import struct

import pytest
from shapely.geometry import LineString

from scripts.import_swisstopo_network import edge_record, geopackage_wkb


def _row(**changes):
    row = dict(uuid='official-id', objektart='1m Weg', wanderwege='Wanderweg',
               verkehrsbeschraenkung='Keine', geom=b'GP\x00\x01' + struct.pack('<i', 2056)
               + LineString([(2600000,1200000,500),(2600030,1200040,510),(2600060,1200080,505)]).wkb)
    return {**row, **changes}


def test_lv95_geometry_has_metric_costs_and_directional_elevation():
    row = edge_record(_row())
    assert row[1:4] == (100, 10, 5)
    assert row[4:7] == ('wanderweg', 'fussweg', 'official-id')
    assert row[7] > row[10] > 0  # Aufstieg in Vorwärtsrichtung kostet mehr.


@pytest.mark.parametrize('objektart', ['Autobahn','Autostrasse','Einfahrt','Faehre','unbekannt'])
def test_non_walkable_or_unknown_classes_are_excluded(objektart):
    assert edge_record(_row(objektart=objektart)) is None


@pytest.mark.parametrize('restriction', ['Gesperrt','Fussgaengerverbot','Gesicherte Kletterpartie'])
def test_closed_paths_are_excluded(restriction):
    assert edge_record(_row(verkehrsbeschraenkung=restriction)) is None


def test_suitable_non_hiking_paths_can_be_imported_from_full_swisstlm():
    assert edge_record(_row(wanderwege='andere',objektart='2m Weg'))[4:6] == (None,'forststrasse')


def test_rejects_unrecognized_hiking_category():
    with pytest.raises(ValueError, match='Wanderwegklasse'):
        edge_record(_row(wanderwege='new category'))


@pytest.mark.parametrize('envelope,values', [(0,0),(1,4),(2,6),(3,6),(4,8)])
def test_geopackage_envelope_headers(envelope, values):
    wkb = LineString([(0,0,1),(1,1,2)]).wkb
    blob = b'GP\x00' + bytes([1 | envelope << 1]) + struct.pack('<i',2056) + b'\x00'*(values*8) + wkb
    assert geopackage_wkb(blob) == wkb


def test_rejects_wrong_crs_before_import():
    with pytest.raises(ValueError, match='LV95'):
        geopackage_wkb(b'GP\x00\x01'+struct.pack('<i',4326))


def _write_geopackage(path, rows):
    import sqlite3
    with sqlite3.connect(path) as source:
        source.execute('CREATE TABLE gpkg_geometry_columns(table_name text,column_name text,srs_id int)')
        source.execute("INSERT INTO gpkg_geometry_columns VALUES ('tlm_strassen_strasse','geom',2056)")
        source.execute('CREATE TABLE tlm_strassen_strasse(id integer primary key,geom blob,uuid text,objektart text,wanderwege text,verkehrsbeschraenkung text)')
        for row in rows:
            source.execute('INSERT INTO tlm_strassen_strasse(geom,uuid,objektart,wanderwege,verkehrsbeschraenkung) VALUES (?,?,?,?,?)',
                           tuple(row[key] for key in ('geom','uuid','objektart','wanderwege','verkehrsbeschraenkung')))


def test_real_geopackage_import_builds_wgs84_network_and_provenance(db, routing_network, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import text
    from scripts import import_swisstopo_network as importer

    @contextmanager
    def transaction_session():
        yield db  # Äußerer Test-SAVEPOINT setzt auch DDL am Ende zurück.

    monkeypatch.setattr(importer, '_AdminSession', transaction_session)
    path = tmp_path/'sample.gpkg'
    _write_geopackage(path, [_row(), _row(objektart='Autobahn')])
    assert importer.import_geopackage(path, 'Integrationstest') == 1
    row = db.execute(text('SELECT ST_SRID(geom), ST_X(ST_StartPoint(geom)), ST_Y(ST_StartPoint(geom)), source,target,length_m FROM routing_edge')).one()
    assert row[0] == 4326
    assert row[1] == pytest.approx(7.4386, abs=0.001)
    assert row[2] == pytest.approx(46.9511, abs=0.001)
    assert row[3] is not None and row[4] is not None and row[3] != row[4]
    assert row[5] == 100
    assert 'SHA256=' in db.scalar(text('SELECT source_description FROM routing_network_meta ORDER BY id DESC LIMIT 1'))


def test_invalid_import_preserves_existing_network(db, routing_network, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import text
    from scripts import import_swisstopo_network as importer

    @contextmanager
    def transaction_session():
        yield db

    monkeypatch.setattr(importer, '_AdminSession', transaction_session)
    before = db.scalar(text('SELECT count(*) FROM routing_edge'))
    path = tmp_path/'invalid.gpkg'
    _write_geopackage(path, [_row(wanderwege='unbekannt')])
    with pytest.raises(ValueError, match='Wanderwegklasse'):
        with db.begin_nested():
            importer.import_geopackage(path, 'Ungültiger Import')
    assert db.scalar(text('SELECT count(*) FROM routing_edge')) == before
