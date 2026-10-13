# Vendorte Typst-Pakete

Der Typst-Compile der Dokument-Engine lädt Pakete ausschliesslich aus diesem Verzeichnis
(`package_path` in `app/documents/renderer.py`); der Download-Cache zeigt pro Compile auf ein
leeres Temp-Verzeichnis. Ein Paket wird nur verwendet, wenn es hier liegt.

Aufbau wie der lokale Typst-Paketspeicher: `<namespace>/<name>/<version>/` mit `typst.toml`
und der Lizenz des Pakets. Import im Stil: `#import "@preview/<name>:<version>": ...`.

`scripts/check-document-catalog.py` prüft, dass jeder `@<namespace>/…`-Import in
`app/documents/styles/` hier vorhanden ist.

Derzeit ist kein Paket nötig: Diagramme und QR-Codes sind eigene, kleine Komponenten
(siehe `docs-site/docs/technik/dokument-engine.md`).
