/**
 * Ctrl+F und «/» auf Seiten mit Liste: springen in das Suchfeld der Liste (SearchInput), statt
 * die Browsersuche zu öffnen. Ist der Fokus schon dort, bleibt Ctrl+F beim Browser.
 *
 * Gesucht wird im obersten offenen Dialog, sonst im Seiteninhalt - nie im Suchfenster selbst
 * (data-global-search) und nie in versteckten Feldern. Ein Suchfeld kann sich mit
 * data-list-search="off" ausnehmen.
 */
const CONTENT_ROOTS = ".shell-content, .mobile-shell-content";

function isVisible(element: HTMLElement): boolean {
  return element.getClientRects().length > 0 && !element.closest("[hidden]");
}

export function findListSearchInput(doc: Document = document): HTMLInputElement | null {
  const dialogs = Array.from(doc.querySelectorAll<HTMLElement>('[role="dialog"]')).filter(
    (dialog) => !dialog.closest("[data-global-search]") && !dialog.querySelector("[data-global-search]") && isVisible(dialog)
  );
  const roots: ParentNode[] = dialogs.length > 0 ? [dialogs[dialogs.length - 1]] : Array.from(doc.querySelectorAll(CONTENT_ROOTS));
  for (const root of roots) {
    const inputs = Array.from(root.querySelectorAll<HTMLInputElement>(".search-input input"));
    const found = inputs.find(
      (input) => !input.disabled && !input.closest("[data-global-search]") && !input.closest('[data-list-search="off"]') && isVisible(input)
    );
    if (found) return found;
  }
  return null;
}

export function focusListSearch(input: HTMLInputElement, text?: string): void {
  if (text !== undefined) {
    // Kontrolliertes React-Feld: Wert über den nativen Setter setzen und ein input-Ereignis
    // auslösen, damit der onChange der Liste läuft.
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
  input.focus();
  input.select();
}

export function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element || !element.tagName) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable;
}
