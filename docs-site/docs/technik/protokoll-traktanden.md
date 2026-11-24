# Traktanden im Protokoll (Editor 1a)

Seit 1.6 lassen sich Traktanden im Protokoll-Editor hinzufügen, umbenennen, aus-/einblenden und
atomar umsortieren. Grundsatz: **Änderungen im Protokoll ändern nie die Vorlage.** Nur die
ausdrückliche Übernahme beim Abschliessen (Recht `templates.edit`) schreibt in die Vorlage.

Code: `backend/app/services/protocol_agenda_service.py` (Hinzufügen, Umbenennen, Sichtbarkeit,
Sortieren, Abweichungen, Übernahme), Routen in `api/routes/protocol_elements.py` und
`api/routes/protocols.py`, Abgleich in `ProtocolService._apply_template_sync` /
`_restore_agenda_order`. API-Vertrag: Plan `2026-11-23-editor-1a-plan.md`, Abschnitt «API».

## Datenmodell (Migration 0270)

| Spalte | Bedeutung |
|---|---|
| `protocol_element.origin` | `template` (aus der Vorlage), `protocol` (im Editor hinzugefügt), `session` (Sitzungsnotizen), `import` (Word-Import). CHECK-Constraint; Bestand rückgefüllt. |
| `protocol_element.template_title_snapshot` | Titel laut Vorlage, sobald im Protokoll umbenannt (NULL = nicht umbenannt). |
| `protocol_element.visibility_customized` | Sichtbarkeit im Protokoll geändert. |
| `protocol.agenda_order_customized` | Reihenfolge im Protokoll geändert (PUT element-order oder veralteter PATCH `sort_index`). |
| `template_element.is_visible` | Bisher ungenutzt; wird jetzt beim Erstellen/Abgleichen ins Protokoll übernommen (`is_visible_snapshot`). |

Keine neue Tabelle, RLS unverändert (`protocol_element` hängt über `protocol` am Mandanten).

## Verhalten

- **Hinzufügen** (`POST /api/protocols/{id}/elements`): Element ohne `template_element_id`,
  `origin='protocol'`, ein Textblock (`configuration_snapshot_json.agenda_custom_block`), leerer
  `ProtocolText`. Alle `sort_index` werden in einer Transaktion (Zeilensperre auf `protocol`)
  neu durchnummeriert; «am Ende» heisst vor den Sitzungsnotizen.
- **Umbenennen** setzt `element_title_snapshot` und `section_name_snapshot` (der
  Verantwortlichen-Zusatz wird weiterhin live angehängt bzw. beim Abschliessen eingefroren). Die
  Sitzungsnotizen werden über ihren Namen gefunden und lassen sich darum nicht umbenennen (409).
- **Sortieren** (`PUT /api/protocols/{id}/element-order`): vollständige Liste plus
  `expected_element_ids`; weicht die Ausgangsreihenfolge oder die Menge ab → 409 `order_conflict`
  mit aktueller Reihenfolge.
- **Broadcast:** `agenda_changed` auf dem Protokoll-Kanal (`hocx:protocol:<id>:events`).
- **Vorlagen-Abgleich** (`sync-template`): Elemente mit `origin <> 'template'` werden nie gelöscht.
  Ohne eigene Reihenfolge gilt die der Vorlage, lokale Traktanden bleiben hinter ihrem bisherigen
  Vorgänger, Sitzungsnotizen am Ende. Mit eigener Reihenfolge bleibt sie, neue Vorlagen-Traktanden
  kommen hinter ihren Vorgänger in der Vorlage. Eigene Titel und eigene Sichtbarkeit bleiben; der
  Vorlagentitel wird in `template_title_snapshot` nachgeführt.
- **Folgeprotokoll:** entsteht aus der Vorlage (`create_from_template`), lokale Traktanden
  erscheinen dort nicht. Nach der Übernahme ist das Protokoll-Traktandum mit dem neuen
  Vorlagen-Traktandum verknüpft (`template_element_id`, Block `source_sort_index=10`), damit Abgleich
  und `copy_from_last_protocol` es finden.
- **Ausblenden ist kein Zugriffsschutz:** ausgeblendete Traktanden bleiben über API und Live-Kanal
  für alle Lesenden sichtbar (der Editor zeigt sie im Vorbereitungsmodus).
