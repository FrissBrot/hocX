"""Tests für scripts/check-keyboard-a11y.py (JSX-Scanner und Tastatur-Regeln)."""
import importlib.util
import sys
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_keyboard_a11y", Path(__file__).resolve().parents[1] / "check-keyboard-a11y.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def rules(source: str, rel: str = "frontend/components/x.tsx") -> list[str]:
    return [rule for rule, _, _ in module.check_source(rel, source)]


def css_rules(source: str) -> list[str]:
    return [rule for rule, _, _ in module.check_css("frontend/app/globals.css", source)]


class ScannerTests(unittest.TestCase):
    def test_multiline_tags_with_nested_expressions(self):
        source = """
export function A() {
  const ok = a < b && c > d;
  return (
    <div
      className={x > 1 ? "a" : "b"}
      onClick={() => { if (y > 2) run({ a: [1, 2] }); }}
    >
      {items.map((item) => <span key={item}>{`${item} > 0`}</span>)}
    </div>
  );
}
"""
        tags = module.JsxScanner(source).scan()
        self.assertEqual([tag.name for tag in tags], ["div", "span"])
        self.assertIn("onClick", tags[0].attrs)
        self.assertEqual(tags[0].line, 5)

    def test_generics_and_comparisons_are_not_jsx(self):
        source = "const r = useRef<HTMLDivElement>(null);\nconst m = new Map<string, number>();\nif (a<b) {}\n"
        self.assertEqual(module.JsxScanner(source).scan(), [])

    def test_strings_comments_and_regex_do_not_derail(self):
        source = """
const re = /<div onClick>/g; // <div onClick={x}>
/* <span onClick={y}> */
const s = "<div onClick={z}>";
const view = <button type="button" onClick={go}>Los</button>;
"""
        self.assertEqual([tag.name for tag in module.JsxScanner(source).scan()], ["button"])


class RuleTests(unittest.TestCase):
    def test_clickable_div_without_keyboard(self):
        self.assertEqual(rules('const a = <div className="row" onClick={open}>x</div>;'), ["clickable-no-keyboard"])
        self.assertEqual(rules('const a = <tr onClick={() => open(row)}><td>x</td></tr>;'), ["clickable-no-keyboard"])

    def test_buttons_and_complete_custom_widgets_pass(self):
        self.assertEqual(rules('const a = <button type="button" onClick={open}>x</button>;'), [])
        self.assertEqual(rules('const a = <div role="button" tabIndex={0} onClick={open} onKeyDown={key}>x</div>;'), [])
        self.assertEqual(rules('const a = <div onClick={(event) => event.stopPropagation()}>x</div>;'), [])
        self.assertEqual(rules('const a = <div role="presentation" onClick={close}>x</div>;'), [])

    def test_role_without_keyboard(self):
        self.assertEqual(rules('const a = <div role="button" onClick={open}>x</div>;'), ["role-without-keyboard"])
        self.assertEqual(rules('const a = <span role="tab" tabIndex={0} onClick={open}>x</span>;'), ["role-without-keyboard"])

    def test_pointer_only_activation(self):
        self.assertEqual(rules('const a = <button type="button" onPointerDown={(e) => { e.preventDefault(); add(); }}>x</button>;'), ["pointer-only-activation"])
        self.assertEqual(rules('const a = <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={add}>x</button>;'), [])

    def test_positive_tabindex(self):
        self.assertEqual(rules('const a = <input tabIndex={2} />;'), ["positive-tabindex"])
        self.assertEqual(rules('const a = <div tabIndex={-1} />;'), [])

    def test_global_key_listener_only_in_central_modules(self):
        line = 'window.addEventListener("keydown", onKey);\n'
        self.assertEqual(rules(line, "frontend/components/a.tsx"), ["global-key-listener"])
        self.assertEqual(rules(line, "frontend/lib/keyboard/use-shortcut.ts"), [])

    def test_alt_letter_by_key(self):
        self.assertEqual(rules('if (event.key === "t" && event.altKey) run();\n'), ["alt-letter-by-key"])
        self.assertEqual(rules('if (event.key === "t" && !event.altKey) run();\n'), [])

    def test_marker_allows_justified_exception(self):
        self.assertEqual(rules('const a = <div onClick={close} /* a11y-ok: Hintergrund, Escape schliesst */>x</div>;'), [])

    def test_outline_none_needs_replacement(self):
        self.assertEqual(css_rules(".a:focus { outline: none; }"), ["outline-none"])
        self.assertEqual(css_rules(".a:focus { outline: none; box-shadow: var(--focus-ring); }"), [])
        self.assertEqual(css_rules(".a:focus { outline: none; /* a11y-ok: Rahmen am Wrapper */ }"), [])
        self.assertEqual(css_rules(".a:focus-within .b { outline: none; }"), [])
        self.assertEqual(css_rules(".a { outline: none; }"), [])


if __name__ == "__main__":
    unittest.main()
