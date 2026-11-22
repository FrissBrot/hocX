"use client";

import { useTranslations } from "next-intl";

import { DateInput } from "@/components/ui/date-input";
import { ReorderButtons } from "@/components/ui/reorder-buttons";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Select } from "@/components/ui/select";
import { TagInput } from "@/components/ui/tag-input";
import type { ImportRule, ImportRuleAction, ImportRuleError } from "@/lib/files/file-import";

export type AlbumOption = { id: string; name: string };

type Props = {
  rule: ImportRule;
  index: number;
  count: number;
  matches: number | undefined;
  errors: ImportRuleError[];
  folders: string[];
  albums: AlbumOption[];
  tagSuggestions: string[];
  readOnly: boolean;
  onChange: (rule: ImportRule) => void;
  onMove: (from: number, to: number) => void;
  onRemove: () => void;
};

const ACTIONS: ImportRuleAction[] = ["add_tags", "set_date", "skip", "add_to_album", "folder_to_album"];

export function ImportRuleCard({
  rule, index, count, matches, errors, folders, albums, tagSuggestions, readOnly, onChange, onMove, onRemove,
}: Props) {
  const t = useTranslations("fileImport");
  const title = t("rules.ruleTitle", { number: index + 1 });
  const errorFor = (field: string) => errors.find((error) => error.field === field);

  function setMatch(patch: Partial<ImportRule["match"]>) {
    onChange({ ...rule, match: { ...rule.match, ...patch } });
  }
  function setAction(patch: Partial<ImportRule["action"]>) {
    onChange({ ...rule, action: { ...rule.action, ...patch } });
  }

  function errorLine(field: string) {
    const error = errorFor(field);
    if (!error) return null;
    const key = `rules.errors.${error.code}`;
    return <span className="field-help file-import-rule-error" role="alert">{t.has(key) ? t(key) : t("rules.errors.invalid")}</span>;
  }

  const folderOptions = folders.map((folder) => ({ id: folder, label: folder }));

  return (
    <fieldset className="file-import-rule" disabled={readOnly}>
      <legend className="file-import-rule-head">
        <span className="file-import-rule-title">{title}</span>
        <span className="muted">{matches === undefined ? "" : t("rules.matches", { count: matches })}</span>
      </legend>
      <div className="file-import-rule-tools">
        <label className="checkbox-row">
          <input type="checkbox" checked={rule.enabled} onChange={(event) => onChange({ ...rule, enabled: event.target.checked })} />
          {t("rules.enabled")}
        </label>
        <ReorderButtons itemKey={rule.id} name={title} index={index} count={count} onMove={onMove} disabled={readOnly} />
        <button type="button" className="button-icon-soft button-icon-soft-danger" aria-label={t("rules.remove", { name: title })} onClick={onRemove}>
          ✕
        </button>
      </div>
      {errorLine("id")}
      {errorLine("rule")}

      <div className="file-import-rule-grid">
        <span className="file-import-rule-section">{t("rules.when")}</span>
        <label className="field-stack">
          <span className="field-label">{t("rules.folder")}</span>
          <SearchableSelect
            options={folderOptions}
            getId={(option) => option.id}
            getLabel={(option) => option.label}
            value={rule.match.folder ?? null}
            onChange={(option) => setMatch({ folder: option?.id ?? null })}
            nullLabel={t("rules.anyFolder")}
            placeholder={t("rules.anyFolder")}
            searchPlaceholder={t("rules.searchFolder")}
            emptyLabel={t("rules.noFolders")}
            disabled={readOnly}
          />
          {errorLine("folder")}
        </label>
        <label className="field-stack">
          <span className="field-label">{t("rules.pathGlob")}</span>
          <input
            value={rule.match.path_glob ?? ""}
            onChange={(event) => setMatch({ path_glob: event.target.value })}
            spellCheck={false}
            maxLength={300}
          />
          <span className="field-help">{t("rules.pathGlobHelp")}</span>
          {errorLine("path_glob")}
        </label>
        <label className="field-stack">
          <span className="field-label">{t("rules.nameRegex")}</span>
          <input
            value={rule.match.name_regex ?? ""}
            onChange={(event) => setMatch({ name_regex: event.target.value })}
            spellCheck={false}
            maxLength={200}
          />
          <span className="field-help">{t("rules.nameRegexHelp")}</span>
          {errorLine("name_regex")}
        </label>
        <label className="field-stack">
          <span className="field-label">{t("rules.kind")}</span>
          <Select value={rule.match.kind} onChange={(event) => setMatch({ kind: event.target.value as ImportRule["match"]["kind"] })}>
            <option value="all">{t("options.types.all")}</option>
            <option value="images">{t("options.types.images")}</option>
            <option value="documents">{t("options.types.documents")}</option>
          </Select>
        </label>
        <label className="checkbox-row">
          <input type="checkbox" checked={rule.match.case_sensitive} onChange={(event) => setMatch({ case_sensitive: event.target.checked })} />
          {t("rules.caseSensitive")}
        </label>

        <span className="file-import-rule-section">{t("rules.then")}</span>
        <label className="field-stack">
          <span className="field-label">{t("rules.action")}</span>
          <Select value={rule.action.type} onChange={(event) => setAction({ type: event.target.value as ImportRuleAction })}>
            {ACTIONS.map((action) => (
              <option key={action} value={action}>{t(`rules.actions.${action}`)}</option>
            ))}
          </Select>
          {errorLine("action")}
        </label>
        {rule.action.type === "add_tags" ? (
          <label className="field-stack">
            <span className="field-label">{t("rules.tags")}</span>
            <TagInput
              value={(rule.action.tags ?? []).join(", ")}
              onChange={(value) => setAction({ tags: value.split(",").map((tag) => tag.trim()).filter(Boolean) })}
              suggestions={tagSuggestions}
              placeholder={t("rules.tagsPlaceholder")}
              readOnly={readOnly}
              offerCreate
            />
            {errorLine("tags")}
          </label>
        ) : null}
        {rule.action.type === "set_date" ? (
          <label className="field-stack">
            <span className="field-label">{t("rules.date")}</span>
            <DateInput value={rule.action.date ?? ""} onChange={(value) => setAction({ date: value || null })} />
            <span className="field-help">{t("rules.dateHelp")}</span>
            {errorLine("date")}
          </label>
        ) : null}
        {rule.action.type === "add_to_album" ? (
          <>
            <label className="field-stack">
              <span className="field-label">{t("rules.existingAlbum")}</span>
              <SearchableSelect
                options={albums}
                getId={(album) => album.id}
                getLabel={(album) => album.name}
                value={rule.action.album_id ?? null}
                onChange={(album) => setAction({ album_id: album?.id ?? null })}
                nullLabel={t("rules.newAlbumOption")}
                placeholder={t("rules.newAlbumOption")}
                searchPlaceholder={t("rules.searchAlbum")}
                emptyLabel={t("rules.noAlbums")}
                disabled={readOnly}
              />
            </label>
            {rule.action.album_id ? null : (
              <label className="field-stack">
                <span className="field-label">{t("rules.newAlbumName")}</span>
                <input value={rule.action.album_name ?? ""} maxLength={120} onChange={(event) => setAction({ album_name: event.target.value })} />
              </label>
            )}
            {errorLine("album")}
            <span className="field-help">{t("rules.imagesOnly")}</span>
          </>
        ) : null}
        {rule.action.type === "folder_to_album" ? (
          <label className="field-stack">
            <span className="field-label">{t("rules.folderLevel")}</span>
            <Select value={rule.action.folder_level ?? "parent"} onChange={(event) => setAction({ folder_level: event.target.value as "parent" | "top" })}>
              <option value="parent">{t("rules.folderLevels.parent")}</option>
              <option value="top">{t("rules.folderLevels.top")}</option>
            </Select>
            <span className="field-help">{t("rules.imagesOnly")}</span>
          </label>
        ) : null}
        {rule.action.type === "skip" ? <span className="field-help">{t("rules.skipHelp")}</span> : null}
      </div>
    </fieldset>
  );
}
