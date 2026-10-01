# Wanderplaner: echtes Wegenetz

Die Kartenansicht liegt unter `/hiking-planner`. Die Hintergrundkarte liefert keine
Routingdaten: Für die Wegsuche muss das Wegenetz einmal separat importiert werden.

## Erstimport und Aktualisierung

Im gewünschten Stack (korrekten Compose-Projektnamen und dessen Dateien verwenden):

```sh
docker compose exec backend python -m scripts.import_swisstopo_network --download
```

Für den lokalen Wanderplaner-Branch:

```sh
docker exec hocx-dev-wanderplaner-backend-1 python -m scripts.import_swisstopo_network --download
```

Quelle ist das offizielle [swissTLM3D-Wanderwegenetz](https://opendata.swiss/de/dataset/swisstlm3d-wanderwege)
von swisstopo, schweizweit einschließlich Liechtenstein. Der Download benötigt ca.
200 MB, temporär zusätzlich den entpackten GeoPackage-Datensatz und Platz für das
Datenbanknetz. Der Aufbau dauert mehrere Minuten. Download und Rohdaten werden bei
`--download` anschließend entfernt. Das Paket enthält signalisierte Wanderwege;
es ist kein vollständiges Verzeichnis aller begehbaren Verbindungen.

Bereits heruntergeladene GeoPackages können mit `--gpkg /pfad/network.gpkg`
importiert werden. Unterstützt wird der `tlm_strassen_strasse`-Layer in LV95/EPSG:2056
mit 3D-Geometrien und den benannten swissTLM3D-Attributwerten. Ein vollständiger
swissTLM3D-Strassenlayer kann ebenso importiert werden: geeignete Wege ohne
Wanderwegstatus bleiben nutzbar, die Profile gewichten diese unterschiedlich.
Autobahnen, Autostrassen, Ein-/Ausfahrten, Fähren, gesperrte Wege, gesicherte
Kletterpartien und unbekannte Wegklassen werden nicht als Fusswege übernommen.
Die Daten sind ein statischer Stand; kurzfristige Sperrungen sind nicht garantiert enthalten.

Der Import streamt die Quelldaten in eine temporäre Tabelle, validiert Kategorien,
Koordinaten und Höhen, transformiert mit PostGIS nach WGS84 und baut die Topologie.
Netzersetzung und Metadaten werden zusammen in einer Transaktion übernommen;
bei Fehlern bleibt das bisherige Netz erhalten. Während des abschließenden
Netztauschs können Routing-Anfragen warten. `routing_network_meta` protokolliert
Quelle, SHA256 des GeoPackages und Anzahl Wegabschnitte. Tourabschnitte speichern
die verwendete Netzversion. Es werden keine bestehenden Touren überschrieben.

**Das Testfixture ist kein produktives Wegenetz.** Tests mit `routing_network`
ausschließlich im separaten Test-Stack ausführen; die Fixture ersetzt dessen Netz.

## Verhalten der Wegsuche

- Start, Ziel und Zwischenpunkte werden auf Wegkanten innerhalb von **150 m** projiziert.
- pgRouting `pgr_withPoints` berücksichtigt Start/Ziel mitten auf einer Kante,
  inklusive gekürzter Geometrie und korrekter Richtung.
- Die sichtbare Route folgt ausschließlich den importierten Weggeometrien.
  Es gibt keine erfundenen Luftlinien zum Weg oder zwischen unverbundenen Netzen.
- Fehlende Abdeckung oder unverbundene Wege ergeben eine verständliche Meldung (HTTP 422).
- Nach neuer Routenberechnung wird das alte Höhenprofil verworfen und kann neu
  abgerufen werden. Höhenmeter der Teilkanten werden anteilig aus der importierten
  Kante ermittelt; das separat abrufbare Höhenprofil liefert die feinere Verteilung.
- Eine erneute automatische Analyse ersetzt alte automatische Punkte und berechnet
  zuerst die Route zwischen den verbleibenden manuellen Punkten neu.
- Bereits gespeicherte alte Routen bleiben bis **Route berechnen** unverändert.
  Dadurch ändert ein Netzupdate keine Planung stillschweigend.

## Verifikation

```sh
docker compose -p hocx-tests-wanderplaner -f docker-compose.tests.yml --profile tests \
  run --rm backend-test python -m pytest \
  tests/test_routing_service.py tests/test_routing_cost.py tests/test_swisstopo_import.py
```

Die Tests prüfen gekrümmte Teilkanten in beiden Richtungen, Profilunterschiede,
Netzlücken, entfernte Punkte, Rundtouren, Höhenprofil-Invalidierung und GeoPackage-Mapping.
