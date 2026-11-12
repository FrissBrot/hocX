# Anliegen

Unter *Arbeiten → Anliegen* sammelt der Verein Punkte, die an einer kommenden Sitzung besprochen
werden sollen. Ein Anliegen erscheint automatisch im passenden Protokoll unter dem gewählten
Traktandum. Die Vorlage braucht dafür keinen eigenen Block.

## Erfassen

*Anliegen erfassen* öffnet das Popup:

1. **Titel** und **Text** (gleicher Editor wie im Protokoll).
2. **Protokollvorlage**: Das Popup wählt die zuletzt verwendete Vorlage vor (gespeichert je Person).
3. **Traktandum**: ein Punkt der Vorlage, oder *Ohne Traktandum* (Vorgabe, solange keiner
   gewählt ist). Dann steht das Anliegen im Protokoll unter «Weitere Anliegen».
4. **Termin** (siehe [unten](#termin)):
   - *Nächste Sitzung*: im nächsten Protokoll dieser Vorlage, das noch *geplant* oder
     *vorbereitet* ist und ab heute datiert.
   - *Monat*: erst im nächsten solchen Protokoll ab dem Ersten des gewählten Monats.

Die Liste zeigt, wer das Anliegen erfasst hat (nicht änderbar) und in welchem Protokoll es steht.
Steht noch kein passendes Protokoll an, zeigt sie «Noch kein Protokoll». Das Anliegen erscheint
dann, sobald ein solches Protokoll erstellt wird.

## Termin {#termin}

- *Nächste Sitzung*: das Anliegen erscheint im frühesten Protokoll derselben Vorlage, das noch
  *geplant* oder *vorbereitet* ist und ab heute datiert. «Heute» richtet sich nach Schweizer Zeit.
- *Monat*: das Anliegen wartet bis zum Ersten des gewählten Monats und erscheint dann im nächsten
  solchen Protokoll. Ein Monat in der Vergangenheit gilt als «ab heute».

## Bearbeiten und vertagen {#vertagen}

Solange ein Anliegen noch auf sein Protokoll wartet, lassen sich Vorlage, Traktandum und Termin
im Popup ändern. Steht es schon fest in einem Protokoll (nach dem Erfassen im Editor oder nach dem
Durchführen), sind diese Felder gesperrt: der Hinweis im Popup nennt das Protokoll. Zum
Verschieben dient **Vertagen** (Knopf direkt im Popup oder im Aktionsmenü): das Anliegen löst sich
vom Protokoll, bekommt einen neuen Termin und erscheint im nächsten passenden Protokoll danach.
Titel und Text bleiben jederzeit änderbar, bis das Protokoll abgeschlossen ist.

## Im Protokoll

- Anliegen stehen unter ihrem Traktandum. Titel und Text lassen sich dort direkt ändern; die
  Änderung gilt für das Anliegen selbst. Wer es erfasst hat, zeigt der Editor nicht.
- Über das Aktionsmenü lässt sich ein Anliegen **vertagen** (neuer Termin: nächste Sitzung oder
  Monat) oder **löschen**. Ein vertagtes Anliegen verschwindet aus dem Protokoll und erscheint
  in einem späteren. Der Hinweis «n × vertagt» zählt mit.
- Im Mini-Menü des Editors (während der Sitzung, Status *vorbereitet*) erfasst *Anliegen
  erfassen* ein Anliegen direkt im aktuellen Protokoll. Es steht standardmässig unter dem gerade
  gewählten Traktandum.
- Sobald das Protokoll auf *durchgeführt* wechselt, gehören die angezeigten Anliegen fest zu
  diesem Protokoll und gelten in der Liste als *behandelt*. Nach dem Abschluss sind sie
  schreibgeschützt.
- Im PDF des Protokolls stehen die Anliegen unter ihrem Traktandum (Titel fett, darunter der Text).

Lesende sehen die Anliegen, ändern können sie Schreibende und Admins.
