# Wanderplaner: echtes Wegenetz

Die Kartenansicht liegt unter `/hiking-planner`. Die Hintergrundkarte liefert keine
Routingdaten: Für die Wegsuche muss das Wegenetz einmal separat importiert werden.

## Architektur

Der Wanderplaner ist ein eigener Fachservice mit eigener Datenbank:

```
Browser ─► frontend ─► backend  /api/hiking-tours/*   (Login, Mandant, Rolle, Feature,
                         │                              Audit, Druck-PDF als StoredFile,
                         │  internes Token +            Fotoalben pro Tour)
                         │  X-Hocx-Tenant-Id/-User-*
                         ▼
                   wanderplaner-backend   (Routing, Höhenprofil, Analyse, Kartendruck)
                         ▼
                   wanderplaner-db        (PostGIS + pgRouting: Touren, Wegenetz, OSM-Daten)
```

- `wanderplaner-backend` ist nur im internen Docker-Netz erreichbar und lehnt jede Anfrage
  ohne `WANDERPLANER_INTERNAL_TOKEN` ab. Das Frontend spricht unverändert mit
  `/api/hiking-tours` im hocX-Backend.
- Touren referenzieren Mandanten und Benutzer nur per ID. Beim Löschen eines Mandanten
  ruft hocX `DELETE /internal/tenants/{id}` auf.
- Fotos bleiben in hocX. Für die automatischen Alben schickt hocX nur Koordinaten und
  Aufnahmedatum an `POST /internal/tenants/{id}/photo-matches`.
- Die hocX-Kerndatenbank bleibt `postgres:16` ohne Geo-Erweiterungen.
- Ein Mandant, bei dem nur das Feature `wanderplaner` freigeschaltet ist, nutzt hocX als
  reinen Wanderplaner.

## Erstimport und Aktualisierung

Im gewünschten Stack (korrekten Compose-Projektnamen und dessen Dateien verwenden):

```sh
docker compose exec wanderplaner-backend python -m scripts.import_swisstopo_network --download
```

Für den lokalen Wanderplaner-Branch:

```sh
docker exec hocx-dev-wanderplaner-wanderplaner-backend-1 python -m scripts.import_swisstopo_network --download
```

Die Importskripte verwenden die Admin-Rolle (`WANDERPLANER_DATABASE_URL`), der laufende
Service die eingeschränkte Rolle `wanderplaner_app` (`WANDERPLANER_APP_DATABASE_URL`).

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
  run --rm wanderplaner-backend-test sh -c "alembic upgrade head && python -m pytest \
  tests/test_routing_service.py tests/test_routing_cost.py tests/test_swisstopo_import.py"
```

Alle Wanderplaner-Tests: `./scripts/test.sh wanderplaner-backend`.

Die Tests prüfen gekrümmte Teilkanten in beiden Richtungen, Profilunterschiede,
Netzlücken, entfernte Punkte, Rundtouren, Höhenprofil-Invalidierung und GeoPackage-Mapping.

## Automatische Wegpunkte aus lokalen Umgebungsdaten

Einmalig im `wanderplaner-backend`-Container ausführen:

```sh
python -m scripts.import_osm_landmarks --download
```

Alternativ `--pbf /data/switzerland.osm.pbf`. Der öffentliche
[Schweizer Landesextrakt von Geofabrik](https://download.geofabrik.de/europe/switzerland.html)
wird heruntergeladen und mit `osmium` in die lokale PostGIS-Datenbank importiert.
Quelle: © [OpenStreetMap-Mitwirkende](https://www.openstreetmap.org/copyright), ODbL.
Der Download enthält keine Anfrage nach einer konkreten Wanderroute. Rohdateien werden
nach dem Import entfernt. Für Aktualisierungen denselben Befehl erneut ausführen;
Fehler lassen den bisherigen Datensatz unverändert. Quelle, SHA256, Objektanzahl und
Importzeit stehen in `hiking_landmark_import`. Import und Index benötigen zusätzlich
zum rund 500 MB grossen Download freien Datenbank- und temporären Speicherplatz.

Die Analyse selbst verwendet ausschliesslich lokale Daten: OSM-Verzweigungen
(mindestens drei verbundene Wegäste), tatsächliche Bach-/Strassenquerungen und Hütten
bzw. Alpen unmittelbar an der Route. Parallel verlaufende Strassen und reine Kurven
werden nicht als Querungen gewertet. Das vorhandene Höhenprofil bestimmt mit dem
Gruppentempo die Gehzeit. Ziel sind etwa 15 Minuten zwischen markanten Punkten;
nahe Kandidaten werden zusammengefasst (mindestens 7 Gehminuten und 100 m Abstand),
bevorzugt werden Querungen und Hütten. Es gibt keine künstlichen Füllpunkte in
Abschnitten ohne geeignete Orte. Namen stammen aus OSM, bei fehlendem Namen aus der
nahen Umgebung. Wiederholte/unbenannte Orte erhalten einen eindeutigen Kilometerzusatz.

Die vorhandene Route wird lokal in Teilabschnitte aufgeteilt, statt sie wegen neuer
Orientierungspunkte neu zu berechnen. Das gespeicherte Höhenprofil wird weiterverwendet;
Analyse und erneute Analyse rufen keine externen Dienste auf. Fehlen lokale Daten,
erscheint eine Fehlermeldung; es gibt **keinen Online-Fallback**. Der separate,
bestehende Höhenprofil-Abruf verwendet weiterhin swisstopo und ist kein Bestandteil
der automatischen Analyse. Vor jedem solchen Abruf fragt die Oberfläche nach Zustimmung. Geodaten sind nicht vollständig: die Vorschläge behalten
den Status „Automatisch erkannt“ und müssen geprüft werden.
