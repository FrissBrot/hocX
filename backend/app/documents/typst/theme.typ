// Darstellungswerte aus dem Brand-Profil (document.json → brand, siehe brand_service.resolve_brand).
// Kein Code aus Benutzerdaten: Farben sind geprüfte Hex-Werte, Schriften geprüfte Familiennamen.

#import "_tokens.typ": colors

#let hex(value, fallback) = if value == none { fallback } else { rgb(value) }

// Palette für alle Komponenten (ctx.c). Brand-Farben überschreiben die neutralen Grundwerte.
#let palette(brand) = {
  let b = brand.colors
  (
    text: rgb(b.text),
    muted: rgb(b.muted),
    border: rgb(b.border).lighten(35%),
    border_strong: rgb(b.border),
    bg: rgb(b.background),
    panel: rgb(b.background),
    surface: rgb(b.surface),
    accent: rgb(b.accent),
    accent_strong: rgb(b.accent).darken(15%),
    accent_soft: rgb(b.accent).lighten(88%),
    success: rgb(b.success),
    warning: rgb(b.warning),
    danger: rgb(b.danger),
    info: rgb(b.info),
    success_bg: rgb(b.success).lighten(85%),
    success_fg: rgb(b.success).darken(15%),
    warning_bg: rgb(b.warning).lighten(85%),
    warning_fg: rgb(b.warning).darken(15%),
    danger_bg: rgb(b.danger).lighten(85%),
    danger_fg: rgb(b.danger).darken(15%),
    neutral_bg: rgb(b.surface),
    neutral_fg: rgb(b.muted),
    on_solid: colors.on_solid,
    watermark: rgb(b.watermark),
    chart_1: colors.chart_1,
    chart_2: colors.chart_2,
    chart_3: colors.chart_3,
    chart_4: colors.chart_4,
    chart_5: colors.chart_5,
  )
}

#let heading-rule(brand, c) = {
  let t = brand.typography
  let style = brand.layout.heading_style
  let primary = rgb(brand.colors.primary)
  let heading-color = rgb(brand.colors.heading)
  let secondary = rgb(brand.colors.secondary)
  let gap = brand.layout.section_gap * 1mm
  it => {
    let sizes = (t.size_h1 * 1pt, t.size_h2 * 1pt, t.size_h3 * 1pt, t.base_size * 1pt)
    let body = if t.heading_transform == "upper" { upper(it) } else { it }
    set text(
      font: brand.fonts.heading,
      size: sizes.at(it.level - 1, default: t.base_size * 1pt),
      weight: t.weight_heading,
      tracking: t.letter_spacing_heading * 1pt,
      fill: if it.level == 1 { heading-color } else { secondary.darken(10%) },
    )
    set block(above: if it.level == 1 { gap * 1.4 } else { gap }, below: 0.65em, sticky: true)
    if it.level > 1 or style == "plain" {
      block(body)
    } else if style == "underline" {
      block(width: 100%, stroke: (bottom: 0.6pt + primary.lighten(55%)), inset: (bottom: 0.3em), body)
    } else if style == "bar" {
      block(width: 100%, stroke: (left: 3pt + primary), inset: (left: 0.5em, y: 0.15em), body)
    } else {
      block(width: 100%, fill: primary.lighten(88%), inset: (x: 0.5em, y: 0.35em), radius: brand.layout.radius * 1mm, body)
    }
  }
}

#let table-style(brand, c) = {
  let style = brand.layout.table_style
  let header-bg = rgb(brand.colors.table_header_background)
  let header-fg = rgb(brand.colors.table_header_text)
  let primary = rgb(brand.colors.primary)
  let line = brand.layout.border_width * 1pt
  let base = (
    header-fill: header-bg,
    header-color: header-fg,
    header-size: 0.95em,
    group-fill: c.neutral_bg,
    group-color: rgb(brand.colors.secondary).darken(20%),
    total-fill: header-bg.lighten(40%),
    zebra: none,
    rule: (line * 1.6) + primary,
    inset: (x: 5pt, y: 4.5pt),
    font-size: 0.92em,
  )
  if style == "grid" {
    base + (stroke: line + c.border_strong)
  } else if style == "zebra" {
    base + (stroke: none, header-fill: primary, header-color: c.on_solid, zebra: rgb(brand.colors.table_zebra), inset: (x: 5pt, y: 4pt))
  } else if style == "minimal" {
    base + (stroke: (x, y) => if y == 0 { (bottom: line + c.border_strong) } else { none }, header-fill: none, header-color: c.text, total-fill: none)
  } else {
    base + (stroke: (x, y) => (bottom: (line * 0.8) + c.border))
  }
}

#let make-theme(brand, c) = (
  primary: rgb(brand.colors.primary),
  secondary: rgb(brand.colors.secondary),
  fonts: brand.fonts.body,
  heading-fonts: brand.fonts.heading,
  heading: heading-rule(brand, c),
  table: table-style(brand, c),
  components: (:),
)

#let make-ctx(doc) = {
  let c = palette(doc.brand)
  (doc: doc, strings: doc.strings, brand: doc.brand, c: c, theme: make-theme(doc.brand, c))
}
