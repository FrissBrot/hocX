// Hausstil «Modern»: Inter, Hausfarbe in Überschriften und Tabellenkopf, nur horizontale Linien.
// Anpassung ausschliesslich über Daten (Document.style, siehe style_tokens.py), nie über Code.

#import "_tokens.typ": colors, space, radius

#let theme(doc) = {
  let primary = rgb(doc.style.primary_color)
  let secondary = rgb(doc.style.secondary_color)
  (
    key: "modern",
    primary: primary,
    secondary: secondary,
    fonts: doc.style.fonts + ("Inter", "Noto Sans", "Noto Color Emoji"),
    justify: false,
    heading: it => {
      let sizes = (1.45em, 1.18em, 1.02em, 1em)
      set text(size: sizes.at(it.level - 1, default: 1em), weight: "bold", fill: if it.level == 1 { primary } else { secondary })
      set block(above: if it.level == 1 { 1.6em } else { 1.2em }, below: 0.7em)
      if it.level == 1 {
        block(width: 100%, sticky: true, stroke: (bottom: 0.6pt + primary.lighten(55%)), inset: (bottom: 0.3em), it)
      } else {
        it
      }
    },
    table: (
      stroke: (x, y) => (bottom: 0.4pt + colors.border),
      header-fill: primary.lighten(88%),
      header-color: primary.darken(25%),
      header-size: 0.95em,
      group-fill: colors.neutral_bg,
      group-color: secondary.darken(20%),
      total-fill: primary.lighten(93%),
      zebra: none,
      rule: 0.8pt + primary,
      inset: (x: 5pt, y: 4.5pt),
      font-size: 0.92em,
    ),
    components: (:),
  )
}
