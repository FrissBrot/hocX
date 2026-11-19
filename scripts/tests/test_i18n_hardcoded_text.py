"""Tests für scripts/check-i18n-hardcoded-text.py (Text neben `{Ausdruck}`, Template-Literale)."""
import importlib.util
import sys
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_i18n_hardcoded_text", Path(__file__).resolve().parents[1] / "check-i18n-hardcoded-text.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def found(line: str) -> int:
    return len(module.line_findings(line))


class HardcodedTextTests(unittest.TestCase):
    def test_text_next_to_an_expression_is_reported(self):
        # Nachtlauf 2026-11-19, Fund 4/5: rutschten am alten Check vorbei.
        self.assertEqual(found("    {(file.size / (1024 * 1024)).toFixed(1)} MB · zum Ersetzen klicken oder Datei hierher ziehen"), 1)
        self.assertEqual(found("  <WarningIcon /> {count} Hinweis{count === 1 ? \"\" : \"e\"} zur Analyse"), 2)
        self.assertEqual(found("  <> {skipped} Einträge wurden übersprungen.</>"), 1)
        self.assertEqual(found('<span className="pill">{count} ausgewählt</span>'), 1)
        self.assertEqual(found('<div className="muted">bisher: {value}</div>'), 1)
        self.assertEqual(found('<span>Feldtyp &quot;{field.row_type}&quot; wird nicht unterstützt.</span>'), 2)

    def test_prose_template_literals_are_reported(self):
        self.assertEqual(found("  `${a} Anwesenheiten, ${b} Termine wurden übernommen.`}"), 1)
        self.assertEqual(found('message: `Zeile "${label}" endgültig löschen?`,'), 1)

    def test_code_next_to_expressions_is_not_reported(self):
        for line in [
            "} catch (error) {",
            "} finally {",
            "export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {",
            "const values = { ...raw } as Record<string, string>;",
            "if (now - last > SESSION_STALE_MS) {",
            "type Props = { a: string } & Omit<Base, \"b\">;",
            '<span className="pill">{t("selected", { count })}</span>',
            "<div className={`card card-${tone}`}>",
            "t(`modal.${decision.kind}Title`)",
            "padding: `${mm(top)}px ${mm(right)}px solid ${color}`,",
            "const url = `/api/protocols/${id}/elements?skip=${skip}`;",
            "{/* {count} Fotos */}",
            "<span>{count} Fotos</span> // i18n-ok: Testfall",
        ]:
            with self.subTest(line=line):
                self.assertEqual(module.line_findings(line), [])

    def test_plain_jsx_text_is_still_reported_once(self):
        self.assertEqual(found("<span>Benutzer löschen</span>"), 1)


if __name__ == "__main__":
    unittest.main()
