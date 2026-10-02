from sqlalchemy import text
import pytest

from scripts import import_osm_landmarks


def test_import_retains_names_topology_and_rolls_back_empty_file(db, tmp_path, monkeypatch):
    # Der Import besitzt absichtlich eine eigene Admin-Transaktion; Testdatenbank verwenden.
    from contextlib import contextmanager
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(import_osm_landmarks, '_AdminSession', session)
    monkeypatch.setattr(db, 'commit', lambda: db.flush())
    source = tmp_path/'fixture.osm'
    source.write_text('''<osm version="0.6">
      <node id="1" lat="47" lon="8.5" version="1"/>
      <node id="2" lat="47.001" lon="8.501" version="1"/>
      <node id="3" lat="47.0005" lon="8.5005" version="1"><tag k="tourism" v="alpine_hut"/><tag k="name" v="Testhütte"/></node>
      <way id="10" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="path"/><tag k="name" v="Alpweg"/></way>
    </osm>''')
    assert import_osm_landmarks.import_pbf(source) == 2
    row = db.execute(text("SELECT tags,nodes,ST_SRID(geom) FROM hiking_landmark WHERE osm_type='way'")).one()
    assert row[0]['name'] == 'Alpweg'
    assert row[1] == [1,2]
    assert row[2] == 2056
    # Temp staging gehört zur Importtransaktion, in diesem Test gibt es keinen Commit.
    db.execute(text('DROP TABLE landmark_stage'))
    source.write_text('<osm version="0.6"></osm>')
    with pytest.raises(ValueError, match='Keine Umgebungsdaten'):
        import_osm_landmarks.import_pbf(source)
    assert db.scalar(text('SELECT count(*) FROM hiking_landmark')) == 2
