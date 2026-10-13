// Hausstil «Kompakt»: Liberation Sans, kleinere Abstände, Zebra-Tabellen mit vollfarbigem Kopf
// - für lange Listen. Anpassung ausschliesslich über Daten (Document.style, style_tokens.py).

#import "_tokens.typ": colors, space, radius

#let theme(doc) = {
  let primary = rgb(doc.style.primary_color)
  let secondary = rgb(doc.style.secondary_color)
  (
    key: "compact",
    primary: primary,
    secondary: secondary,
    fonts: doc.style.fonts + ("Liberation Sans", "Noto Sans", "Noto Color Emoji"),
    justify: false,
    heading: it => {
      let sizes = (1.22em, 1.06em, 1em, 1em)
      set text(size: sizes.at(it.level - 1, default: 1em), weight: "bold", fill: if it.level == 1 { primary } else { secondary })
      set block(above: if it.level == 1 { 1.1em } else { 0.9em }, below: 0.45em)
      it
    },
    table: (
      stroke: none,
      header-fill: primary,
      header-color: colors.on_solid,
      header-size: 0.95em,
      group-fill: secondary.lighten(80%),
      group-color: secondary.darken(30%),
      total-fill: colors.neutral_bg,
      zebra: colors.neutral_bg,
      rule: 0.8pt + primary,
      inset: (x: 3.5pt, y: 2.5pt),
      font-size: 0.88em,
    ),
    components: (:),
  )
}
