// Darstellung des kompilierten Layoutbaums (compiler.py → document.json).
//
// Jeder Knoten ist ein Dictionary mit Typ "t", ID, kompiliertem Stil "s" und typabhängigen
// Feldern. Texte stehen als Spans ({v, b, i} / {br}) im JSON und werden nur als Inhalt
// eingesetzt ([#span.v]) - es gibt keine Auswertung von Benutzerinhalt (kein eval).

#import "@preview/tiaoma:0.3.0": qrcode
#import "lib/core.typ": tr, is-blank
#import "base/blocks.typ": render-block
#import "theme.typ": with-appearance
#import "base/rich.typ": render-rich

// ── Längen und Stil ─────────────────────────────────────────────────────────

#let length-of(l, default: auto) = {
  if l == none { default }
  else if l.k == "auto" { auto }
  else if l.k == "fill" { 100% }
  else if l.k == "mm" { l.v * 1mm }
  else if l.k == "pct" { l.v * 1% }
  else { 100% }
}

// Spaltenbreite in Zeilen/Rastern: fill und fr teilen den Rest auf
#let track-of(l) = {
  if l == none or l.k == "auto" { auto }
  else if l.k == "fill" { 1fr }
  else if l.k == "fr" { l.v * 1fr }
  else if l.k == "mm" { l.v * 1mm }
  else if l.k == "pct" { l.v * 1% }
  else { auto }
}

#let h-align(value) = if value == "center" { center } else if value == "right" { right } else { left }

#let apply-text(ctx, t, body) = {
  if t == none { return body }
  let args = (:)
  if "font" in t and t.font != none { args.insert("font", t.font) }
  if "size" in t { args.insert("size", t.size * 1pt) }
  if "weight" in t { args.insert("weight", t.weight) }
  if "italic" in t { args.insert("style", if t.italic { "italic" } else { "normal" }) }
  if "color" in t and t.color != none { args.insert("fill", rgb(t.color)) }
  if "tracking" in t { args.insert("tracking", t.tracking * 1pt) }
  let content = body
  if "transform" in t { content = if t.transform == "upper" { upper(body) } else { lower(body) } }
  set text(..args)
  if "leading" in t { set par(leading: t.leading * 1em) }
  if "align" in t {
    if t.align == "justify" {
      set par(justify: true)
      content
    } else {
      align(h-align(t.align), content)
    }
  } else {
    content
  }
}

#let border-stroke(b) = {
  if b == none { return none }
  let line = (paint: rgb(b.c), thickness: b.w * 1pt, dash: if b.style == "dashed" { "dashed" } else if b.style == "dotted" { "dotted" } else { none })
  let result = (:)
  for side in b.sides { result.insert(side, line) }
  result
}

// Kasten-Stil (Breite, Höhe, Innenabstand, Hintergrund, Rahmen, Ausrichtung, Aussenabstand)
#let styled(ctx, n, body, breakable: true) = {
  let s = n.at("s", default: (:))
  let content = apply-text(ctx, s.at("text", default: none), body)
  let keep = n.at("keep", default: false)
  let has-box = "pad" in s or "bg" in s or "border" in s or "w" in s or "h" in s
  if has-box {
    // Ausrichtung des Kastens gilt nicht für seinen Inhalt (dafür gibt es die Textausrichtung)
    if "align" in s and not ("text" in s and "align" in s.text) { content = align(left, content) }
    let pad = s.at("pad", default: (0, 0, 0, 0))
    let border = s.at("border", default: none)
    content = block(
      width: length-of(s.at("w", default: none), default: auto),
      height: length-of(s.at("h", default: none), default: auto),
      inset: (top: pad.at(0) * 1mm, right: pad.at(1) * 1mm, bottom: pad.at(2) * 1mm, left: pad.at(3) * 1mm),
      fill: if s.at("bg", default: none) != none { rgb(s.bg) } else { none },
      stroke: border-stroke(border),
      radius: if border != none { border.r * 1mm } else { 0pt },
      breakable: breakable and not keep,
      above: 0pt,
      below: 0pt,
      content,
    )
  } else if keep {
    content = block(breakable: false, above: 0pt, below: 0pt, content)
  }
  if "align" in s { content = align(h-align(s.align), content) }
  if n.at("break", default: false) { pagebreak(weak: true) }
  if s.at("mt", default: 0) > 0 { v(s.mt * 1mm, weak: true) }
  content
  if s.at("mb", default: 0) > 0 { v(s.mb * 1mm, weak: true) }
}

