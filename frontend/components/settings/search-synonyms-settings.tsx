"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { KeywordInput } from "@/components/ui/keyword-input";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";

export type SearchSynonyms = { groups: string[][]; builtin: string[][] };

const MAX_GROUPS = 200;

type Row = { key: number; words: string[] };

/**
 * Mandanteneigene Synonyme der Suche (Fotos und Ablage): Gruppen gleichbedeutender Wörter.
 * Formular mit «Speichern» (mehrere Gruppen werden gemeinsam ersetzt). Der eingebaute Grundstock
 * ist nur zum Nachschlagen aufklappbar.
 */
export function SearchSynonymsSettings({ initial }: { initial: SearchSynonyms }) {
  const t = useTranslations("tenantSettings.searchSynonyms");
  const showToast = useToast();
  const [nextKey, setNextKey] = useState(initial.groups.length + 1);
  const [rows, setRows] = useState<Row[]>(() => initial.groups.map((words, index) => ({ key: index + 1, words })));
  const [saved, setSaved] = useState(JSON.stringify(initial.groups));
  const [busy, setBusy] = useState(false);
  const current = rows.map((row) => row.words).filter((words) => words.length > 0);
  const dirty = JSON.stringify(current) !== saved;
  const incomplete = rows.some((row) => row.words.length === 1);

  function update(key: number, words: string[]) {
    setRows((existing) => existing.map((row) => (row.key === key ? { ...row, words } : row)));
  }

  function addGroup() {
    setRows((existing) => [...existing, { key: nextKey, words: [] }]);
    setNextKey((key) => key + 1);
  }

  function removeGroup(key: number) {
    setRows((existing) => existing.filter((row) => row.key !== key));
  }

  async function save() {
    if (busy) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<SearchSynonyms>("/api/search-synonyms", {
        method: "PUT",
        body: JSON.stringify({ groups: current }),
      });
      const groups = result?.groups ?? current;
      setRows(groups.map((words, index) => ({ key: nextKey + index, words })));
      setNextKey((key) => key + groups.length);
      setSaved(JSON.stringify(groups));
      showToast(t("savedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("saveError"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="section-stack search-synonyms">
      <section className="section-stack">
        <h2 className="search-synonyms-title">{t("ownTitle")}</h2>
        <p className="muted">{t("ownIntro")}</p>
        {rows.length === 0 ? <p className="muted">{t("empty")}</p> : null}
        <ol className="search-synonyms-list">
          {rows.map((row, index) => (
            <li key={row.key} className="search-synonyms-row">
              <KeywordInput
                value={row.words}
                onChange={(words) => update(row.key, words)}
                label={t("groupLabel", { number: index + 1 })}
                placeholder={t("groupPlaceholder")}
              />
              <button
                type="button"
                className="button-icon-soft button-icon-soft-danger"
                aria-label={t("removeGroup", { number: index + 1 })}
                title={t("removeGroup", { number: index + 1 })}
                onClick={() => removeGroup(row.key)}
              >
                <ActionIcon name="delete" />
              </button>
            </li>
          ))}
        </ol>
        {incomplete ? <p className="field-help">{t("needsTwo")}</p> : null}
        <div className="search-synonyms-actions">
          <button type="button" className="button-secondary" onClick={addGroup} disabled={busy || rows.length >= MAX_GROUPS}>
            {t("addGroup")}
          </button>
          <button type="button" className="button-primary" onClick={() => void save()} disabled={busy || !dirty}>
            {busy ? t("saving") : t("save")}
          </button>
        </div>
      </section>

      <details className="search-synonyms-builtin">
        <summary>{t("builtinTitle", { count: initial.builtin.length })}</summary>
        <p className="muted">{t("builtinIntro")}</p>
        <ul className="search-synonyms-builtin-list">
          {initial.builtin.map((group) => (
            <li key={group.join("|")}>{group.join(" · ")}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
