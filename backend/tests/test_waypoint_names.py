"""Andere Geo-Namen vor Kombinationen wählen; keine künstlichen Namenszusätze."""
from app.core.waypoint_names import unique_environment_name


def test_selects_next_unused_environment_name_before_combining():
    assert unique_environment_name(['Oberalp', 'Alpbach', 'Hüttenweg'], ['Oberalp']) == 'Alpbach'


def test_combines_nearby_names_when_all_individual_names_are_taken():
    assert unique_environment_name(['Oberalp', 'Alpbach'], ['Oberalp', 'Alpbach']) == 'Oberalp / Alpbach'


def test_avoids_duplicate_combined_names():
    assert unique_environment_name(['Oberalp', 'Alpbach', 'Hüttenweg'],
        ['Oberalp', 'Alpbach', 'Hüttenweg', 'Oberalp / Alpbach']) == 'Oberalp / Hüttenweg'


def test_compares_names_without_case_or_whitespace_differences():
    assert unique_environment_name([' Oberalp ', 'oberalp', 'Alpbach'], ['OBERALP']) == 'Alpbach'


def test_does_not_invent_names_when_local_names_are_exhausted():
    assert unique_environment_name([], ['Oberalp']) is None
    assert unique_environment_name(['Oberalp'], ['Oberalp']) is None
