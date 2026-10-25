// Basis-Komponenten der Fachkomponenten: eine pro Block-Typ (model.py). Farben, Schriften und
// Tabellenstil kommen aus dem Brand-Profil (ctx.c, ctx.theme); jeder Block-Typ ist so in jeder
// Vorlage verwendbar. Eingebettet werden sie über data_block-Knoten (layout.typ).
// Darstellungsvarianten (Grundstil, Brand- und Block-Übersteuerung) liefert look(ctx, art).

#import "../lib/core.typ": colors, space, radius, tr, is-blank, tone-color, status-dot, tag-chip, empty-note
#import "rich.typ": render-rich
#import "table.typ": data-table
#import "chart.typ": render-chart
#import "../theme.typ": look, with-appearance

// Hervorgehobene Fläche (Varianten «box»/«tiles»/«filled»)
#let surface-box(ctx, radius, body, accent: false) = block(
  width: 100%,
  inset: space.s3,
  radius: radius * 1mm,
  fill: ctx.theme.primary.lighten(90%),
  stroke: if accent { (left: 3pt + ctx.theme.primary) } else { none },
  body,
)

// ── Struktur ────────────────────────────────────────────────────────────────

#let richtext-block(ctx, b) = render-rich(b.content, ctx)

#let static-text-block(ctx, b) = render-rich(b.content, ctx)

// ── Protokoll ───────────────────────────────────────────────────────────────

