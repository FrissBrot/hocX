"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { browserApiFetch } from "@/lib/api/client";
import { apiErrorCode, type CloudNode } from "@/lib/files/file-import";
import { formatFileSize } from "@/lib/utils/format";

// Eigener Ordnerbaum (Entscheid E-4, kein Anbieter-Picker): live beim Anbieter gelesen, Ebene für
// Ebene nachgeladen. Ein gewählter Ordner umfasst alles darunter - Kinder erscheinen dann als
// mitgewählt (gesperrt). Bedienung: Tab über Aufklappknöpfe und Checkboxen, Leertaste/Enter.

type Branch = { nodes: CloudNode[]; cursor: string | null; loading: boolean; error: string | null };

type Props = {
  jobId: string;
  selected: Map<string, CloudNode>;
  onToggle: (node: CloudNode, checked: boolean) => void;
  onRequestTier: (tier: string) => void;
};

export function ImportCloudTree({ jobId, selected, onToggle, onRequestTier }: Props) {
  const t = useTranslations("fileImport");
  const [branches, setBranches] = useState<Record<string, Branch>>({});
  const [open, setOpen] = useState<Set<string>>(new Set());

  const load = useCallback(
    async (key: string, ref: string | null, cursor: string | null) => {
      setBranches((current) => ({
        ...current,
        [key]: { nodes: cursor ? current[key]?.nodes ?? [] : [], cursor: null, loading: true, error: null },
      }));
      try {
        // POST: das Lesen erneuert Tokens beim Anbieter (zustandsändernd, nie per GET)
        const page = await browserApiFetch<{ nodes: CloudNode[]; cursor: string | null }>(`/api/cloud-import/jobs/${jobId}/browse`, {
          method: "POST",
          body: JSON.stringify({ ref, cursor }),
        });
        setBranches((current) => ({
          ...current,
          [key]: { nodes: [...(cursor ? current[key]?.nodes ?? [] : []), ...page.nodes], cursor: page.cursor, loading: false, error: null },
        }));
      } catch (error) {
        const code = apiErrorCode(error) ?? "generic";
        setBranches((current) => ({ ...current, [key]: { nodes: current[key]?.nodes ?? [], cursor, loading: false, error: code } }));
      }
    },
    [jobId],
  );

  useEffect(() => {
    void load("", null, null);
  }, [load]);

  function toggleOpen(node: CloudNode) {
    const opening = !open.has(node.ref);
    if (opening && !branches[node.ref]) void load(node.ref, node.ref, null);
    setOpen((current) => {
      const next = new Set(current);
      if (opening) next.add(node.ref);
      else next.delete(node.ref);
      return next;
    });
  }

  function renderBranch(key: string, inherited: boolean, depth: number) {
    const branch = branches[key];
    if (!branch) return null;
    return (
      <ul className={depth === 0 ? "file-import-tree" : "file-import-tree-children"}>
        {branch.nodes.map((node) => (
          <TreeRow
            key={node.ref}
            node={node}
            open={open.has(node.ref)}
            inherited={inherited}
            checked={inherited || selected.has(node.ref)}
            onToggleOpen={() => toggleOpen(node)}
            onToggle={(checked) => onToggle(node, checked)}
            onRequestTier={onRequestTier}
          >
            {open.has(node.ref) ? renderBranch(node.ref, inherited || selected.has(node.ref), depth + 1) : null}
          </TreeRow>
        ))}
        {branch.loading ? (
          <li className="file-import-tree-status">
            <progress className="gallery-upload-progress" aria-label={t("cloud.loading")} />
          </li>
        ) : null}
        {branch.error ? (
          <li className="file-import-tree-status muted">
            {t.has(`cloud.errors.${branch.error}`) ? t(`cloud.errors.${branch.error}`) : t("errors.generic")}{" "}
            <button type="button" className="button-secondary button-ghost" onClick={() => void load(key, key || null, branch.cursor)}>
              {t("cloud.retry")}
            </button>
          </li>
        ) : null}
        {!branch.loading && !branch.error && branch.cursor ? (
          <li className="file-import-tree-status">
            <button type="button" className="button-secondary button-ghost" onClick={() => void load(key, key || null, branch.cursor)}>
              {t("cloud.loadMore")}
            </button>
          </li>
        ) : null}
        {!branch.loading && !branch.error && branch.nodes.length === 0 ? (
          <li className="file-import-tree-status muted">{t("cloud.emptyFolder")}</li>
        ) : null}
      </ul>
    );
  }

  return <div className="file-import-tree-shell" aria-label={t("cloud.treeLabel")} role="group">{renderBranch("", false, 0)}</div>;
}

type RowProps = {
  node: CloudNode;
  open: boolean;
  inherited: boolean;
  checked: boolean;
  onToggleOpen: () => void;
  onToggle: (checked: boolean) => void;
  onRequestTier: (tier: string) => void;
  children: React.ReactNode;
};

function TreeRow({ node, open, inherited, checked, onToggleOpen, onToggle, onRequestTier, children }: RowProps) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const folder = node.kind === "folder";
  const locked = !node.available;
  const name = node.label_key && t.has(`cloud.roots.${node.label_key}`) ? t(`cloud.roots.${node.label_key}`) : node.name;
  return (
    <li className="file-import-tree-item">
      <div className="file-import-tree-row">
        {folder && !locked ? (
          <button
            type="button"
            className="button-icon-soft button-icon-soft-sm"
            aria-expanded={open}
            aria-label={t(open ? "cloud.collapse" : "cloud.expand", { name })}
            onClick={onToggleOpen}
          >
            <span aria-hidden="true">{open ? "−" /* i18n-ok: Symbol */ : "+" /* i18n-ok: Symbol */}</span>
          </button>
        ) : (
          <span className="file-import-tree-spacer" aria-hidden="true" />
        )}
        {node.selectable ? (
          <label className="checkbox-row file-import-tree-label">
            <input type="checkbox" checked={checked} disabled={inherited} onChange={(event) => onToggle(event.target.checked)} />
            <span className="file-import-tree-name">{name}</span>
          </label>
        ) : (
          <span className="file-import-tree-name file-import-tree-group">{name}</span>
        )}
        <span className="file-import-tree-meta muted">
          {folder ? (node.child_count != null ? t("cloud.childCount", { count: node.child_count }) : null) : formatFileSize(node.size ?? 0, locale)}
          {!folder && node.file_kind === "other" ? ` · ${t("cloud.notImported")}` : null}
        </span>
        {locked && node.requires_tier ? (
          <button type="button" className="button-secondary button-ghost" onClick={() => onRequestTier(node.requires_tier!)}>
            {t("cloud.grantMore")}
          </button>
        ) : null}
      </div>
      {children}
    </li>
  );
}
