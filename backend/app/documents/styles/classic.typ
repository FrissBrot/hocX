// Hausstil «Klassisch»: Serifenschrift, Blocksatz, Tabellen mit vollem Raster, zurückhaltende
// Farben. Anpassung ausschliesslich über Daten (Document.style, siehe style_tokens.py).

#import "_tokens.typ": colors, space, radius

#let theme(doc) = {
  let primary = rgb(doc.style.primary_color)
  let secondary = rgb(doc.style.secondary_color)
  (
    key: "classic",
    primary: primary,
    secondary: secondary,
    fonts: doc.style.fonts + ("Liberation Serif", "Noto Sans", "Noto Color Emoji"),
    justify: true,
    heading: it => {
      let sizes = (1.35em, 1.12em, 1em, 1em)
      set text(size: sizes.at(it.level - 1, default: 1em), weight: "bold", style: if it.level >= 2 { "italic" } else { "normal" }, fill: if it.level == 1 { primary } else { colors.text })
      set block(above: if it.level == 1 { 1.8em } else { 1.3em }, below: 0.8em)
      if it.level == 1 {
        block(width: 100%, sticky: true, stroke: (bottom: 0.8pt + colors.text), inset: (bottom: 0.3em), it)
      } else {
        it
      }
    },
    table: (
      stroke: 0.5pt + colors.border_strong,
      header-fill: none,
      header-color: colors.text,
      header-size: 1em,
      group-fill: colors.neutral_bg,
      group-color: colors.text,
      total-fill: none,
      zebra: none,
      rule: 1pt + colors.text,
      inset: (x: 5pt, y: 4pt),
      font-size: 0.95em,
    ),
    components: (:),
  )
}
