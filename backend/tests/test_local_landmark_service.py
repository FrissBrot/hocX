import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.services.route_landmark_service import RouteLandmarkService


def test_local_lookup_never_uses_http_and_filters_by_route(db):
    db.execute(text("INSERT INTO hiking_landmark_import(id,source,feature_count) VALUES(1,'test',2) ON CONFLICT(id) DO NOTHING"))
    for identifier, lon in [(1,8.5),(2,9.5)]:
        db.execute(text('''INSERT INTO hiking_landmark(osm_type,osm_id,tags,geom)
            VALUES('node',:id,cast(:tags as jsonb), ST_Transform(ST_SetSRID(ST_MakePoint(:lon,47),4326),2056))'''),
            {'id':identifier, 'lon':lon,'tags':json.dumps({'tourism':'alpine_hut','name':'Testhütte'})})
    with patch('urllib.request.urlopen', side_effect=AssertionError('Keine externen Abfragen erlaubt')):
        result = RouteLandmarkService().fetch(db, [(8.499,47),(8.501,47)])
    assert [element['id'] for element in result] == [1]
    assert result[0]['tags']['name'] == 'Testhütte'


def test_missing_import_reports_clear_error_without_online_fallback(db):
    db.execute(text('DELETE FROM hiking_landmark_import'))
    with patch('urllib.request.urlopen', side_effect=AssertionError('Keine externen Abfragen erlaubt')):
        with pytest.raises(ValueError, match='Lokale Umgebungsdaten fehlen'):
            RouteLandmarkService().fetch(db, [(8.499,47),(8.501,47)])
