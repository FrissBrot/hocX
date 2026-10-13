// Seitenaufbau: Kopf-/Fussvarianten, Titelseiten, Inhaltsverzeichnis, Wasserzeichen und die
// Signaturzeile auf der letzten Seite. Jede Variante funktioniert mit jeder anderen; ein
// Logo-Kopf ohne Logo fällt sichtbar auf den Standardkopf zurück.

#import "../lib/core.typ": colors, space, radius, tr, is-blank

#let meta-line(ctx) = {
  let meta = ctx.doc.meta
  (meta.at("number", default: none), meta.at("date", default: none)).filter(value => not is-blank(value)).join(" · ")
}

#let status-label(ctx) = {
  let status = ctx.doc.meta.at("status", default: none)
  if is-blank(status) { none } else { tr(ctx, "protocolStatus." + status) }
}

#let version-label(ctx) = ctx.doc.meta.at("version", default: none)

// Wasserzeichen «Entwurf», solange ein Protokoll nicht abgeschlossen ist (abschaltbar).
#let watermark(ctx) = {
  if ctx.doc.options.watermark {
    place(center + horizon, rotate(-35deg, text(size: 96pt, weight: "bold", fill: colors.neutral_bg)[#tr(ctx, "watermark.draft")]))
  }
}

// ── Kopf ────────────────────────────────────────────────────────────────────

#let header-content(ctx) = {
  let style = ctx.doc.style
  let variant = style.header
  let meta = ctx.doc.meta
  if variant == "logo" and style.at("logo", default: none) == none { variant = "standard" }
  set text(size: 0.8em, fill: colors.muted)
  if variant == "none" { return }
  if variant == "minimal" {
    align(right, context counter(page).display())
  } else if variant == "bar" {
    grid(columns: (1fr, auto), text(weight: "bold", fill: ctx.theme.primary)[#meta.title], text(fill: ctx.theme.primary)[#meta.at("date", default: "")])
    v(-0.4em)
    line(length: 100%, stroke: 2pt + ctx.theme.primary)
  } else if variant == "logo" {
    grid(columns: (auto, 1fr, auto), column-gutter: 1em, align: horizon,
      image("/" + style.logo, height: 0.9cm, fit: "contain"),
      align(center, text(style: "italic")[#meta.title]),
      [#meta.at("date", default: "")])
    v(-0.3em)
    line(length: 100%, stroke: 0.4pt + colors.border_strong)
  } else {
    grid(columns: (1fr, auto), text(style: "italic")[#meta.title], [#meta.at("date", default: "")])
    v(-0.4em)
    line(length: 100%, stroke: 0.4pt + colors.border_strong)
  }
}

// ── Fuss ────────────────────────────────────────────────────────────────────

#let page-of(ctx) = context tr(ctx, "page.of", page: counter(page).get().first(), total: counter(page).final().first())

#let signature-line(ctx) = context {
  let render = ctx.doc.render
  let last = counter(page).final().first()
  if counter(page).get().first() == last {
    let id = render.at("document_id", default: none)
    let text-value = if render.at("preview", default: false) or id == none {
      tr(ctx, "signature.preview")
    } else if is-blank(version-label(ctx)) {
      tr(ctx, "signature.lineNoVersion", id: id)
    } else {
      tr(ctx, "signature.line", id: id, version: version-label(ctx))
    }
    if render.at("signed", default: false) or render.at("preview", default: false) {
      align(center, text(size: 0.75em, fill: colors.muted)[#text-value])
    }
  }
}

#let footer-content(ctx) = {
  let variant = ctx.doc.style.footer
  let meta = ctx.doc.meta
  set text(size: 0.8em, fill: colors.muted)
  let body = if variant == "none" {
    none
  } else if variant == "minimal" {
    align(center, page-of(ctx))
  } else if variant == "with_version" {
    grid(columns: (1fr, auto, 1fr), [#meta.at("number", default: "")], [#version-label(ctx)], align(right, page-of(ctx)))
  } else if variant == "date_page" {
    grid(columns: (1fr, auto), [#meta.at("date", default: "")], page-of(ctx))
  } else {
    grid(columns: (1fr, auto), [#meta.at("number", default: "")], page-of(ctx))
  }
  if body != none and variant != "minimal" {
    line(length: 100%, stroke: 0.4pt + colors.border)
    v(-0.5em)
  }
  body
  signature-line(ctx)
}

// ── Titelseiten ─────────────────────────────────────────────────────────────

#let title-facts(ctx) = {
  let meta = ctx.doc.meta
  let rows = ()
  if not is-blank(meta.at("number", default: none)) { rows.push((tr(ctx, "titlePage.number"), meta.number)) }
  if not is-blank(meta.at("date", default: none)) { rows.push((tr(ctx, "titlePage.date"), meta.date)) }
  if status-label(ctx) != none { rows.push((tr(ctx, "titlePage.status"), status-label(ctx))) }
  if not is-blank(version-label(ctx)) { rows.push((tr(ctx, "titlePage.version"), version-label(ctx))) }
  if not is-blank(ctx.doc.style.at("place", default: none)) { rows.push((tr(ctx, "titlePage.place"), ctx.doc.style.place)) }
  grid(columns: (auto, 1fr), column-gutter: 1.5em, row-gutter: 0.7em, ..rows.map(((label, value)) => (text(weight: "bold")[#label], [#value])).flatten())
}

#let toc-outline(ctx, compact: false) = {
  let depth = if ctx.doc.options.toc_block_titles { 3 } else { 1 }
  set text(size: if compact { 0.85em } else { 1em })
  show outline.entry: it => block(above: if compact { 0.35em } else { 0.7em }, it)
  outline(title: text(fill: ctx.theme.primary)[#tr(ctx, "toc.title")], depth: depth, indent: auto)
}

#let title-page-minimal(ctx) = {
  let meta = ctx.doc.meta
  v(3.5cm)
  align(center, {
    text(size: 2.4em, weight: "bold", fill: ctx.theme.primary)[#meta.title]
    if not is-blank(meta.at("subtitle", default: none)) { v(0.4em); text(size: 1.3em, fill: ctx.theme.secondary)[#meta.subtitle] }
    v(0.5cm)
    text(size: 1.3em, fill: ctx.theme.secondary)[#meta.at("number", default: "")]
    v(2cm)
    line(length: 5cm, stroke: 1.5pt + ctx.theme.primary)
    v(1cm)
    text(fill: ctx.theme.secondary)[#((meta.at("date", default: none), status-label(ctx), version-label(ctx)).filter(value => not is-blank(value)).join("  •  "))]
  })
}

#let title-page-modern(ctx) = {
  let meta = ctx.doc.meta
  block(width: 100%, fill: ctx.theme.primary, inset: (x: 1.2cm, y: 1.4cm), radius: radius.sm, {
    text(size: 2.2em, weight: "bold", fill: colors.on_solid)[#meta.title]
    if not is-blank(meta.at("subtitle", default: none)) or not is-blank(meta.at("number", default: none)) {
      v(0.4em)
      text(size: 1.15em, fill: colors.on_solid.transparentize(25%))[#((meta.at("subtitle", default: none), meta.at("number", default: none)).filter(value => not is-blank(value)).join(" · "))]
    }
  })
  v(2cm)
  pad(left: 1.2cm, title-facts(ctx))
  v(1fr)
  if not is-blank(ctx.doc.style.at("sender", default: none)) {
    pad(left: 1.2cm, text(size: 0.9em, fill: colors.muted)[#ctx.doc.style.sender])
    v(0.8cm)
  }
  line(length: 100%, stroke: 1pt + ctx.theme.primary)
  v(-0.6em)
  line(length: 100%, stroke: 0.4pt + ctx.theme.secondary)
}

#let title-page-bold(ctx) = {
  let meta = ctx.doc.meta
  set text(fill: colors.on_solid)
  v(1fr)
  align(center, {
    text(size: 2.8em, weight: "bold")[#meta.title]
    v(0.8cm)
    text(size: 1.4em)[#meta.at("number", default: "")]
    v(2cm)
    line(length: 6cm, stroke: 0.6pt + colors.on_solid)
    v(1.2cm)
    [#meta.at("date", default: "")]
    if status-label(ctx) != none { v(0.4cm); text(size: 0.9em)[#status-label(ctx)] }
    if not is-blank(version-label(ctx)) { v(0.2cm); text(size: 0.9em)[#version-label(ctx)] }
  })
  v(1fr)
}

#let title-page-cover(ctx) = {
  let style = ctx.doc.style
  let meta = ctx.doc.meta
  if style.at("logo", default: none) != none {
    align(center, image("/" + style.logo, height: 3cm, fit: "contain"))
    v(0.8cm)
  }
  align(center, {
    text(size: 2.2em, weight: "bold", fill: ctx.theme.primary)[#meta.title]
    linebreak()
    text(size: 1.1em, fill: ctx.theme.secondary)[#((meta.at("number", default: none), meta.at("date", default: none), if not is-blank(style.at("place", default: none)) { style.place }).filter(value => not is-blank(value)).join(" · "))]
  })
  v(1cm)
  if ctx.doc.options.toc != "off" { toc-outline(ctx, compact: ctx.doc.options.toc == "compact") }
  v(1fr)
  if not is-blank(style.at("sender", default: none)) {
    align(center, text(size: 0.85em, fill: colors.muted)[#style.sender])
  }
}

#let title-page(ctx) = {
  let variant = ctx.doc.options.title_page
  if variant == "none" { return }
  let override = ctx.theme.at("title-pages", default: (:)).at(variant, default: none)
  let style = ctx.doc.style
  let footer-image = style.at("footer_image", default: none)
  let body = if override != none { override(ctx) }
    else if variant == "minimal" { title-page-minimal(ctx) }
    else if variant == "bold" { title-page-bold(ctx) }
    else if variant == "cover" { title-page-cover(ctx) }
    else { title-page-modern(ctx) }
  // Nur abweichende Seitenparameter setzen; alles andere (Fuss, Wasserzeichen) bleibt wie im
  // Dokument eingestellt.
  let args = (header: none)
  if variant == "bold" { args.insert("fill", ctx.theme.primary) }
  if variant == "cover" and footer-image != none {
    args.insert("footer", none)
    args.insert("background", { watermark(ctx); place(bottom, image("/" + footer-image, width: 100%)) })
  }
  page(..args, body)
}

#let toc-section(ctx) = {
  let variant = ctx.doc.options.toc
  if variant == "off" or ctx.doc.options.title_page == "cover" { return }
  toc-outline(ctx, compact: variant == "compact")
  pagebreak(weak: true)
}

// ── Seite ───────────────────────────────────────────────────────────────────

#let margins = (narrow: 1.5cm, normal: 2.2cm, wide: 3cm)
#let leadings = (tight: 0.5em, normal: 0.65em, relaxed: 0.85em)

#let setup-page(ctx, body) = {
  let style = ctx.doc.style
  let theme = ctx.theme
  set document(title: ctx.doc.meta.title, author: if is-blank(ctx.doc.meta.tenant_name) { "hocX" } else { ctx.doc.meta.tenant_name })
  set page(
    paper: "a4",
    flipped: ctx.doc.options.orientation == "landscape",
    margin: margins.at(style.margins, default: 2.2cm),
    header: header-content(ctx),
    footer: footer-content(ctx),
    background: watermark(ctx),
  )
  set text(font: theme.fonts, size: style.base_size * 1pt, lang: ctx.doc.meta.language, hyphenate: true, fill: colors.text)
  set par(justify: theme.justify, leading: leadings.at(style.line_spacing, default: 0.65em))
  set heading(numbering: if ctx.doc.options.numbering { "1.1" } else { none })
  show heading: theme.heading
  show link: it => it
  body
}