// ── Text ────────────────────────────────────────────────────────────────────

#let render-spans(spans) = {
  for span in spans {
    if span.at("br", default: false) {
      linebreak()
    } else {
      let body = [#span.v]
      if span.at("b", default: false) { body = text(weight: "bold", body) }
      if span.at("i", default: false) { body = text(style: "italic", body) }
      body
    }
  }
}

// Rollen-Standards (aus dem Brand-Profil); eigene Textstile des Knotens haben Vorrang.
#let text-role(ctx, n) = {
  let t = ctx.brand.typography
  let role = n.role
  let body = render-spans(n.spans)
  if role == "heading" { return heading(level: n.level, outlined: true, body) }
  if role == "paragraph" { return par(body) }
  let defaults = if role == "title" {
    (font: ctx.theme.heading-fonts, size: t.size_title * 1pt, weight: t.weight_heading, fill: rgb(ctx.brand.colors.heading))
  } else if role == "subtitle" {
    (font: ctx.theme.heading-fonts, size: t.size_subtitle * 1pt, fill: ctx.theme.secondary)
  } else if role == "caption" {
    (size: t.size_small * 1pt, style: "italic", fill: ctx.c.muted)
  } else if role == "label" {
    (size: t.size_small * 1pt, weight: "bold", fill: ctx.c.muted)
  } else {
    (size: t.size_small * 1pt)
  }
  let own = n.at("s", default: (:)).at("text", default: (:))
  if "font" in own and own.font != none { defaults.insert("font", own.font) }
  if "size" in own { defaults.insert("size", own.size * 1pt) }
  if "weight" in own { defaults.insert("weight", own.weight) }
  if "italic" in own { defaults.insert("style", if own.italic { "italic" } else { "normal" }) }
  if "color" in own and own.color != none { defaults.insert("fill", rgb(own.color)) }
  let content = text(..defaults, body)
  if role == "title" { block(above: 0pt, below: 0.4em, content) }
  else if role == "subtitle" { block(above: 0pt, below: 0.6em, content) }
  else { content }
}

// ── Prüfvermerk, Seitenzahl ─────────────────────────────────────────────────

#let page-of(ctx, format) = context {
  let current = counter(page).get().first()
  if format == "page" { str(current) } else { tr(ctx, "page.of", page: current, total: counter(page).final().first()) }
}

#let verify-text(ctx, show-url, show-id) = {
  let render = ctx.doc.render
  let id = if render.at("preview", default: false) { tr(ctx, "verify.previewId") } else { render.at("short_id", default: none) }
  let url = render.at("verify_display", default: none)
  let has-url = show-url and not is-blank(url)
  let has-id = show-id and not is-blank(id)
  if has-url and has-id { tr(ctx, "verify.urlAndId", url: url, id: id) }
  else if has-url { tr(ctx, "verify.url", url: url) }
  else if has-id { tr(ctx, "verify.id", id: id) }
  else { none }
}

#let qr-box(ctx, target, size) = {
  if is-blank(target) {
    box(width: size, height: size, stroke: (paint: ctx.c.border_strong, thickness: 0.6pt, dash: "dashed"), radius: 2pt,
      align(center + horizon, text(size: 0.6em, fill: ctx.c.muted)[QR]))
  } else {
    link(target, qrcode(target, width: size, height: size))
  }
}

#let verify-qr(ctx, size) = {
  let render = ctx.doc.render
  qr-box(ctx, if render.at("preview", default: false) { none } else { render.at("verify_link", default: none) }, size)
}

#let verify-block(ctx, show-url, show-id, show-qr) = {
  let value = verify-text(ctx, show-url, show-id)
  if not show-qr and value == none { return }
  set text(size: 0.8em, fill: ctx.c.muted)
  if show-qr {
    grid(columns: (auto, 1fr), column-gutter: 0.8em, align: horizon,
      verify-qr(ctx, 1.6cm),
      if value != none { value } else { tr(ctx, "verify.qrHint") })
  } else {
    value
  }
}

