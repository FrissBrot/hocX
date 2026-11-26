"""Security-Review 1.6.0 (Zusammenspiel): IDs und Referenzen der Cloud-Quellen strikt prüfen.

Mit ``re.match`` und ``$`` ging ein angehängtes «\\n» durch (z. B. Picker-Auswahl ohne Sitzung);
jetzt verankern die Muster mit ``\\Z``. Einzelne Picker-IDs sind zusätzlich in der Länge begrenzt.
"""

import pytest
from pydantic import ValidationError

from app.api.routes.cloud_import_google import PickerApplyIn
from app.services.cloud_import import dav_http, rules
from app.services.cloud_import.providers import base, dropbox, google_common, google_photos, microsoft, webdav


@pytest.mark.parametrize(
    ("pattern", "valid"),
    [
        (google_common.GOOGLE_ID, "1AbC_d-9"),
        (google_common.PAGE_TOKEN, "abc~=+/."),
        (microsoft._ID, "01ABC!12,3"),
        (base.SAFE_REF, "id:abc@x"),
        (dropbox._REF, "id:AbC_1"),
        (dav_http._REF, "pAbC_1"),
        (google_photos._IMAGE_HOST, "lh3.googleusercontent.com"),
        (webdav._KDRIVE_ID, "123456"),
        (rules._RULE_ID, "rule_1"),
        (dav_http._LABEL, "kdrive"),
        (dav_http._TLD, "ch"),
    ],
)
def test_pattern_rejects_trailing_newline(pattern, valid):
    assert pattern.match(valid)
    assert pattern.match(valid + "\n") is None


def test_microsoft_id_still_rejects_dot_segments():
    assert microsoft._ID.match(".") is None
    assert microsoft._ID.match("..") is None
    assert microsoft._ID.match("..\n") is None


def test_picker_apply_limits_single_id_length():
    PickerApplyIn(ticket="t" * 20, file_ids=["a" * 300])
    with pytest.raises(ValidationError):
        PickerApplyIn(ticket="t" * 20, file_ids=["a" * 301])
