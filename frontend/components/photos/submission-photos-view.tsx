"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { ContextPhoto } from "@/types/api";
import { RetryImage } from "@/components/ui/retry-image";

const PAGE_SIZE = 60;

type Page = { items: ContextPhoto[]; total: number };

// «Fotos aus Abgaben»: nur Bilder, die eine Kontext-Freigabe dem Konto zeigt (Backend
// context_visibility_service.visible_files_query). Inhalt und Vorschau laufen über
// /api/stored-files/*, die dieselbe Freigabe prüfen - nur lesen.
export function SubmissionPhotosView() {
  const t = useTranslations("photos.fromSubmissions");
  const [items, setItems] = useState<ContextPhoto[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async (skip: number) => {
    setLoading(true);
    try {
      const page = await browserApiFetch<Page>(`/api/context-files/submission-photos?skip=${skip}&limit=${PAGE_SIZE}`);
      setItems((current) => (skip === 0 ? page.items : [...current, ...page.items]));
      setTotal(page.total);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(0);
  }, [load]);

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
      </div>
      {failed ? <StatusBanner tone="error" message={t("loadFailed")} /> : null}
      {!loading && !failed && items.length === 0 ? <p className="muted">{t("empty")}</p> : null}
      {items.length > 0 ? (
        <>
          <p className="field-help">{t("count", { count: total })}</p>
          <div className="photo-grid">
            {items.map((photo) => (
              <figure key={photo.id} className="photo-tile">
                <a href={photo.content_url} target="_blank" rel="noreferrer" aria-label={photo.original_name}>
                  <RetryImage className="photo-tile-img" src={photo.thumbnail_url} alt={photo.original_name} loading="lazy" />
                </a>
                {photo.assignment_title ? <figcaption className="field-help">{photo.assignment_title}</figcaption> : null}
              </figure>
            ))}
          </div>
        </>
      ) : null}
      {items.length < total ? (
        <div className="table-actions table-actions-start">
          <button type="button" className="button-secondary" disabled={loading} onClick={() => void load(items.length)}>
            {t("loadMore")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
