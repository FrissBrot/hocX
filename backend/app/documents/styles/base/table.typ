// Gemeinsame Tabellenkomponente für alle Tabellen-Blöcke (model.py: TableData).
//
// Regeln: bricht über Seiten um und wiederholt die Kopfzeile, Spaltenbreiten passen sich dem
// Inhalt an (eine Spalte nimmt die Restbreite), Beträge rechtsbündig, Status als übersetztes
// Label mit farbigem Punkt. Die Optik (Linien, Kopf, Zebra, Innenabstand) kommt aus
// ctx.theme.table, damit jeder Hausstil sie anpassen kann.

#import "../lib/core.typ": colors, space, radius, tr, tone-color, status-dot, tag-chip
#import "rich.typ": render-rich

#let column-width(column, index, flexible-index) = {
  if column.width == "fill" { 1fr }
  else if column.width == "wide" { 2fr }
  else if index == flexible-index { 1fr }
  else { auto }
}

// Ohne ausdrücklich breite Spalte bekommt die Spalte mit dem meisten Text die Restbreite.
// So läuft eine Tabelle nie über den Rand, auch wenn eine Zelle sehr lang ist.
#let widest-text-column(tbl) = {
  let totals = tbl.columns.map(_ => 0)
  for group in tbl.groups {
    for row in group.rows {
      for (index, cell) in row.cells.enumerate() {
        if index < totals.len() {
          totals.at(index) += cell.at("v", default: "").len()
        }
      }
    }
  }
  let best = 0
  for (index, total) in totals.enumerate() {
    if total > totals.at(best) { best = index }
  }
  best
}

#let column-align(column) = {
  if column.align == "right" { right } else if column.align == "center" { center } else { left }
}

#let header-label(ctx, column) = {
  if column.at("label_key", default: none) != none { tr(ctx, column.label_key) }
  else if column.at("label", default: none) != none { column.label }
  else { "" }
}

#let render-cell(ctx, cell) = {
  let kind = cell.at("k", default: "text")
  let body = if kind == "status" and cell.at("status", default: none) != none {
    status-dot(ctx, cell.status)
    if cell.at("v", default: "") != "" { text(fill: colors.muted)[ (#cell.v)] }
  } else if kind == "tags" {
    cell.tags.map(tag => tag-chip(ctx, tag)).join(h(0.25em))
  } else if kind == "rich" {
    render-rich(cell.rich, ctx, compact: true)
  } else if kind == "check" {
    box(width: 0.85em, height: 0.85em, stroke: 0.6pt + colors.text, radius: 1pt, if cell.at("checked", default: false) { align(center + horizon, text(size: 0.7em)[✓]) })
  } else if kind == "blank" {
    box(width: 100%, height: 1.8em)
  } else {
    let value = cell.at("v", default: "")
    let note = cell.at("note_key", default: none)
    if note == none { [#value] }
    else if value == "" { tr(ctx, note) }
    else { [#value (#tr(ctx, note))] }
  }
  if cell.at("strike", default: false) { body = strike(body) }
  let tone = cell.at("tone", default: "default")
  if tone != "default" { body = text(fill: tone-color(ctx, tone), body) }
  body
}

#let group-label(ctx, group) = {
  if group.at("label_key", default: none) != none { tr(ctx, group.label_key) }
  else if group.at("label", default: none) != none { group.label }
  else { none }
}

#let data-table(ctx, tbl) = {
  let style = ctx.theme.table
  let columns = tbl.columns
  let count = columns.len()
  if count == 0 { return }
  let has-flexible = columns.any(column => column.width == "fill" or column.width == "wide")
  let flexible-index = if has-flexible { -1 } else { widest-text-column(tbl) }
  let widths = columns.enumerate().map(((index, column)) => column-width(column, index, flexible-index))
  let aligns = columns.map(column-align)

  let cells = ()
  let fills = ()
  let body-row = 0

  for group in tbl.groups {
    let label = group-label(ctx, group)
    if label != none {
      cells.push(table.cell(colspan: count, fill: style.group-fill, inset: style.inset, text(weight: "bold", fill: style.group-color)[#label]))
    }
    for row in group.rows {
      let row-fill = if style.zebra != none and calc.odd(body-row) { style.zebra } else { none }
      body-row += 1
      for (index, cell) in row.cells.enumerate() {
        let content = render-cell(ctx, cell)
        if row.at("muted", default: false) { content = text(fill: colors.muted, content) }
        if row.at("strong", default: false) { content = text(weight: "bold", content) }
        cells.push(table.cell(fill: row-fill, align: aligns.at(index, default: left), content))
      }
      // Fehlende Zellen auffüllen, damit eine kurze Zeile das Raster nie verschiebt.
      for _ in range(row.cells.len(), count) { cells.push([]) }
    }
    if group.at("subtotal", default: none) != none {
      for (index, cell) in group.subtotal.enumerate() {
        cells.push(table.cell(fill: style.total-fill, align: aligns.at(index, default: left), text(weight: "bold", render-cell(ctx, cell))))
      }
      for _ in range(group.subtotal.len(), count) { cells.push(table.cell(fill: style.total-fill)[]) }
    }
  }
  if tbl.at("totals", default: none) != none {
    for (index, cell) in tbl.totals.enumerate() {
      cells.push(table.cell(fill: style.total-fill, stroke: (top: style.rule), align: aligns.at(index, default: left), text(weight: "bold", render-cell(ctx, cell))))
    }
    for _ in range(tbl.totals.len(), count) { cells.push(table.cell(fill: style.total-fill, stroke: (top: style.rule))[]) }
  }

  let header = if tbl.at("show_header", default: true) {
    (table.header(
      repeat: true,
      ..columns.enumerate().map(((index, column)) => table.cell(
        fill: style.header-fill,
        align: aligns.at(index),
        text(weight: "bold", fill: style.header-color, size: style.header-size)[#header-label(ctx, column)],
      )),
    ),)
  } else { () }

  set text(size: style.font-size)
  table(
    columns: widths,
    inset: style.inset,
    stroke: style.stroke,
    ..header,
    ..cells,
  )
}
