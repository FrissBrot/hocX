"use client";

// Auswahlfeld im hocX-Look. Bleibt ein echtes <select> (Beschriftung über <label>, Formulare,
// Tastaturfokus, Screenreader und `onChange` wie gewohnt), ersetzt aber die Liste des
// Betriebssystems durch eine eigene: Maus und die Öffnen-Tasten (Pfeile, Leertaste, Enter, F4)
// zeigen sie, die Auswahl setzt den Wert des Selects und löst ein normales `change` aus.
// Auf Touch-Geräten bleibt die native Auswahl (Wählrad von iOS/Android), ebenso bei `multiple`
// und `size`.

import {
  CSSProperties,
  forwardRef,
  KeyboardEvent,
  MouseEvent,
  MutableRefObject,
  Ref,
  RefObject,
  SelectHTMLAttributes,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { computePopoverPosition, usePopoverDismiss } from "./popover";

type Item = { kind: "option"; value: string; label: string; disabled: boolean } | { kind: "group"; label: string };

const OPTION_HEIGHT = 36;
const TYPEAHEAD_RESET_MS = 700;

function readItems(select: HTMLSelectElement): Item[] {
  const items: Item[] = [];
  const option = (element: HTMLOptionElement, groupDisabled = false): Item => ({
    kind: "option",
    value: element.value,
    label: element.label || element.text,
    disabled: element.disabled || groupDisabled,
  });
  for (const child of Array.from(select.children)) {
    if (child instanceof HTMLOptionElement) {
      if (!child.hidden) items.push(option(child));
    } else if (child instanceof HTMLOptGroupElement) {
      items.push({ kind: "group", label: child.label });
      for (const nested of Array.from(child.children)) {
        if (nested instanceof HTMLOptionElement && !nested.hidden) items.push(option(nested, child.disabled));
      }
    }
  }
  return items;
}

function prefersNativePicker(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
}

/** Wert setzen wie bei einer Auswahl in der nativen Liste: React erhält ein normales onChange. */
function selectValue(select: HTMLSelectElement, value: string) {
  if (select.value === value) return;
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
  setter?.call(select, value);
  select.dispatchEvent(new Event("input", { bubbles: true }));
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function assignRef(ref: Ref<HTMLSelectElement> | undefined, value: HTMLSelectElement | null) {
  if (typeof ref === "function") ref(value);
  else if (ref) (ref as MutableRefObject<HTMLSelectElement | null>).current = value;
}

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select({ onMouseDown, onKeyDown, ...props }, forwardedRef) {
  const selectRef = useRef<HTMLSelectElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const typeahead = useRef<{ text: string; at: number }>({ text: "", at: 0 });
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState(-1);
  const [style, setStyle] = useState<CSSProperties>({});
  const custom = !props.multiple && !(props.size && props.size > 1);

  const close = useCallback(() => setOpen(false), []);
  usePopoverDismiss(open, close, [selectRef as RefObject<HTMLElement | null>, panelRef]);

  // Liste schliessen, wenn sich die Seite unter ihr bewegt (Position wäre sonst falsch)
  useEffect(() => {
    if (!open) return;
    const onScroll = (event: Event) => {
      if (panelRef.current?.contains(event.target as Node)) return;
      close();
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [open, close]);

  useEffect(() => {
    if (!open || active < 0) return;
    const element = panelRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    element?.scrollIntoView?.({ block: "nearest" });
  }, [open, active]);

  function openList() {
    const select = selectRef.current;
    if (!select || select.disabled) return;
    const next = readItems(select);
    setItems(next);
    setActive(next.findIndex((item) => item.kind === "option" && item.value === select.value));
    setStyle(computePopoverPosition(select.getBoundingClientRect(), "start", 4, { estimatedHeight: Math.min(320, next.length * OPTION_HEIGHT + 16) }));
    setOpen(true);
  }

  function choose(index: number) {
    const select = selectRef.current;
    const item = items[index];
    if (!select || !item || item.kind !== "option" || item.disabled) return;
    setOpen(false);
    select.focus();
    selectValue(select, item.value);
  }

  function move(from: number, step: number): number {
    for (let index = from + step; index >= 0 && items.length > index; index += step) {
      const item = items[index];
      if (item.kind === "option" && !item.disabled) return index;
    }
    return from;
  }

  function edge(fromEnd: boolean): number {
    const start = fromEnd ? items.length : -1;
    return move(start, fromEnd ? -1 : 1);
  }

  function findByText(key: string): number {
    const now = Date.now();
    const text = (now - typeahead.current.at > TYPEAHEAD_RESET_MS ? "" : typeahead.current.text) + key.toLowerCase();
    typeahead.current = { text, at: now };
    const order = [...items.keys()].slice(active + 1).concat([...items.keys()].slice(0, active + 1));
    // Gleicher Buchstabe mehrfach: zum nächsten Eintrag mit diesem Anfang springen
    const needle = text.split("").every((char) => char === text[0]) ? text[0] : text;
    const found = order.find((index) => {
      const item = items[index];
      return item.kind === "option" && !item.disabled && item.label.trim().toLowerCase().startsWith(needle);
    });
    return found ?? active;
  }

  function handleMouseDown(event: MouseEvent<HTMLSelectElement>) {
    onMouseDown?.(event);
    if (event.defaultPrevented || !custom || event.button !== 0 || prefersNativePicker()) return;
    event.preventDefault();
    event.currentTarget.focus();
    if (open) close();
    else openList();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLSelectElement>) {
    onKeyDown?.(event);
    if (event.defaultPrevented || !custom || prefersNativePicker()) return;
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " ", "F4"].includes(event.key)) {
        event.preventDefault();
        openList();
      }
      return;
    }
    const handled = (index: number) => {
      event.preventDefault();
      setActive(index);
    };
    switch (event.key) {
      case "ArrowDown":
        return handled(move(active, 1));
      case "ArrowUp":
        return handled(move(active, -1));
      case "PageDown":
        return handled(Array.from({ length: 8 }).reduce<number>((index) => move(index, 1), active));
      case "PageUp":
        return handled(Array.from({ length: 8 }).reduce<number>((index) => move(index, -1), active));
      case "Home":
        return handled(edge(false));
      case "End":
        return handled(edge(true));
      case "Enter":
      case " ":
        event.preventDefault();
        choose(active);
        return;
      case "Tab":
        close();
        return;
      default:
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) handled(findByText(event.key));
    }
  }

  const currentValue = selectRef.current?.value;
  return (
    <>
      <select
        {...props}
        ref={(element) => {
          selectRef.current = element;
          assignRef(forwardedRef, element);
        }}
        aria-expanded={custom ? open : undefined}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        onMouseDown={handleMouseDown}
        onKeyDown={handleKeyDown}
      />
      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panelRef}
              id={listId}
              role="listbox"
              aria-label={props["aria-label"]}
              className="popover-panel select-list"
              style={style}
              // Fokus bleibt auf dem Select (Tastatur, Formular)
              onMouseDown={(event) => event.preventDefault()}
            >
              {items.map((item, index) =>
                item.kind === "group" ? (
                  <div key={`group-${index}`} className="select-list-group" role="presentation">
                    {item.label}
                  </div>
                ) : (
                  <div
                    key={`option-${index}`}
                    id={`${listId}-${index}`}
                    data-index={index}
                    role="option"
                    aria-selected={item.value === currentValue}
                    aria-disabled={item.disabled || undefined}
                    className={[
                      "select-option",
                      item.value === currentValue ? "select-option-selected" : "",
                      index === active ? "select-option-active" : "",
                      item.disabled ? "select-option-disabled" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onMouseEnter={() => !item.disabled && setActive(index)}
                    onClick={() => choose(index)}
                  >
                    <span className="select-option-label">{item.label}</span>
                    {item.value === currentValue ? (
                      <span className="select-option-check" aria-hidden="true">
                        ✓
                      </span>
                    ) : null}
                  </div>
                )
              )}
            </div>,
            document.body
          )
        : null}
    </>
  );
});
