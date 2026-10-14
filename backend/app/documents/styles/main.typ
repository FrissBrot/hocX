// Einstieg jedes Compiles. Liest /document.json (Dokumentmodell, siehe model.py) und rendert es
// im gewählten Hausstil. Die Stilmodule liefern nur Daten und Darstellungsfunktionen; der
// Seitenaufbau und die Basis-Komponenten sind gemeinsam (base/).

#import "base/page.typ": setup-page, title-page, toc-section, metadata-section, verify-end
#import "base/blocks.typ": render-blocks
#import "modern.typ" as modern-style
#import "classic.typ" as classic-style
#import "compact.typ" as compact-style

#let doc = json("/document.json")
#let themes = (modern: modern-style.theme, classic: classic-style.theme, compact: compact-style.theme)
#let theme = themes.at(doc.style.key, default: modern-style.theme)(doc)
#let ctx = (doc: doc, strings: doc.strings, theme: theme)

#show: setup-page.with(ctx)
#title-page(ctx)
#toc-section(ctx)
#metadata-section(ctx)
#render-blocks(ctx, doc.blocks)
#verify-end(ctx)
