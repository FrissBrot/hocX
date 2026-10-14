// Seitenaufbau: Kopf-/Fussvarianten, Titelseiten, Inhaltsverzeichnis, Wasserzeichen und die
// Prüfvermerk (Echtheitsprüfung). Jede Variante funktioniert mit jeder anderen; ein
// Logo-Kopf ohne Logo fällt sichtbar auf den Standardkopf zurück.

#import "@preview/tiaoma:0.3.0": qrcode
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
  if variant == "logo_bar" and style.at("logo", default: none) == none { variant = "bar" }
  set text(size: 0.8em, fill: colors.muted)
  if variant == "none" { return }
  if variant == "minimal" {
    align(right, context counter(page).display())
  } else if variant == "bar" {
    grid(columns: (1fr, auto), text(weight: "bold", fill: ctx.theme.primary)[#meta.title], text(fill: ctx.theme.primary)[#meta.at("date", default: "")])
    v(-0.4em)
    line(length: 100%, stroke: 2pt + ctx.theme.primary)
  } else if variant == "logo" or variant == "logo_bar" {
    let bar = variant == "logo_bar"
    grid(columns: (auto, 1fr, auto), column-gutter: 1em, align: horizon,
      image("/" + style.logo, height: 0.9cm, fit: "contain"),
      align(center, if bar { text(weight: "bold", fill: ctx.theme.primary)[#meta.title] } else { text(style: "italic")[#meta.title] }),
      if bar { text(fill: ctx.theme.primary)[#meta.at("date", default: "")] } else { [#meta.at("date", default: "")] })
    v(-0.3em)
    line(length: 100%, stroke: if bar { 2pt + ctx.theme.primary } else { 0.4pt + colors.border_strong })
  } else {
    grid(columns: (1fr, auto), text(style: "italic")[#meta.title], [#meta.at("date", default: "")])
    v(-0.4em)
    line(length: 100%, stroke: 0.4pt + colors.border_strong)
  }
}

// ── Fuss ────────────────────────────────────────────────────────────────────

#let page-of(ctx) = context tr(ctx, "page.of", page: counter(page).get().first(), total: counter(page).final().first())

// ── Echtheitsprüfung ────────────────────────────────────────────────────────
// Drei Hausstil-Optionen (verify_show_url, verify_show_id, verify_show_qr). Der Text setzt sich nur
// aus eingeschalteten Teilen zusammen; Trennzeichen stehen nur zwischen vorhandenen Teilen. Sind
// alle drei aus, entfällt der Prüfvermerk vollständig.

#let verify-flags(ctx) = {
  let style = ctx.doc.style
  (
    url: style.at("verify_show_url", default: true) and not is-blank(ctx.doc.render.at("verify_display", default: none)),
    id: style.at("verify_show_id", default: true),
    qr: style.at("verify_show_qr", default: true),
  )
}

#let verify-short-id(ctx) = {
  if ctx.doc.render.at("preview", default: false) { tr(ctx, "verify.previewId") } else { ctx.doc.render.at("short_id", default: none) }
}

// Text der Prüfzeile oder none
#let verify-text(ctx) = {
  let flags = verify-flags(ctx)
  let id = verify-short-id(ctx)
  let url = ctx.doc.render.at("verify_display", default: none)
  let show-id = flags.id and not is-blank(id)
  if flags.url and show-id { tr(ctx, "verify.urlAndId", url: url, id: id) }
  else if flags.url { tr(ctx, "verify.url", url: url) }
  else if show-id { tr(ctx, "verify.id", id: id) }
  else { none }
}

// Die Zeile steht bei Modern/Klassisch in der Fusszeile jeder Seite, sonst im Prüfvermerk am Ende
#let verify-in-footer(ctx) = ctx.theme.at("verify-in-footer", default: true) and ctx.doc.style.footer != "none"

#let verify-footer-line(ctx) = {
  let value = verify-text(ctx)
  if verify-in-footer(ctx) and value != none {
    v(-0.2em)
    align(center, text(size: 0.85em)[#value])
  }
}

#let verify-qr(ctx, size) = {
  let render = ctx.doc.render
  let link-target = render.at("verify_link", default: none)
  if render.at("preview", default: false) or is-blank(link-target) {
    box(width: size, height: size, stroke: (paint: colors.border_strong, thickness: 0.6pt, dash: "dashed"), radius: 2pt,
      align(center + horizon, text(size: 0.6em, fill: colors.muted)[QR]))
  } else {
    link(link-target, qrcode(link-target, width: size, height: size))
  }
}

// Prüfvermerk am Ende des Inhalts, unten auf der letzten Seite (nicht umbrechbar)
#let verify-end(ctx) = {
  let flags = verify-flags(ctx)
  let value = if verify-in-footer(ctx) { none } else { verify-text(ctx) }
  if not flags.qr and value == none { return }
  v(1fr, weak: true)
  block(breakable: false, above: 1.2em, width: 100%, {
    set text(size: 0.8em, fill: colors.muted)
    if flags.qr {
      grid(columns: (auto, 1fr), column-gutter: 0.8em, align: horizon,
        verify-qr(ctx, 1.6cm),
        if value != none { value } else { tr(ctx, "verify.qrHint") })
    } else {
      align(center, value)
    }
  })
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
  verify-footer-line(ctx)
}

// ── Titelseiten ─────────────────────────────────────────────────────────────

#let sender-color(ctx) = {
  let value = ctx.doc.style.at("sender_color", default: none)
  if value == none { colors.muted } else { rgb(value) }
}

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

// Abstände je TOC-Variante: on, compact, very_compact (wie früher «TOC-Abstand»)
#let toc-spacing = (on: (size: 1em, above: 0.7em), compact: (size: 0.85em, above: 0.35em), very_compact: (size: 0.8em, above: 0.28em))

#let toc-outline(ctx, variant: "on") = {
  let depth = if ctx.doc.options.toc_block_titles { 3 } else { 1 }
  let spacing = toc-spacing.at(variant, default: toc-spacing.on)
  set text(size: spacing.size)
  show outline.entry: it => block(above: spacing.above, it)
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
    pad(left: 1.2cm, text(size: 0.9em, fill: sender-color(ctx))[#ctx.doc.style.sender])
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
  if ctx.doc.options.toc != "off" { toc-outline(ctx, variant: ctx.doc.options.toc) }
  v(1fr)
  if not is-blank(style.at("sender", default: none)) {
    align(center, text(size: 0.85em, fill: sender-color(ctx))[#style.sender])
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
  toc-outline(ctx, variant: variant)
  pagebreak(weak: true)
}

// Kasten mit Nummer, Datum, Status, Version und Ort am Anfang des Inhalts (Token show_metadata)
#let metadata-section(ctx) = {
  if not ctx.doc.options.at("show_metadata", default: false) { return }
  block(width: 100%, inset: 0.8em, radius: 3pt, stroke: 0.5pt + colors.border_strong, {
    text(weight: "bold", fill: ctx.theme.primary)[#tr(ctx, "metadata.title")]
    v(0.3em)
    title-facts(ctx)
  })
  // Fester Abstand: das «above» der folgenden Überschrift würde ein «below» hier überstimmen.
  v(1.2em)
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
