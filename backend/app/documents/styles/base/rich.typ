// Rich-Text-Baum (model.py: RichBlock/RichInline) → Typst-Inhalt.
// Jeder String wird als Text eingesetzt; es gibt keine Auswertung von Benutzerinhalt.

#import "../lib/core.typ": colors, space, radius

#let render-inline(nodes) = {
  for node in nodes {
    if node.t == "br" {
      linebreak()
    } else {
      let body = if node.at("code", default: false) {
        box(fill: colors.neutral_bg, inset: (x: 2pt), outset: (y: 2pt), radius: 2pt, text(font: "DejaVu Sans Mono", size: 0.9em)[#node.v])
      } else {
        [#node.v]
      }
      if node.at("b", default: false) { body = text(weight: "bold", body) }
      if node.at("i", default: false) { body = text(style: "italic", body) }
      if node.at("s", default: false) { body = strike(body) }
      let href = node.at("href", default: none)
      if href != none {
        body = link(href, text(fill: colors.accent_strong, underline(body)))
      }
      body
    }
  }
}

#let render-rich(nodes, ctx, compact: false) = {
  let gap = if compact { 0.35em } else { 0.65em }
  for node in nodes {
    if node.t == "p" {
      block(above: gap, below: gap, render-inline(node.c))
    } else if node.t == "h" {
      let size = (1.2em, 1.1em, 1em).at(node.level - 1, default: 1em)
      block(above: gap * 1.4, below: gap, sticky: true, text(weight: "bold", size: size, render-inline(node.c)))
    } else if node.t == "ul" {
      list(spacing: gap, ..node.items.map(item => render-rich(item, ctx, compact: true)))
    } else if node.t == "ol" {
      enum(start: node.start, spacing: gap, ..node.items.map(item => render-rich(item, ctx, compact: true)))
    } else if node.t == "quote" {
      block(
        above: gap,
        below: gap,
        inset: (left: 0.8em, y: 0.2em),
        stroke: (left: 2pt + colors.border_strong),
        text(fill: colors.muted, render-rich(node.c, ctx, compact: compact)),
      )
    } else if node.t == "code" {
      block(
        above: gap,
        below: gap,
        width: 100%,
        inset: 0.6em,
        radius: radius.xs,
        fill: colors.neutral_bg,
        text(font: "DejaVu Sans Mono", size: 0.85em)[#node.v],
      )
    } else if node.t == "table" {
      let width = calc.max(1, ..node.rows.map(row => row.len()), if node.at("header", default: none) != none { node.header.len() } else { 0 })
      let cells = ()
      if node.at("header", default: none) != none {
        cells += node.header.map(value => text(weight: "bold")[#value])
      }
      for row in node.rows {
        for index in range(width) {
          cells.push([#row.at(index, default: "")])
        }
      }
      block(above: gap, below: gap, table(
        columns: width,
        stroke: none,
        inset: (x: 0pt, y: 2pt),
        column-gutter: 1em,
        ..cells,
      ))
    }
  }
}