// ── Knoten ──────────────────────────────────────────────────────────────────

#let render-node(ctx, n) = {
  let t = n.t
  if t == "stack" or t == "container" {
    let gap = n.at("gap", default: 3) * 1mm
    styled(ctx, n, breakable: n.at("breakable", default: true), {
      for (index, child) in n.children.enumerate() {
        if index > 0 { v(gap, weak: true) }
        render-node(ctx, child)
      }
    })
  } else if t == "section" {
    let gap = n.at("gap", default: 3) * 1mm
    styled(ctx, n, {
      if n.title.len() > 0 { heading(level: n.level, outlined: n.outlined, render-spans(n.title)) }
      for (index, child) in n.children.enumerate() {
        if index > 0 { v(gap, weak: true) }
        render-node(ctx, child)
      }
    })
  } else if t == "row" {
    if n.children.len() == 0 { return }
    let tracks = n.children.map(child => track-of(child.at("s", default: (:)).at("w", default: none)))
    let valign = if n.valign == "middle" { horizon } else if n.valign == "bottom" { bottom } else { top }
    styled(ctx, n, grid(columns: tracks, column-gutter: n.gap * 1mm, align: valign, ..n.children.map(child => render-node(ctx, child))))
  } else if t == "grid" {
    if n.children.len() == 0 { return }
    let widths = n.widths.map(track-of)
    let columns = if widths.len() == n.columns { widths } else { range(n.columns).map(_ => 1fr) }
    styled(ctx, n, grid(columns: columns, column-gutter: n.gap_x * 1mm, row-gutter: n.gap_y * 1mm, ..n.children.map(child => render-node(ctx, child))))
  } else if t == "text" {
    styled(ctx, n, text-role(ctx, n))
  } else if t == "rich" {
    styled(ctx, n, render-rich(n.content, ctx))
  } else if t == "image" {
    let s = n.at("s", default: (:))
    let width = length-of(s.at("w", default: none), default: auto)
    let height = length-of(s.at("h", default: none), default: auto)
    let body = if n.path == none {
      box(width: if width == auto { 40mm } else { width }, height: if height == auto { 20mm } else { height },
        stroke: (paint: ctx.c.border_strong, thickness: 0.6pt, dash: "dashed"), radius: 2pt,
        align(center + horizon, text(size: 0.7em, fill: ctx.c.muted)[#tr(ctx, "label.imageMissing")]))
    } else {
      image("/" + n.path, width: width, height: height, fit: n.fit)
    }
    let caption = if n.caption.len() > 0 { [#v(0.3em) #text(size: 0.85em, fill: ctx.c.muted, render-spans(n.caption))] } else { none }
    let inner = s
    let _ = inner.remove("w", default: none)
    let _ = inner.remove("h", default: none)
    styled(ctx, (s: inner, keep: true, "break": n.at("break", default: false)), { body; caption })
  } else if t == "divider" {
    let dash = if n.line_style == "dashed" { "dashed" } else if n.line_style == "dotted" { "dotted" } else { none }
    styled(ctx, n, block(above: 0.4em, below: 0.4em, line(length: length-of(n.length, default: 100%), stroke: (paint: rgb(n.color), thickness: n.thickness * 1pt, dash: dash))))
  } else if t == "spacer" {
    if n.flexible { v(1fr) } else { v(n.size * 1mm) }
  } else if t == "pagebreak" {
    pagebreak(weak: true)
  } else if t == "page_number" {
    styled(ctx, n, page-of(ctx, n.format))
  } else if t == "toc" {
    let spacing = (normal: (size: 1em, above: 0.7em), compact: (size: 0.85em, above: 0.35em), very_compact: (size: 0.8em, above: 0.28em)).at(n.density)
    styled(ctx, n, {
      set text(size: spacing.size)
      show outline.entry: it => block(above: spacing.above, it)
      outline(title: if n.show_title { text(fill: ctx.theme.primary)[#tr(ctx, "toc.title")] } else { none }, depth: n.depth, indent: auto)
    })
  } else if t == "metadata" {
    styled(ctx, n, {
      if n.layout == "inline" {
        n.rows.map(row => [#text(weight: "bold")[#row.at(0):] #row.at(1)]).join([ #h(0.4em)·#h(0.4em) ])
      } else {
        grid(columns: (auto, 1fr), column-gutter: 1.5em, row-gutter: 0.6em,
          ..n.rows.map(row => (text(weight: "bold")[#row.at(0)], [#row.at(1)])).flatten())
      }
    })
  } else if t == "verify" {
    styled(ctx, n, block(breakable: false, verify-block(ctx, n.show_url, n.show_id, n.show_qr)))
  } else if t == "qr" {
    styled(ctx, n, block(breakable: false, {
      qr-box(ctx, n.link, n.size * 1mm)
      if n.caption.len() > 0 { v(0.3em); text(size: 0.8em, fill: ctx.c.muted, render-spans(n.caption)) }
    }))
  } else if t == "list" {
    let items = n.items.map(spans => render-spans(spans))
    styled(ctx, n, if n.marker == "number" { enum(..items) } else if n.marker == "none" { list(marker: none, ..items) } else { list(..items) })
  } else if t == "table" {
    let style = ctx.theme.table
    let count = n.columns.len()
    let tracks = n.columns.map(column => track-of(column.w))
    if tracks.all(track => track == auto) { tracks.at(0) = 1fr }
    let aligns = n.columns.map(column => h-align(column.align))
    let cells = ()
    for (index, row) in n.rows.enumerate() {
      let fill = if n.zebra and calc.odd(index) { rgb(ctx.brand.colors.table_zebra) } else { none }
      for (column, spans) in row.enumerate() {
        if column < count { cells.push(table.cell(fill: fill, align: aligns.at(column), render-spans(spans))) }
      }
    }
    let header = if n.show_header {
      (table.header(repeat: n.repeat_header, ..n.columns.enumerate().map(((index, column)) => table.cell(
        fill: style.header-fill, align: aligns.at(index),
        text(weight: "bold", fill: style.header-color, size: style.header-size, render-spans(column.header))))),)
    } else { () }
    styled(ctx, n, {
      if n.rows.len() == 0 and n.at("empty", default: none) != none {
        text(fill: ctx.c.muted, style: "italic")[#n.empty]
      } else {
        set text(size: style.font-size)
        table(columns: tracks, inset: style.inset, stroke: style.stroke, ..header, ..cells)
      }
    })
  } else if t == "data" {
    // Fachkomponenten bleiben auf oberster Ebene (Seitenumbrüche, wiederholte Tabellenköpfe)
    let block-ctx = with-appearance(ctx, n.at("appearance", default: none))
    styled(ctx, n, { for b in n.blocks { render-block(block-ctx, b) } })
  } else if t == "layer" {
    let body = {
      for child in n.children {
        let frame = child.at("frame", default: (x: 0, y: 0, w: none, h: none, rotate: 0))
        let inner = render-node(ctx, child)
        let sized = block(width: if frame.w != none { frame.w * 1mm } else { auto }, height: if frame.h != none { frame.h * 1mm } else { auto }, inner)
        let turned = if frame.rotate != 0 { rotate(frame.rotate * 1deg, reflow: false, sized) } else { sized }
        place(top + left, dx: (frame.x + n.offset.at(0)) * 1mm, dy: (frame.y + n.offset.at(1)) * 1mm, turned)
      }
    }
    if n.anchor == "page" { body } else { styled(ctx, n, block(width: 100%, height: n.height * 1mm, breakable: false, body)) }
  } else if t == "watermark" {
    if n.path != none {
      place(center + horizon, rotate(n.angle * 1deg, image("/" + n.path, width: 60%)))
    } else {
      place(center + horizon, rotate(n.angle * 1deg, text(size: n.size * 1pt, weight: "bold", fill: rgb(n.color))[#n.text]))
    }
  } else if t == "error" {
    if ctx.doc.flags.at("diagnostics", default: false) {
      block(width: 100%, inset: 0.5em, radius: 2pt, stroke: (paint: ctx.c.danger, thickness: 0.8pt, dash: "dashed"),
        text(size: 0.8em, fill: ctx.c.danger)[#tr(ctx, "error.node", label: n.label) (#tr(ctx, "diagnostic." + n.code))])
    }
  }
}

#let render-nodes(ctx, nodes) = {
  for node in nodes { render-node(ctx, node) }
}
