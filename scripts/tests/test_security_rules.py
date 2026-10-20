import importlib.util
import sys
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "check_security_rules", Path(__file__).resolve().parents[1] / "check-security-rules.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

PY = "backend/app/api/routes/example.py"
TS = "frontend/components/example.tsx"


def rules(path, current, baseline=None):
    return [finding.rule for finding in module.new_findings(path, current, baseline)]


class SecurityRulesTests(unittest.TestCase):
    def test_unscoped_lookup_is_reported_scoped_or_marked_is_fine(self):
        self.assertEqual(rules(PY, "x = public_id_service.get_by_public_id(db, Protocol, pid)\n"), ["public-id-lookup-without-tenant"])
        self.assertEqual(rules(PY, "x = public_id_service.get_by_public_id(db, Protocol, pid, tenant_id=t)\n"), [])
        marked = "x = resolve_internal_id(db, Tenant, pid)  # nosemgrep: public-id-lookup-without-tenant -- Plattform\n"
        self.assertEqual(rules(PY, marked), [])

    def test_only_new_findings_count(self):
        old = "a = get_by_public_id(db, A, x)\n"
        self.assertEqual(rules(PY, old, old), [])
        self.assertEqual(rules(PY, old + "b = get_by_public_id(db, B, y)\n", old), ["public-id-lookup-without-tenant"])

    def test_sql_fstring_with_values_is_reported(self):
        self.assertEqual(rules(PY, 'db.execute(text(f"SELECT * FROM t WHERE id = {value}"))\n'), ["sql-fstring"])
        self.assertEqual(rules(PY, 'db.execute(text("SELECT * FROM t WHERE id = :id"), {"id": value})\n'), [])
        self.assertEqual(rules(PY, 'db.execute(text(f"SET lock_timeout = {T}"))  # sql-ok: Konstante\n'), [])

    def test_http_exception_in_except_needs_a_cause(self):
        bare = "try:\n    f()\nexcept ValueError as exc:\n    raise HTTPException(status_code=400, detail='x')\n"
        chained = "try:\n    f()\nexcept ValueError as exc:\n    raise HTTPException(status_code=400, detail='x') from exc\n"
        self.assertEqual(rules(PY, bare), ["http-exception-without-cause"])
        self.assertEqual(rules(PY, chained), [])

    def test_scope_suspension_needs_a_reason(self):
        self.assertEqual(rules(PY, "with tenant_scope_suspended(db):\n    pass\n"), ["tenant-scope-suspended"])
        self.assertEqual(rules(PY, "with tenant_scope_suspended(db):  # rls-ok: nur Anzahl\n    pass\n"), [])

    def test_secrets_in_urls_are_reported(self):
        self.assertEqual(rules(PY, 'url = f"https://x/api/bridge?token={token}"\nredirect(url)\n'), [])
        self.assertEqual(rules(PY, 'redirect(f"https://x/api/bridge?token={token}")\n'), ["secret-in-url"])
        self.assertEqual(rules(TS, "fetch(`/api/x?password=${pw}`);\n"), ["secret-in-url"])
        self.assertEqual(rules(TS, 'fetch("/api/x", { method: "POST", body: JSON.stringify({ password }) });\n'), [])

    def test_inner_html_needs_a_reason(self):
        self.assertEqual(rules(TS, "<div dangerouslySetInnerHTML={{ __html: html }} />\n"), ["dangerously-set-inner-html"])
        marked = "<div dangerouslySetInnerHTML={{ __html: html }} /> {/* security-ok: bereinigt mit DOMPurify */}\n"
        self.assertEqual(rules(TS, marked), [])

    def test_tests_migrations_and_other_paths_are_ignored(self):
        self.assertEqual(rules("backend/tests/test_x.py", "get_by_public_id(db, A, x)\n"), [])
        self.assertEqual(rules("backend/alembic/versions/x.py", 'op.execute(f"DROP {name}")\n'), [])
        self.assertEqual(rules("frontend/e2e/x.spec.ts", "goto(`/x?token=${t}`)\n"), [])


if __name__ == "__main__":
    unittest.main()
