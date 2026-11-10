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

    def test_blocking_db_in_async_is_reported(self):
        blocking = "async def route(db=Depends(get_db)):\n    db.commit()\n    return load(db)\n"
        self.assertEqual(rules(PY, blocking), ["blocking-db-in-async", "blocking-db-in-async"])
        offloaded = "async def route(db=Depends(get_db)):\n    await run_in_threadpool(load, db)\n    await asyncio.to_thread(lambda: db.commit())\n"
        self.assertEqual(rules(PY, offloaded), [])
        awaited = "async def route(db):\n    return await service.save(db)\n"
        self.assertEqual(rules(PY, awaited), [])
        nested = "async def route(db):\n    def work():\n        db.commit()\n    await run_in_threadpool(work)\n"
        self.assertEqual(rules(PY, nested), [])
        marked = "async def job(db):  # loop-ok: läuft im Worker-Thread\n    db.commit()\n"
        self.assertEqual(rules(PY, marked), [])

    def test_stream_response_with_request_scoped_session_is_reported(self):
        held = "def download(db: Session = Depends(get_db)):\n    return object_response(request, MAIN, key)\n"
        self.assertEqual(rules(PY, held), ["stream-response-holds-db"])
        scoped = 'def download(db: Session = Depends(get_db, scope="function")):\n    return FileResponse(path)\n'
        self.assertEqual(rules(PY, scoped), [])
        released = "def download(db: Session = Depends(get_db)):\n    return release_for_stream(db, FileResponse(path))\n"
        self.assertEqual(rules(PY, released), [])

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

    def test_role_code_comparisons_are_reported(self):
        self.assertEqual(rules(PY, 'if user.role_code == "admin":\n    pass\n'), ["role-code-comparison"])
        self.assertEqual(rules(PY, 'ok = role.system_key in ("writer", "kassier")\n'), ["role-code-comparison"])
        self.assertEqual(rules(PY, 'if source == "admin":\n    pass\n'), [])
        self.assertEqual(rules(PY, 'if access == "writer":\n    pass\n'), [])
        self.assertEqual(rules(PY, 'if role.system_key == "reader":  # rbac-ok: Standardrolle als Fallback\n    pass\n'), [])
        self.assertEqual(rules(TS, 'const isAdmin = session.current_role === "admin";\n'), ["role-code-comparison"])
        self.assertEqual(rules(TS, 'if (role?.system_key !== "writer") return;\n'), ["role-code-comparison"])
        self.assertEqual(rules(TS, 'if (binding.access === "writer") return;\n'), [])
        self.assertEqual(rules("frontend/lib/permissions.ts", 'role.system_key === "admin";\n'), [])

    def test_role_writes_belong_to_role_service(self):
        self.assertEqual(rules(PY, "db.add(UserRole(tenant_id=t, user_id=u, role_id=r))\n"), ["role-write-outside-role-service"])
        self.assertEqual(rules(PY, "db.execute(delete(TenantRolePermission).where(x))\n"), ["role-write-outside-role-service"])
        self.assertEqual(rules(PY, 'db.execute(text("DELETE FROM user_role WHERE user_id = :id"), {"id": 1})\n'), ["role-write-outside-role-service"])
        self.assertEqual(rules(PY, "rows = db.scalars(select(UserRole.role_id).where(UserRole.user_id == u))\n"), [])
        self.assertEqual(rules("backend/scripts/seed.py", "db.add(TenantRole(tenant_id=t))\n"), ["role-write-outside-role-service"])
        self.assertEqual(rules("backend/app/services/role_service.py", "db.add(UserRole(tenant_id=t))\n"), [])

    def test_tests_migrations_and_other_paths_are_ignored(self):
        self.assertEqual(rules("backend/tests/test_x.py", "get_by_public_id(db, A, x)\n"), [])
        self.assertEqual(rules("backend/alembic/versions/x.py", 'op.execute(f"DROP {name}")\n'), [])
        self.assertEqual(rules("frontend/e2e/x.spec.ts", "goto(`/x?token=${t}`)\n"), [])


if __name__ == "__main__":
    unittest.main()
