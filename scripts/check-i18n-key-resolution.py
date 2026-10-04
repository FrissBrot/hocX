#!/usr/bin/env python3
"""Prueft, ob t("key")-Aufrufe tatsaechlich einen existierenden Key in ihrem useTranslations/
getTranslations-Namespace treffen - deckt eine Bug-Klasse ab, die check-i18n-completeness.py
(nur Key-Paritaet zwischen Locales) und check-i18n-hardcoded-text.py (nur hartcodierter Text)
nicht sehen: ein t()-Aufruf, der syntaktisch korrekt aussieht, aber den falschen Namespace oder
einen nicht existierenden Key trifft, bricht erst zur Laufzeit mit next-intls MISSING_MESSAGE
(siehe z.B. app-shell.tsx: t("breadcrumbNav") auf dem "nav"-Namespace statt "common").

Arbeitsweise (zwei Pässe, beide nur gegen den deutschen Katalog - Vollstaendigkeit über die
Locales deckt check-i18n-completeness.py ab):

1. Scope-Pass: pro Top-Level-Funktion/Komponente werden lokale
   `const x = useTranslations("ns")` / `await getTranslations("ns")`-Zuweisungen erfasst und
   jeder `x("key")`-Aufruf im selben Scope gegen den Katalog aufgeloest.
2. Interprozeduraler Pass: fuer modulweite Hilfsfunktionen mit einem Parameter `t: TFunc` (das
   "TFunc-Muster" dieser Codebase, siehe CLAUDE.md) werden Aufrufstellen gesucht - in derselben
   Datei und in Dateien, die die Funktion per `import { fn } from "..."` beziehen - und das dort
   fuer `t` uebergebene Argument auf eine Namespace-Zuweisung im Scope dieser Aufrufstelle
   zurueckgefuehrt.

Bekannte Grenze: mehrstufige Parameter-Weiterleitung (eine Hilfsfunktion ruft eine andere mit
ihrem eigenen `t`-Parameter auf) kann nicht vollstaendig aufgeloest werden - solche Treffer
werden als "nicht verifizierbar" uebersprungen statt geraten (kein falscher Alarm), erscheinen
also nicht als Fund. Ein echter Fund bedeutet immer: der Namespace wurde konkret aufgeloest und
der Key fehlt dort nachweislich.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = [ROOT / "frontend", ROOT / "abgabebox-frontend"]

DECL_RE = re.compile(r'\b(?:const|let)\s+(\w+)\s*=\s*(?:await\s+)?(?:useTranslations|getTranslations)\(\s*"([^"]*)"\s*\)')
CALL_RE_TEMPLATE = r'\b{}\(\s*"([a-zA-Z0-9_.]+)"'
FN_DEF_RE = re.compile(r'\bfunction\s+(\w+)\s*(?:<[^>]*>)?\(([^)]*)\)')
TOPLEVEL_FN_RE = re.compile(r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+\w+')
IMPORT_RE = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"([^"]+)"')
GENERIC_CALL_RE = re.compile(r'\b(\w+)\(\s*"([a-zA-Z0-9_.]+)"')


def load_catalog(app_dir: Path, locale: str) -> dict:
    messages_dir = app_dir / "messages" / locale
    catalog = {}
    if not messages_dir.is_dir():
        return catalog
    for f in messages_dir.glob("*.json"):
        catalog[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return catalog


def resolve(catalog: dict, namespace: str, key: str):
    parts = namespace.split(".") if namespace else []
    if not parts:
        return None, "no-namespace"
    ns_file = parts[0]
    if ns_file not in catalog:
        return None, f"missing-namespace-file:{ns_file}"
    node = catalog[ns_file]
    for p in parts[1:]:
        if not isinstance(node, dict) or p not in node:
            return None, f"missing-namespace-path:{namespace}"
        node = node[p]
    for p in key.split("."):
        if not isinstance(node, dict) or p not in node:
            return None, "missing-key"
        node = node[p]
    if not isinstance(node, str):
        return None, "not-a-string"
    return node, None


def find_toplevel_fn_ranges(lines):
    ranges = []
    i, n = 0, len(lines)
    while i < n:
        if TOPLEVEL_FN_RE.match(lines[i]):
            j, depth, started = i, 0, False
            while j < n:
                for ch in lines[j]:
                    if ch == "{":
                        depth += 1
                        started = True
                    elif ch == "}":
                        depth -= 1
                if started and depth == 0:
                    ranges.append((i, j))
                    break
                j += 1
            i = j + 1 if started else i + 1
        else:
            i += 1
    return ranges


def var_ns_for_range(lines, start, end):
    var_ns = {}
    for line in lines[start:end + 1]:
        for m in DECL_RE.finditer(line):
            var_ns[m.group(1)] = m.group(2)
    return var_ns


def find_enclosing_range(ranges, line_idx):
    for start, end in ranges:
        if start <= line_idx <= end:
            return start, end
    return None


def split_args(arg_str):
    args, depth, cur = [], 0, ""
    for ch in arg_str:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def resolve_import_path(app_dir: Path, importer_file: Path, spec: str):
    if spec.startswith("@/"):
        base = app_dir / spec[2:]
    elif spec.startswith("."):
        base = (importer_file.parent / spec).resolve()
    else:
        return None
    for suffix in (".tsx", ".ts", "/index.tsx", "/index.ts"):
        candidate = Path(str(base) + suffix) if not str(base).endswith(suffix) else base
        if candidate.exists():
            return candidate.resolve()
    if base.exists():
        return base.resolve()
    return None


def collect_files(app_dir: Path):
    files = list(app_dir.glob("components/**/*.tsx")) + list(app_dir.glob("app/**/*.tsx")) + \
        list(app_dir.glob("components/**/*.ts")) + list(app_dir.glob("app/**/*.ts"))
    return [f for f in files if ".test." not in f.name]


def scope_pass(file_data, catalogs):
    findings = []
    for f, data in file_data.items():
        catalog = catalogs.get(data["app"], {})
        for start, end in data["ranges"]:
            vns = var_ns_for_range(data["lines"], start, end)
            if not vns:
                continue
            for ln_off, line in enumerate(data["lines"][start:end + 1]):
                for m in GENERIC_CALL_RE.finditer(line):
                    varname, key = m.group(1), m.group(2)
                    if varname not in vns:
                        continue
                    namespace = vns[varname]
                    value, err = resolve(catalog, namespace, key)
                    if err:
                        findings.append((f, start + ln_off + 1, varname, namespace, key, err))
    return findings


def interprocedural_pass(file_data, catalogs, import_map):
    fn_registry = {}
    for f, data in file_data.items():
        for m in FN_DEF_RE.finditer(data["src"]):
            fn_name = m.group(1)
            params = split_args(m.group(2))
            t_idx = None
            for idx, p in enumerate(params):
                pname = p.split(":")[0].strip().lstrip(".").strip()
                if pname in ("t", "t?"):
                    t_idx = idx
                    break
            if t_idx is None:
                continue
            line_idx = data["src"].count("\n", 0, m.start())
            enclosing = find_enclosing_range(data["ranges"], line_idx)
            if enclosing is None:
                for r in data["ranges"]:
                    if r[0] == line_idx:
                        enclosing = r
                        break
            if enclosing is None:
                continue
            fn_registry.setdefault((fn_name, f), []).append((t_idx, enclosing[0], enclosing[1]))

    importer_files_for = {}
    for f, mapping in import_map.items():
        for name, src_file in mapping.items():
            importer_files_for.setdefault((name, src_file), set()).add(f)

    findings = []
    call_key_re_cache = {}

    for (fn_name, def_file), defs in fn_registry.items():
        call_re = call_key_re_cache.setdefault(fn_name, re.compile(CALL_RE_TEMPLATE.format("t")))
        for t_idx, body_start, body_end in defs:
            body_lines = file_data[def_file]["lines"][body_start:body_end + 1]
            keys = []
            for ln_off, line in enumerate(body_lines):
                for m in call_re.finditer(line):
                    keys.append((body_start + ln_off + 1, m.group(1)))
            if not keys:
                continue
            search_files = {def_file} | importer_files_for.get((fn_name, def_file), set())
            resolved_namespaces = set()
            for cf in search_files:
                cdata = file_data[cf]
                for cm in re.finditer(r'\b' + re.escape(fn_name) + r'\(', cdata["src"]):
                    if cf == def_file:
                        call_line_idx0 = cdata["src"].count("\n", 0, cm.start())
                        if body_start <= call_line_idx0 <= body_end:
                            continue
                    start_paren = cm.end() - 1
                    depth, i, arg_text = 0, start_paren, ""
                    while i < len(cdata["src"]):
                        ch = cdata["src"][i]
                        if ch == "(":
                            depth += 1
                            if depth == 1:
                                i += 1
                                continue
                        elif ch == ")":
                            depth -= 1
                            if depth == 0:
                                break
                        arg_text += ch
                        i += 1
                    args = split_args(arg_text)
                    if t_idx >= len(args):
                        continue
                    arg_expr = args[t_idx].strip()
                    call_line_idx = cdata["src"].count("\n", 0, cm.start())
                    ns = None
                    inline_m = re.match(r'(?:await\s+)?(?:useTranslations|getTranslations)\(\s*"([^"]*)"\s*\)', arg_expr)
                    if inline_m:
                        ns = inline_m.group(1)
                    elif re.match(r'^\w+$', arg_expr):
                        enclosing = find_enclosing_range(cdata["ranges"], call_line_idx)
                        if enclosing:
                            vns = var_ns_for_range(cdata["lines"], enclosing[0], enclosing[1])
                            ns = vns.get(arg_expr)
                    if ns:
                        resolved_namespaces.add(ns)
            if not resolved_namespaces:
                continue  # nicht verifizierbar - kein Fund, kein Fehlalarm
            app_dir = file_data[def_file]["app"]
            catalog = catalogs.get(app_dir, {})
            for ns in resolved_namespaces:
                for line, key in keys:
                    value, err = resolve(catalog, ns, key)
                    if err:
                        findings.append((def_file, line, fn_name, ns, key, err))
    return findings


def main():
    file_data = {}
    for app_dir in APPS:
        for f in collect_files(app_dir):
            src = f.read_text(encoding="utf-8")
            lines = src.split("\n")
            file_data[f] = {
                "src": src, "lines": lines,
                "ranges": find_toplevel_fn_ranges(lines), "app": app_dir,
            }

    import_map = {}
    for f, data in file_data.items():
        mapping = {}
        for m in IMPORT_RE.finditer(data["src"]):
            names = [n.strip().split(" as ")[0].strip() for n in m.group(1).split(",") if n.strip()]
            src_file = resolve_import_path(data["app"], f, m.group(2))
            if src_file:
                for n in names:
                    mapping[n] = src_file
        import_map[f] = mapping

    catalogs = {app_dir: load_catalog(app_dir, "de") for app_dir in APPS}

    findings = set()
    for f, line, varname, namespace, key, err in scope_pass(file_data, catalogs):
        findings.add((str(f.relative_to(ROOT)), line, varname, namespace, key, err))
    for f, line, varname, namespace, key, err in interprocedural_pass(file_data, catalogs, import_map):
        findings.add((str(f.relative_to(ROOT)), line, varname, namespace, key, err))

    if not findings:
        print("i18n-Key-Resolution: ok")
        return 0

    print(f"i18n-Key-Resolution: {len(findings)} Fund(e)\n")
    for item in sorted(findings):
        f, line, varname, namespace, key, err = item
        print(f'{f}:{line}: {varname}("{key}") Namespace "{namespace}" -> {err}')
    print(
        "\nJeder Fund hier ist ein konkret aufgeloester Namespace, in dem der Key nachweislich "
        "fehlt - kein geratener Fehlalarm. Entweder den Key im passenden messages/<locale>/*.json "
        "ergaenzen oder die falsche t(...)/useTranslations(...)-Zuweisung korrigieren."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
