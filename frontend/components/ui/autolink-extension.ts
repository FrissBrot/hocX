import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";

import { findLinks } from "@/lib/utils/autolink";

// Nackte Links (URL, www., E-Mail) im Editor als Link darstellen - nur als Dekoration: das
// gespeicherte Markdown bleibt unverändert (keine Link-Marke, kein Speichern beim Öffnen, kein
// Ausschlag in «Änderungen nachverfolgen»). Im PDF macht richtext.autolink daraus echte Links.
// Strg/Cmd-Klick (bzw. Klick im Nur-Lesen-Modus) öffnet den Link in einem neuen Tab.

type AutolinkOptions = { openHint: string };

const autolinkKey = new PluginKey<DecorationSet>("autolink");

function buildDecorations(doc: ProseMirrorNode, openHint: string): DecorationSet {
  const decorations: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return;
    if (node.marks.some((mark) => mark.type.name === "code" || mark.type.name === "link")) return;
    for (const link of findLinks(node.text)) {
      decorations.push(
        Decoration.inline(pos + link.from, pos + link.to, { class: "rich-text-autolink", title: openHint }, { href: link.href })
      );
    }
  });
  return DecorationSet.create(doc, decorations);
}

export const Autolink = Extension.create<AutolinkOptions>({
  name: "autolink",

  addOptions() {
    return { openHint: "" };
  },

  addProseMirrorPlugins() {
    const { openHint } = this.options;
    return [
      new Plugin<DecorationSet>({
        key: autolinkKey,
        state: {
          init: (_, state) => buildDecorations(state.doc, openHint),
          apply: (tr, old) => (tr.docChanged ? buildDecorations(tr.doc, openHint) : old),
        },
        props: {
          decorations: (state) => autolinkKey.getState(state),
          handleClick(view, pos, event) {
            if (!(event.ctrlKey || event.metaKey) && view.editable) return false;
            const found = autolinkKey.getState(view.state)?.find(pos, pos) ?? [];
            const href = (found[0]?.spec as { href?: string } | undefined)?.href;
            if (!href) return false;
            window.open(href, "_blank", "noopener,noreferrer");
            return true;
          },
        },
      }),
    ];
  },
});
