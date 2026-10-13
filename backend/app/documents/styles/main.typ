// Einstieg jedes Compiles. Liest /document.json (Dokumentmodell, siehe model.py) und rendert es
// im gewählten Hausstil. Die Stilmodule liefern nur Daten und Darstellungsfunktionen; der
// Seitenaufbau und die Basis-Komponenten sind gemeinsam (base/).

#import "base/page.typ": setup-page, title-page, toc-section
#import "base/blocks.typ": render-blocks
#import "modern.typ" as modern-style

#let doc = json("/document.json")
#let themes = (modern: modern-style.theme)
#let theme = themes.at(doc.style.key, default: modern-style.theme)(doc)
#let ctx = (doc: doc, strings: doc.strings, theme: theme)

#show: setup-page.with(ctx)
#title-page(ctx)
#toc-section(ctx)
#render-blocks(ctx, doc.blocks)
