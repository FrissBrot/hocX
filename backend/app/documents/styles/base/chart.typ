// Diagramme als Vektor in Hausfarben und Hausschrift (model.py: ChartBlock).
// Eigene kleine Komponenten statt eines externen Pakets (siehe dokument-engine.md).

#import "../lib/core.typ": colors, space, radius, tr, tone-color, series-color, format-value

#let chart-height = 5.2cm

#let series-label(ctx, series) = {
  if series.at("label_key", default: none) != none { tr(ctx, series.label_key) }
  else if series.at("label", default: none) != none { series.label }
  else { "" }
}

#let nice-max(value) = {
  if value <= 0 { return 1 }
  let exponent = calc.floor(calc.log(value, base: 10))
  let base = calc.pow(10.0, exponent)
  let fraction = value / base
  let nice = if fraction <= 1 { 1 } else if fraction <= 2 { 2 } else if fraction <= 2.5 { 2.5 } else if fraction <= 5 { 5 } else { 10 }
  nice * base
}

#let swatch(color) = box(baseline: -0.05em, rect(width: 0.75em, height: 0.75em, radius: 1pt, fill: color, stroke: none))

#let legend(entries) = {
  set text(size: 0.85em)
  block(above: 0.6em, entries.map(((color, label)) => box[#swatch(color) #h(0.3em) #label]).join(h(1.2em)))
}

#let series-colors(ctx, chart) = chart.series.enumerate().map(((index, series)) => series-color(ctx, series.at("tone", default: "primary"), index))

#let horizontal-bars(ctx, chart, stacked) = {
  let palette = series-colors(ctx, chart)
  let categories = chart.categories
  let totals = categories.enumerate().map(((index, _)) => {
    let values = chart.series.map(series => series.values.at(index, default: 0))
    if stacked { values.sum(default: 0) } else { calc.max(0, ..values) }
  })
  let maximum = calc.max(1e-9, ..totals)
  let bar-height = if stacked or chart.series.len() == 1 { 0.75em } else { 0.45em }
  let cells = ()
  for (index, category) in categories.enumerate() {
    cells.push(align(right + horizon, text(size: 0.85em)[#category]))
    let bars = if stacked {
      let segments = chart.series.enumerate().map(((series-index, series)) => {
        let value = series.values.at(index, default: 0)
        if value > 0 { box(width: value / maximum * 100%, height: bar-height, fill: palette.at(series-index)) }
      }).filter(segment => segment != none)
      box(width: 100%, segments.join())
    } else {
      stack(spacing: 1pt, ..chart.series.enumerate().map(((series-index, series)) => {
        let value = series.values.at(index, default: 0)
        box(width: calc.max(value, 0) / maximum * 100%, height: bar-height, fill: palette.at(series-index))
      }))
    }
    cells.push(align(horizon, bars))
    cells.push(align(left + horizon, text(size: 0.8em, fill: colors.muted)[#format-value(totals.at(index), chart.value_format)]))
  }
  grid(columns: (auto, 1fr, auto), column-gutter: 0.6em, row-gutter: 0.45em, ..cells)
  if chart.series.len() > 1 {
    legend(chart.series.enumerate().map(((index, series)) => (palette.at(index), series-label(ctx, series))))
  }
}

#let axis-area(ctx, maximum, chart, body) = {
  // Gitterlinien mit Achsenbeschriftung links, Inhalt im Rest
  let ticks = 4
  grid(
    columns: (auto, 1fr),
    column-gutter: 0.4em,
    box(height: chart-height, {
      for tick in range(ticks + 1) {
        let value = maximum / ticks * tick
        place(bottom + right, dy: -(tick / ticks) * chart-height + 0.35em, text(size: 0.7em, fill: colors.muted)[#format-value(value, chart.value_format)])
      }
    }),
    box(width: 100%, height: chart-height, {
      for tick in range(ticks + 1) {
        place(bottom + left, dy: -(tick / ticks) * chart-height, line(length: 100%, stroke: 0.4pt + colors.border))
      }
      body
    }),
  )
}

#let category-labels(chart) = {
  let count = chart.categories.len()
  let rotated = count > 8
  grid(
    columns: (auto, ..range(count).map(_ => 1fr)),
    column-gutter: 0.4em,
    [],
    ..chart.categories.map(category => align(center, text(size: 0.7em, fill: colors.muted, if rotated { rotate(-40deg, reflow: true)[#category] } else [#category]))),
  )
}

#let vertical-bars(ctx, chart, stacked) = {
  let palette = series-colors(ctx, chart)
  let count = chart.categories.len()
  let totals = range(count).map(index => {
    let values = chart.series.map(series => series.values.at(index, default: 0))
    if stacked { values.sum(default: 0) } else { calc.max(0, ..values) }
  })
  let maximum = nice-max(calc.max(0, ..totals))
  axis-area(ctx, maximum, chart, grid(
    columns: range(count).map(_ => 1fr),
    column-gutter: 0.4em,
    ..range(count).map(index => {
      let values = chart.series.map(series => calc.max(series.values.at(index, default: 0), 0))
      if stacked {
        align(bottom + center, stack(dir: btt, ..values.enumerate().map(((series-index, value)) => rect(width: 70%, height: value / maximum * chart-height, fill: palette.at(series-index), stroke: none))))
      } else {
        align(bottom + center, stack(dir: ltr, spacing: 1pt, ..values.enumerate().map(((series-index, value)) => rect(width: 70% / calc.max(values.len(), 1), height: value / maximum * chart-height, fill: palette.at(series-index), stroke: none))))
      }
    }),
  ))
  category-labels(chart)
  if chart.series.len() > 1 {
    legend(chart.series.enumerate().map(((index, series)) => (palette.at(index), series-label(ctx, series))))
  }
}

#let line-chart(ctx, chart) = {
  let palette = series-colors(ctx, chart)
  let count = chart.categories.len()
  let all-values = chart.series.map(series => series.values).flatten()
  let maximum = nice-max(calc.max(0, ..all-values))
  axis-area(ctx, maximum, chart, layout(size => {
    let step = size.width / calc.max(count, 1)
    for (series-index, series) in chart.series.enumerate() {
      let points = range(count).map(index => (step * (index + 0.5), chart-height - calc.max(series.values.at(index, default: 0), 0) / maximum * chart-height))
      if points.len() > 1 {
        place(top + left, curve(
          stroke: 1.6pt + palette.at(series-index),
          curve.move(points.first()),
          ..points.slice(1).map(point => curve.line(point)),
        ))
      }
      for point in points {
        place(top + left, dx: point.at(0) - 2.2pt, dy: point.at(1) - 2.2pt, circle(radius: 2.2pt, fill: palette.at(series-index), stroke: 0.8pt + white))
      }
    }
  }))
  category-labels(chart)
  legend(chart.series.enumerate().map(((index, series)) => (palette.at(index), series-label(ctx, series))))
}

#let donut(ctx, chart) = {
  let values = chart.series.at(0, default: (values: ())).values.map(value => calc.max(value, 0))
  let total = values.sum(default: 0)
  let tones = chart.at("category_tones", default: ())
  let palette = chart.categories.enumerate().map(((index, _)) => series-color(ctx, tones.at(index, default: "primary"), index))
  let outer = 2.2cm
  let inner = 1.25cm
  let wedges = {
    let start = -90deg
    for (index, value) in values.enumerate() {
      if value > 0 and total > 0 {
        let sweep = value / total * 360deg
        let steps = calc.max(2, int(sweep / 4deg))
        let outer-points = range(steps + 1).map(step => {
          let angle = start + sweep * step / steps
          (outer + outer * calc.cos(angle), outer + outer * calc.sin(angle))
        })
        let inner-points = range(steps + 1).rev().map(step => {
          let angle = start + sweep * step / steps
          (outer + inner * calc.cos(angle), outer + inner * calc.sin(angle))
        })
        place(top + left, polygon(fill: palette.at(index), stroke: 0.8pt + white, ..outer-points, ..inner-points))
        start += sweep
      }
    }
  }
  grid(
    columns: (auto, 1fr),
    column-gutter: 1.2em,
    align: horizon,
    box(width: outer * 2, height: outer * 2, {
      wedges
      place(center + horizon, text(weight: "bold", size: 1.1em)[#format-value(total, chart.value_format)])
    }),
    {
      set text(size: 0.9em)
      stack(spacing: 0.5em, ..chart.categories.enumerate().map(((index, category)) => {
        let value = values.at(index, default: 0)
        let share = if total > 0 { calc.round(value / total * 100) } else { 0 }
        box[#swatch(palette.at(index)) #h(0.3em) #category #h(0.4em) #text(fill: colors.muted)[#format-value(value, chart.value_format) (#share%)]]
      }))
    },
  )
}

#let render-chart(ctx, chart) = {
  if chart.kind == "donut" { donut(ctx, chart) }
  else if chart.kind == "line" { line-chart(ctx, chart) }
  else if chart.horizontal { horizontal-bars(ctx, chart, chart.kind == "stacked_bar") }
  else { vertical-bars(ctx, chart, chart.kind == "stacked_bar") }
}