#let session-date-block(ctx, b) = {
  let label = if is-blank(b.at("label", default: none)) { tr(ctx, "label.nextSession") } else { b.label }
  let value = if is-blank(b.at("date", default: none)) { tr(ctx, "label.open") } else { b.date }
  let style = look(ctx, "session_date", default: "line")
  if style.variant == "box" {
    block(above: space.s2, below: space.s2, breakable: false, surface-box(ctx, style.radius, accent: style.radius == 0, {
      text(size: 0.8em, weight: "bold", fill: ctx.theme.primary)[#upper(label)]
      linebreak()
      text(size: 1.25em, weight: "bold")[#value]
    }))
  } else {
    block(above: space.s2, below: space.s2)[#text(weight: "bold")[#label:] #value]
  }
}

#let session-notes-block(ctx, b) = render-rich(b.content, ctx)

#let form-block(ctx, b) = {
  let has-header = not is-blank(b.at("label_heading", default: none)) or not is-blank(b.at("value_heading", default: none))
  if look(ctx, "form", default: "grid").variant == "table" {
    let style = ctx.theme.table
    let header = if has-header {
      (table.header(..(b.at("label_heading", default: ""), b.at("value_heading", default: "")).map(label => table.cell(fill: style.header-fill, text(weight: "bold", fill: style.header-color)[#label]))),)
    } else { () }
    set text(size: style.font-size)
    return table(columns: (auto, 1fr), inset: style.inset, stroke: style.stroke, ..header,
      ..b.rows.map(row => (text(fill: ctx.c.muted)[#row.label], render-rich(row.value, ctx, compact: true))).flatten())
  }
  let cells = ()
  if has-header {
    cells.push(text(weight: "bold")[#b.at("label_heading", default: "")])
    cells.push(text(weight: "bold")[#b.at("value_heading", default: "")])
  }
  for row in b.rows {
    cells.push(text(fill: ctx.c.muted)[#row.label])
    cells.push(render-rich(row.value, ctx, compact: true))
  }
  grid(columns: (auto, 1fr), column-gutter: 1.2em, row-gutter: 0.55em, ..cells)
}

#let bullet-list-block(ctx, b) = list(..b.items.filter(item => item.trim() != "").map(item => [#item]))

#let matrix-block(ctx, b) = {
  for table-data in b.tables {
    data-table(ctx, table-data)
    v(space.s3, weak: true)
  }
}

#let entry-exit-block(ctx, b) = {
  let group(key, items) = {
    if items.len() > 0 {
      block(above: space.s3, below: space.s2, sticky: true, text(weight: "bold")[#tr(ctx, key)])
      list(..items.map(item => [#item.name#if not is-blank(item.at("date", default: none)) [ (#item.date)]]))
    }
  }
  group("label.joins", b.joins)
  group("label.leaves", b.leaves)
}

#let image-figure(ctx, image-ref, max-width: 82%) = {
  if image-ref.at("missing", default: false) {
    block(inset: space.s3, stroke: 0.5pt + ctx.c.border, radius: radius.xs, text(fill: ctx.c.muted)[#tr(ctx, "label.imageMissing")#if not is-blank(image-ref.at("caption", default: none)) [: #image-ref.caption]])
  } else {
    let width = if image-ref.at("width_pt", default: none) != none { calc.min(image-ref.width_pt, 1000) * 1pt } else { auto }
    figure(
      block(width: max-width, align(center, image("/" + image-ref.path, width: if width == auto { 100% } else { calc.min(width / 1pt, 1000) * 1pt }, fit: "contain"))),
      caption: if is-blank(image-ref.at("caption", default: none)) { none } else { [#image-ref.caption] },
      kind: image,
      supplement: none,
      numbering: none,
    )
  }
}

#let image-block(ctx, b) = image-figure(ctx, b.image)

#let image-gallery-block(ctx, b) = {
  if b.columns <= 1 {
    for image-ref in b.images { image-figure(ctx, image-ref) }
  } else {
    grid(columns: range(b.columns).map(_ => 1fr), column-gutter: space.s4, row-gutter: space.s4,
      ..b.images.map(image-ref => image-figure(ctx, image-ref, max-width: 100%)))
  }
}

// ── Personen ────────────────────────────────────────────────────────────────

#let attendance-counts(ctx, b) = {
  let counts = (present: 0, late: 0, excused: 0, absent: 0)
  for entry in b.entries {
    let status = entry.at("status", default: none)
    if status != none { counts.insert(status, counts.at(status) + 1) }
  }
  counts
}

// Kompakt: eine Zeile pro Status («Anwesend (3): A, B, C»)
#let attendance-compact(ctx, b) = {
  let groups = ("present", "late", "excused", "absent").map(status => (status, b.entries.filter(entry => entry.at("status", default: none) == status)))
  let open = b.entries.filter(entry => entry.at("status", default: none) == none)
  for (status, entries) in groups {
    if entries.len() > 0 {
      block(above: space.s2, below: space.s2)[#status-dot(ctx, "attendanceStatus." + status) (#entries.len()): #entries.map(entry => entry.name).join(", ")]
    }
  }
  if open.len() > 0 {
    block(above: space.s2, below: space.s2, text(fill: ctx.c.muted)[– (#open.len()): #open.map(entry => entry.name).join(", ")])
  }
}

#let attendance-table(ctx, b) = {
  let style = ctx.theme.table
  set text(size: style.font-size)
  table(columns: (1fr, auto), inset: style.inset, stroke: style.stroke,
    table.header(repeat: true, ..(tr(ctx, "col.name"), tr(ctx, "col.status")).map(label => table.cell(fill: style.header-fill, text(weight: "bold", fill: style.header-color)[#label]))),
    ..b.entries.map(entry => {
      let status = entry.at("status", default: none)
      ([#entry.name], if status == none { text(fill: ctx.c.muted)[–] } else { status-dot(ctx, "attendanceStatus." + status) })
    }).flatten())
}

#let attendance-block(ctx, b) = {
  let variant = look(ctx, "attendance", default: "list").variant
  if variant == "compact" or variant == "table" {
    if variant == "compact" { attendance-compact(ctx, b) } else { attendance-table(ctx, b) }
    if b.show_counts {
      let counts = attendance-counts(ctx, b)
      block(above: space.s3, text(size: 0.9em, fill: ctx.theme.secondary)[#tr(ctx, "label.attendanceCounts", present: counts.present, late: counts.late, excused: counts.excused, absent: counts.absent)])
    }
    return
  }
  let cells = ()
  let counts = (present: 0, late: 0, excused: 0, absent: 0)
  for entry in b.entries {
    cells.push([#entry.name])
    let status = entry.at("status", default: none)
    if status != none {
      counts.insert(status, counts.at(status) + 1)
      cells.push(status-dot(ctx, "attendanceStatus." + status))
    } else {
      cells.push(text(fill: ctx.c.muted)[–])
    }
  }
  grid(columns: (auto, 1fr), column-gutter: 2.5em, row-gutter: 0.45em, ..cells)
  if b.show_counts {
    block(above: space.s3, text(size: 0.9em, fill: ctx.theme.secondary)[#tr(ctx, "label.attendanceCounts", present: counts.present, late: counts.late, excused: counts.excused, absent: counts.absent)])
  }
}

#let attendance-matrix-block(ctx, b) = {
  let style = ctx.theme.table
  let short(status) = if status == none { text(fill: ctx.c.muted)[·] } else {
    text(weight: "bold", fill: tone-color(ctx, ("present": "success", "late": "info", "excused": "warning", "absent": "danger").at(status)))[#tr(ctx, "attendanceShort." + status)]
  }
  let has-rates = b.rates.len() > 0
  let columns = (auto, ..b.sessions.map(_ => 1fr), ..if has-rates { (auto,) } else { () })
  let header = (
    text(weight: "bold", fill: style.header-color)[#tr(ctx, "col.name")],
    ..b.sessions.map(session => align(center, text(size: 0.8em, weight: "bold", fill: style.header-color)[#session])),
    ..if has-rates { (align(right, text(weight: "bold", fill: style.header-color)[#tr(ctx, "col.rate")]),) } else { () },
  )
  let cells = ()
  for (index, person) in b.people.enumerate() {
    cells.push([#person])
    for status in b.cells.at(index, default: ()) { cells.push(align(center, short(status))) }
    for _ in range(b.cells.at(index, default: ()).len(), b.sessions.len()) { cells.push([]) }
    if has-rates { cells.push(align(right)[#b.rates.at(index, default: "")]) }
  }
  set text(size: style.font-size)
  table(columns: columns, inset: style.inset, stroke: style.stroke,
    table.header(repeat: true, ..header.map(cell => table.cell(fill: style.header-fill, cell))),
    ..cells)
  block(above: space.s2, text(size: 0.8em, fill: ctx.c.muted)[#tr(ctx, "label.legend"): #("present", "late", "excused", "absent").map(status => [#tr(ctx, "attendanceShort." + status) = #tr(ctx, "attendanceStatus." + status)]).join(", ")])
}

#let member-list-block(ctx, b) = data-table(ctx, b.table)

#let signature-line(ctx, label, name) = {
  block(breakable: false, above: space.s6, {
    v(1.4cm)
    line(length: 100%, stroke: 0.6pt + ctx.c.text)
    text(size: 0.85em, fill: ctx.c.muted)[#if is-blank(label) { tr(ctx, "label.signature") } else { label }#if not is-blank(name) [ · #name]]
  })
}

#let signature-fields-block(ctx, b) = {
  let fields = b.fields
  grid(columns: (1fr, 1fr), column-gutter: space.s6, row-gutter: space.s4,
    ..if b.with_place_date { (signature-line(ctx, tr(ctx, "label.placeDate"), none),) } else { () },
    ..fields.map(field => signature-line(ctx, field.at("label", default: none), field.at("name", default: none))),
  )
}

#let attendance-sheet-block(ctx, b) = {
  let style = ctx.theme.table
  let extra = if b.columns.len() > 0 { b.columns } else { (tr(ctx, "col.signature"),) }
  let header = (tr(ctx, "col.name"), ..extra).map(label => table.cell(fill: style.header-fill, text(weight: "bold", fill: style.header-color)[#label]))
  let rows = ()
  for name in b.names {
    rows.push([#name])
    for _ in extra { rows.push(box(height: 1.6em)) }
  }
  for _ in range(b.blank_rows) {
    rows.push(box(height: 1.6em))
    for _ in extra { rows.push([]) }
  }
  set text(size: style.font-size)
  table(columns: (auto, ..extra.map(_ => 1fr)), inset: style.inset, stroke: 0.5pt + ctx.c.border_strong,
    table.header(repeat: true, ..header), ..rows)
}

// ── Aufgaben, Termine, Listen ───────────────────────────────────────────────

#let table-block(ctx, b) = data-table(ctx, b.table)

#let calendar-month(ctx, month) = {
  let style = ctx.theme.table
  block(breakable: false, above: space.s4, {
    text(weight: "bold", size: 1.1em, fill: ctx.theme.primary)[#tr(ctx, "month." + str(month.month)) #month.year]
    v(space.s2)
    let cells = range(7).map(day => table.cell(fill: style.header-fill, align(center, text(size: 0.8em, weight: "bold", fill: style.header-color)[#tr(ctx, "weekday." + str(day))])))
    for _ in range(month.first_weekday) { cells.push(table.cell(fill: ctx.c.neutral_bg)[]) }
    for day in range(1, month.days + 1) {
      let events = month.events.at(str(day), default: ())
      cells.push(box(width: 100%, height: 1.7cm, clip: true, {
        text(size: 0.75em, fill: ctx.c.muted, weight: "bold")[#day]
        for event in events {
          let color = if event.at("color", default: none) != none { rgb(event.color) } else { ctx.theme.primary }
          block(above: 2pt, below: 0pt, width: 100%, inset: (x: 2pt, y: 1pt), radius: 1.5pt, fill: if event.muted { ctx.c.neutral_bg } else { color.lighten(80%) },
            text(size: 0.65em, fill: if event.muted { ctx.c.muted } else { color.darken(40%) }, if event.cancelled { strike[#event.title] } else [#event.title]))
        }
      }))
    }
    let trailing = calc.rem(7 - calc.rem(month.first_weekday + month.days, 7), 7)
    for _ in range(trailing) { cells.push(table.cell(fill: ctx.c.neutral_bg)[]) }
    table(columns: range(7).map(_ => 1fr), inset: 3pt, stroke: 0.5pt + ctx.c.border, ..cells)
  })
}

#let event-calendar-month-block(ctx, b) = {
  // Jeder Monat ist unteilbar und rutscht als Ganzes auf die nächste Seite, wenn er nicht passt.
  for month in b.months { calendar-month(ctx, month) }
}

#let event-agenda-block(ctx, b) = {
  for month in b.months {
    if month.items.len() > 0 {
      block(above: space.s4, below: space.s2, sticky: true, text(weight: "bold", fill: ctx.theme.primary)[#tr(ctx, "month." + str(month.month)) #month.year])
      grid(columns: (auto, 1fr), column-gutter: 1em, row-gutter: 0.45em,
        ..month.items.map(item => {
          let color = if item.muted { ctx.c.muted } else { ctx.c.text }
          (
            text(fill: color, weight: "bold")[#item.date],
            text(fill: color, {
              if item.cancelled { strike[#item.title] } else [#item.title]
              if item.cancelled [ (#tr(ctx, "label.cancelled"))]
              if not is-blank(item.at("detail", default: none)) { text(fill: ctx.c.muted)[ · #item.detail] }
              if item.tags.len() > 0 { h(0.4em); item.tags.map(tag => tag-chip(ctx, tag)).join(h(0.2em)) }
            }),
          )
        }).flatten())
    }
  }
}

// ── Finanzen ────────────────────────────────────────────────────────────────

#let finance-balance-block(ctx, b) = {
  let style = look(ctx, "finance_balance", default: "list")
  if style.variant == "tiles" {
    let count = calc.min(calc.max(b.balances.len(), 1), 3)
    return grid(columns: range(count).map(_ => 1fr), column-gutter: space.s3, row-gutter: space.s3,
      ..b.balances.map(line => surface-box(ctx, style.radius, {
        text(size: 0.8em, fill: ctx.c.muted)[#line.name]
        linebreak()
        text(size: 1.4em, weight: "bold", fill: if line.negative { ctx.c.danger } else { ctx.theme.primary })[#line.amount #line.currency]
        if not is-blank(line.at("as_of", default: none)) { linebreak(); text(size: 0.75em, fill: ctx.c.muted)[#tr(ctx, "label.asOf", date: line.as_of)] }
      })))
  }
  grid(columns: (1fr, auto), column-gutter: 1.2em, row-gutter: 0.5em,
    ..b.balances.map(line => (
      [#line.name#if not is-blank(line.at("as_of", default: none)) { text(size: 0.85em, fill: ctx.c.muted)[ · #tr(ctx, "label.asOf", date: line.as_of)] }],
      align(right, text(weight: "bold", fill: if line.negative { ctx.c.danger } else { ctx.c.text })[#line.amount #line.currency]),
    )).flatten())
}

// ── Statistik ───────────────────────────────────────────────────────────────

#let kpi-tiles-block(ctx, b) = {
  let count = calc.min(calc.max(b.tiles.len(), 1), 4)
  let style = look(ctx, "kpi_tiles", default: "outlined")
  let filled = style.variant == "filled"
  grid(columns: range(count).map(_ => 1fr), column-gutter: space.s3, row-gutter: space.s3,
    ..b.tiles.map(tile => block(width: 100%, inset: space.s3, radius: style.radius * 1mm, stroke: if filled { none } else { 0.6pt + ctx.c.border }, fill: if filled { ctx.theme.primary.lighten(90%) } else { ctx.c.panel }, {
      text(size: 0.8em, fill: ctx.c.muted)[#if tile.at("label_key", default: none) != none { tr(ctx, tile.label_key) } else { tile.at("label", default: "") }]
      linebreak()
      text(size: 1.6em, weight: "bold", fill: if tile.tone == "default" { ctx.theme.primary } else { tone-color(ctx, tile.tone) })[#tile.value]
      if not is-blank(tile.at("hint", default: none)) { linebreak(); text(size: 0.75em, fill: ctx.c.muted)[#tile.hint] }
    })))
}

#let chart-block(ctx, b) = render-chart(ctx, b)

// ── Sonstiges ───────────────────────────────────────────────────────────────

// ── Verteiler ───────────────────────────────────────────────────────────────

#let base-components = (
  richtext: richtext-block,
  static_text: static-text-block,
  session_date: session-date-block,
  session_notes: session-notes-block,
  form: form-block,
  bullet_list: bullet-list-block,
  matrix: matrix-block,
  entry_exit: entry-exit-block,
  image: image-block,
  image_gallery: image-gallery-block,
  attendance: attendance-block,
  attendance_matrix: attendance-matrix-block,
  member_list: member-list-block,
  signature_fields: signature-fields-block,
  attendance_sheet: attendance-sheet-block,
  todo_table: table-block,
  event_table: table-block,
  event_calendar_month: event-calendar-month-block,
  event_agenda: event-agenda-block,
  list_table: table-block,
  finance_balance: finance-balance-block,
  finance_transactions: table-block,
  fines: table-block,
  kpi_tiles: kpi-tiles-block,
  chart: chart-block,
  stat_table: table-block,
)

#let block-title(ctx, b) = {
  let title = b.at("title", default: none)
  if is-blank(title) and b.at("title_key", default: none) != none { title = tr(ctx, b.title_key) }
  if not is-blank(title) and b.type != "heading" {
    heading(level: b.level, outlined: true)[#title]
  }
}

#let render-block(ctx, b) = {
  // Darstellung eines einzelnen Bausteins (Sitzungsvorlage), bereits aufgelöst
  let ctx = if b.at("appearance", default: none) != none { with-appearance(ctx, b.appearance) } else { ctx }
  if b.type == "protocol_element" {
    block-title(ctx, b)
    if not is-blank(b.at("responsible", default: none)) {
      block(above: 0pt, below: space.s3, text(size: 0.85em, fill: ctx.c.muted)[#tr(ctx, "label.responsible"): #b.responsible])
    }
    if b.empty or b.children.len() == 0 {
      empty-note(ctx, b.type)
    } else {
      for child in b.children { render-block(ctx, child) }
    }
  } else {
    block-title(ctx, b)
    if b.empty {
      empty-note(ctx, b.type)
    } else {
      let component = ctx.theme.components.at(b.type, default: base-components.at(b.type))
      // Kein umschliessender block(): Seitenumbrüche und seitenübergreifende Tabellen müssen
      // auf oberster Ebene bleiben.
      v(space.s2, weak: true)
      component(ctx, b)
      v(space.s4, weak: true)
    }
  }
}

#let render-blocks(ctx, blocks) = {
  for item in blocks { render-block(ctx, item) }
}