- **PDF/Abdeckung:** Elemente mit `is_visible_snapshot=false` fehlen im PDF; die PDF-Abdeckung
  meldet sie als `element_not_exported`. Lokale Traktanden erscheinen in Protokoll-Reihenfolge,
  auch in Einladung/Traktandenliste.
- **Suche/Statistik:** Die Protokollsuche läuft im Frontend über die geladenen Elemente; die
  Statistik wertet Blöcke (Anwesenheit, Pendenzen) ohne Vorlagenbezug aus. Keine Sonderfälle.
  Anliegen hängen an Vorlagen-Traktanden, lokale Traktanden haben keinen Anliegen-Slot.

## Abweichungen und Übernahme

`GET /api/protocols/{id}/template-changes` rechnet live gegen die aktuelle Vorlage und meldet nur,
was im Protokoll geändert wurde:

- `added`: `origin='protocol'` ohne Vorlagenbezug, mit Vorgänger aus der Vorlage;
- `renamed`: `template_title_snapshot` gesetzt und Vorlagentitel (mit Zyklus-Platzhaltern
  gerendert) ≠ Protokolltitel;
- `visibility`: `visibility_customized` und Sichtbarkeit ≠ `template_element.is_visible`;
- `order`: `agenda_order_customized` und die Reihenfolge der verknüpften Traktanden weicht ab.

`POST …/template-changes/apply` (`templates.edit` und `meetings.edit`, Vorlage lesbar, Rate-Limit
20/min; `meetings.edit`, weil die Übernahme das Protokoll-Traktandum verknüpft und die
Abweichungs-Merker zurücksetzt - nur Buchhaltungsspalten, kein Inhalt, auch im abgeschlossenen
Protokoll) übernimmt die
gewählten Keys in einer Transaktion unter Zeilensperre der Vorlage; der Trigger aus 0214 erhöht
die Vorlagenversion einmal. Geteilte oder Bibliotheks-Bausteine werden vor dem Umbenennen für diese
Vorlage kopiert (wie «nur in dieser Vorlage ändern»). Audit: `template.agenda_changes_applied`
(Keys, Protokoll, neue Version). War das Protokoll auf dem Stand der Vorlage, rückt
`protocol.template_version` mit. Veraltete Keys oder `expected_template_version` → 409
`changes_outdated`. Der Statuswechsel «abschliessen» ist davon unabhängig; die Übernahme geht
auch danach. Eingeschränkte Leser ohne Zuweisung der Vorlage bekommen eine leere Liste.
Abgleich, Hinzufügen, Sortieren und der Element-PATCH sperren die Protokollzeile; ein Umbenennen
kopiert den Baustein, wenn er in der Bibliothek liegt, mehrfach oder über alte
`template_element_block`-Verweise verwendet wird.

## Präsenz «wo ist wer»

WebSocket-Nachricht `focus` (Client → Server) mit `element_id`, `block_id`, `mode`. Der Server
prüft die UUIDs, stuft `editing` ohne `meetings.edit` zu `viewing` herab, drosselt je Verbindung
(`FocusThrottle`, 500 ms, die letzte Meldung gewinnt) und verteilt `presence_focus` auf dem
Protokoll-Kanal. Der Stand liegt in Redis (`hocx:presence-focus:<protocol_id>`, TTL wie die
Präsenz) und kommt im `snapshot` mit; beim Trennen folgt `presence_focus` mit Nullwerten.

## Bildunterschrift

`PATCH /api/protocol-images/{id}` (`meetings.edit`): Bild über Block/Protokoll im eigenen
Mandanten (sonst 404), Protokoll nicht abgeschlossen und Block nicht von einer anderen Person
gesperrt (409), höchstens 500 Zeichen. Broadcast der Bildliste unter `block-<id>-images`.

## Profileinstellungen

`protocol_accordion_enabled`/`protocol_wheel_enabled` sind aus Session und `CurrentUser`
entfernt. `PATCH /api/users/me` akzeptiert sie in 1.6 noch und ignoriert sie; in 1.7 entfernen
(`UserSelfUpdate`). Gespeicherte Werte in `external_identity_json` bleiben unbeachtet liegen.
