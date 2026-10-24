// Einstieg jedes Compiles. Liest /document.json (vom Layout-Compiler erzeugt, siehe
// compiler.py) und setzt Seiten, Seitenvorlagen (Kopf, Fuss, Hintergrund), Titelseite und die
// Inhaltssegmente. Gestaltung kommt ausschliesslich aus den Daten (Brand-Profil, Vorlage).

#import "theme.typ": make-ctx
#import "layout.typ": render-node, render-nodes, verify-block

#let doc = json("/document.json")
#let ctx = make-ctx(doc)
#let brand = doc.brand
#let t = brand.typography

#let mm-list(values) = (top: values.at(0) * 1mm, right: values.at(1) * 1mm, bottom: values.at(2) * 1mm, left: values.at(3) * 1mm)

#let master-of(id) = {
  let key = if id == none { doc.settings.default_master } else { id }
  doc.masters.at(key, default: doc.masters.at(doc.settings.default_master, default: (header: none, footer: none, background: ())))
}

// Kopf/Fuss einer Seitenvorlage; die erste Inhaltsseite kann eine eigene Vorlage haben.
#let slot-content(master, first, slot) = context {
  let use-first = first != none and here().page() == locate(<hocx-content-start>).page()
  let source = if use-first { first } else { master }
  let node = source.at(slot, default: none)
  if node != none { render-node(ctx, node) }
}

#let background-content(master, first, draft-watermark) = context {
  let use-first = first != none and here().page() == locate(<hocx-content-start>).page()
  let source = if use-first { first } else { master }
  for node in source.at("background", default: ()) { render-node(ctx, node) }
}

#let page-args(master-id, first-id: none) = {
  let master = master-of(master-id)
  let first = if first-id != none and first-id != master-id { master-of(first-id) } else { none }
  let width = doc.page.width * 1mm
  let height = doc.page.height * 1mm
  let orientation = master.at("orientation", default: none)
  if orientation == "landscape" and width < height { (width, height) = (height, width) }
  if orientation == "portrait" and width > height { (width, height) = (height, width) }
  let margins = master.at("margins", default: doc.page.margins)
  (
    width: width,
    height: height,
    margin: mm-list(margins),
    columns: doc.page.columns,
    header: slot-content(master, first, "header"),
    footer: slot-content(master, first, "footer"),
    background: background-content(master, first, none),
  )
}

#set document(title: doc.meta.title, author: if doc.meta.tenant_name == "" { "hocX" } else { doc.meta.tenant_name })
#set text(
  font: brand.fonts.body,
  size: t.base_size * 1pt,
  weight: t.weight_body,
  lang: doc.meta.language,
  hyphenate: doc.settings.hyphenate,
  fill: ctx.c.text,
)
#set par(justify: doc.settings.justify, leading: calc.max(t.line_height - 0.7, 0.1) * 1em, spacing: brand.layout.paragraph_gap * 1mm + 0.4em)
#set columns(gutter: doc.page.column_gap * 1mm)
#set heading(numbering: if doc.settings.numbering { "1.1" } else { none })
#show heading: ctx.theme.heading
#show link: it => it

// Titelseite (eigene Seite, zählt nicht zur Seitennummerierung des Inhalts)
#if doc.title_page != none {
  let tp = doc.title_page
  let args = if tp.master != none { page-args(tp.master) } else { page-args(none) + (header: none, footer: none, background: none) }
  if tp.background != none { args.insert("fill", rgb(tp.background)) }
  page(..args, render-nodes(ctx, tp.children))
  counter(page).update(1)
}

#for (index, segment) in doc.segments.enumerate() {
  let first-id = if index == 0 { doc.settings.first_page_master } else { none }
  let last = index == doc.segments.len() - 1
  page(..page-args(segment.master, first-id: first-id), {
    if index == 0 { [#metadata("start") <hocx-content-start>] }
    render-nodes(ctx, segment.nodes)
    // Prüfvermerk am Ende, falls die Vorlage keinen eigenen enthält (unten auf der letzten Seite)
    if last and doc.verify.auto {
      v(1fr, weak: true)
      block(breakable: false, above: 1.2em, width: 100%, verify-block(ctx, doc.verify.show_url, doc.verify.show_id, doc.verify.show_qr))
    }
  })
}
