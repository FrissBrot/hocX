// Gemeinsame Hilfsfunktionen aller Hausstile.
//
// Kein Code in diesem Verzeichnis wertet Benutzerinhalt aus: Strings aus document.json werden
// ausschliesslich als Text eingesetzt ([#value]), nie per eval.

#import "../_tokens.typ": colors, space, radius

// Text aus Document.strings nachschlagen; {name}-Platzhalter ersetzen.
#let tr(ctx, key, ..params) = {
  let value = ctx.strings.at(key, default: key)
  for (name, param) in params.named() {
    value = value.replace("{" + name + "}", str(param))
  }
  value
}

#let is-blank(value) = value == none or (type(value) == str and value.trim() == "")

// Bedeutungsfarben (Tone aus model.py) → Farbe
#let tone-color(ctx, tone) = {
  let map = (
    default: colors.text,
    muted: colors.muted,
    success: colors.success,
    warning: colors.warning,
    danger: colors.danger,
    info: colors.accent,
    neutral: colors.neutral_fg,
    primary: ctx.theme.primary,
    secondary: ctx.theme.secondary,
  )
  map.at(tone, default: colors.text)
}

// Status-Schlüssel (z. B. "todoStatus.done") → Tone
#let status-tones = (
  "todoStatus.open": "warning",
  "todoStatus.in_progress": "info",
  "todoStatus.done": "success",
  "todoStatus.cancelled": "neutral",
  "attendanceStatus.present": "success",
  "attendanceStatus.late": "info",
  "attendanceStatus.excused": "warning",
  "attendanceStatus.absent": "danger",
  "fineStatus.open": "warning",
  "fineStatus.collected": "success",
  "fineStatus.collectedLater": "success",
  "fineStatus.collectedHere": "success",
  "protocolStatus.planned": "neutral",
  "protocolStatus.prepared": "info",
  "protocolStatus.held": "warning",
  "protocolStatus.closed": "success",
)

#let status-tone(key) = status-tones.at(key, default: "neutral")

// Kategoriale Reihenfarben: zuerst Hausfarben, dann die Diagrammfarben aus den Tokens.
#let series-palette(ctx) = (
  ctx.theme.primary,
  ctx.theme.secondary,
  colors.chart_1,
  colors.chart_2,
  colors.chart_3,
  colors.chart_4,
  colors.chart_5,
)

#let series-color(ctx, tone, index) = {
  if tone == "primary" or tone == none {
    let palette = series-palette(ctx)
    palette.at(calc.rem(index, palette.len()))
  } else {
    tone-color(ctx, tone)
  }
}

// Zahl mit Tausendertrenner ' (wie im Rest von hocX) und fester Anzahl Nachkommastellen.
#let format-number(value, decimals: 0) = {
  let negative = value < 0
  let factor = calc.pow(10, decimals)
  let rounded = calc.round(calc.abs(value) * factor)
  let whole = calc.floor(rounded / factor)
  let fraction = calc.rem(rounded, factor)
  let digits = str(int(whole))
  let grouped = ""
  let count = 0
  for index in range(digits.len() - 1, -1, step: -1) {
    if count > 0 and calc.rem(count, 3) == 0 {
      grouped = "'" + grouped
    }
    grouped = digits.at(index) + grouped
    count += 1
  }
  let result = grouped
  if decimals > 0 {
    let fraction-text = str(int(fraction))
    while fraction-text.len() < decimals {
      fraction-text = "0" + fraction-text
    }
    result += "." + fraction-text
  }
  if negative and rounded != 0 { "-" + result } else { result }
}

#let format-value(value, kind) = {
  if kind == "amount" { format-number(value, decimals: 2) }
  else if kind == "decimal" { format-number(value, decimals: 1) }
  else { format-number(value) }
}

// Farbiger Punkt mit Label (Status)
#let status-dot(ctx, key) = {
  let color = tone-color(ctx, status-tone(key))
  box(baseline: -0.1em, circle(radius: 0.28em, fill: color, stroke: none))
  h(0.35em)
  tr(ctx, key)
}

#let tag-chip(ctx, tag) = {
  let color = if tag.at("color", default: none) != none { rgb(tag.color) } else { colors.neutral_fg }
  box(
    inset: (x: 0.35em, y: 0.12em),
    radius: radius.xs,
    fill: color.lighten(82%),
    stroke: 0.4pt + color,
    text(size: 0.85em, fill: color.darken(35%))[#tag.label],
  )
}

#let empty-note(ctx, block-type) = {
  text(fill: colors.muted, style: "italic")[#tr(ctx, "empty." + block-type)]
}
