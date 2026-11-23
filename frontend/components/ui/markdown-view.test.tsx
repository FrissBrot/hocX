import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownView, parseMarkdownBlocks } from "./markdown-view";

function html(markdown: string) {
  const { container } = render(<MarkdownView markdown={markdown} />);
  return container.innerHTML;
}

describe("MarkdownView", () => {
  it("zeigt Absätze, fett und kursiv", () => {
    expect(html("Hallo **Welt** und *du*\n\nZweiter _Absatz_")).toBe(
      '<div class="markdown-view"><p>Hallo <strong>Welt</strong> und <em>du</em></p><p>Zweiter <em>Absatz</em></p></div>'
    );
  });

  it("unterscheidet harte Umbrüche von weichen", () => {
    expect(html("eins\\\nzwei\ndrei")).toBe('<div class="markdown-view"><p>eins<br>zwei drei</p></div>');
  });

  it("baut Aufzählungen und nummerierte Listen, auch verschachtelt", () => {
    expect(html("- a\n- b\n  1. x\n  2. y\n- c")).toBe(
      '<div class="markdown-view"><ul><li>a</li><li>b<ol><li>x</li><li>y</li></ol></li><li>c</li></ul></div>'
    );
    expect(html("3. drei\n4. vier")).toBe('<div class="markdown-view"><ol start="3"><li>drei</li><li>vier</li></ol></div>');
  });

  it("maskiert HTML statt es auszuführen und löst Entitäten von tiptap-markdown auf", () => {
    const { container } = render(<MarkdownView markdown={'<img src=x onerror="alert(1)"> &lt;b&gt; \\*kein\\* fett'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe('<img src=x onerror="alert(1)"> <b> *kein* fett');
  });

  it("verlinkt nackte Links wie der Editor, ohne javascript:-Adressen", () => {
    const { container } = render(<MarkdownView markdown="Siehe www.hocx.ch und javascript:alert(1)" />);
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("https://www.hocx.ch");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("lässt Unterstriche im Wort stehen", () => {
    expect(html("datei_name_neu")).toBe('<div class="markdown-view"><p>datei_name_neu</p></div>');
  });

  it("zeigt bei leerem Text den Platzhalter", () => {
    const { container } = render(<MarkdownView markdown="  " placeholder="Noch kein Text" />);
    expect(container.textContent).toBe("Noch kein Text");
    expect(parseMarkdownBlocks("")).toEqual([]);
  });
});
