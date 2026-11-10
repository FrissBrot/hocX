# Vendorte Typst-Pakete

Der Typst-Compile der Dokument-Engine lädt Pakete ausschliesslich aus diesem Verzeichnis
(`package_path` in `app/documents/renderer.py`); der Download-Cache zeigt pro Compile auf ein
leeres Temp-Verzeichnis. Ein Paket wird nur verwendet, wenn es hier liegt.

Aufbau wie der lokale Typst-Paketspeicher: `<namespace>/<name>/<version>/` mit `typst.toml`
und der Lizenz des Pakets. Import in den Typst-Dateien: `#import "@preview/<name>:<version>": ...`.

`scripts/check-document-catalog.py` prüft, dass jeder `@<namespace>/…`-Import in
`app/documents/typst/` hier vorhanden ist.

Vendored:

| Paket | Lizenz | Zweck | Herkunft |
|---|---|---|---|
| `preview/tiaoma/0.3.0` | MIT (Zint-Kern BSD-3, siehe `license.html`) | QR-Codes (Prüfvermerk, Block `qr_link`) | `https://packages.typst.org/preview/tiaoma-0.3.0.tar.gz`, SHA-256 `c646c3f41c3f1a062ff1558f070187ac970b7d350f00b31f45133e059c9981be` |

Diagramme sind eigene, kleine Komponenten (siehe `docs-site/docs/technik/dokument-engine.md`).
