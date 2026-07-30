import json
from io import BytesIO

import pytest
from urllib.error import URLError

from app.services import songbook_service
from app.services.songbook_service import LyricsProviderError, SongbookService


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_search_lyrics_maps_lrclib_results(monkeypatch):
    payload = [
        {
            "id": 42,
            "trackName": "Testlied",
            "artistName": "Testband",
            "albumName": "Album",
            "duration": 123.6,
            "plainLyrics": "Erste Zeile\nZweite Zeile",
            "instrumental": False,
        }
    ]
    monkeypatch.setattr(
        songbook_service,
        "urlopen",
        lambda request, timeout: _Response(json.dumps(payload).encode()),
    )

    results = SongbookService().search_lyrics("Testband Testlied")

    assert len(results) == 1
    assert results[0].source_id == "42"
    assert results[0].title == "Testlied"
    assert results[0].artist == "Testband"
    assert results[0].duration_seconds == 124
    assert results[0].lyrics == "Erste Zeile\nZweite Zeile"


def test_search_lyrics_wraps_provider_failure(monkeypatch):
    def fail(_request, timeout):
        raise URLError("offline")

    monkeypatch.setattr(songbook_service, "urlopen", fail)

    with pytest.raises(LyricsProviderError, match="derzeit nicht erreichbar"):
        SongbookService().search_lyrics("Testlied")
