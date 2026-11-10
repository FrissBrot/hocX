"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { HikingTourElevationPreview } from "@/components/wanderplaner/hiking-tour-elevation-preview";
import { HikingTourLoadingLandscape } from "@/components/wanderplaner/hiking-tour-loading-landscape";
import { HikingTourMap } from "@/components/wanderplaner/hiking-tour-map";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatDate } from "@/lib/utils/format";
import { HikingTour, HikingTourSummary } from "@/types/api";

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: "neutral",
  analyzed: "info",
  reconnoitered: "warning",
  approved: "success",
};

type LatLon = { lat: number; lon: number };

export function HikingTourManager({ initialTours, canWrite }: { initialTours: HikingTourSummary[]; canWrite: boolean }) {
  const t = useTranslations("wanderplaner");
  const router = useRouter();
  const showToast = useToast();
  const [tours, setTours] = useState(initialTours);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tourDate, setTourDate] = useState("");
  const [start, setStart] = useState<LatLon | null>(null);
  const [end, setEnd] = useState<LatLon | null>(null);
  const [pendingField, setPendingField] = useState<"start" | "end">("start");
  const [saving, setSaving] = useState(false);
  const [showGpxImport, setShowGpxImport] = useState(false);
  const [gpxTitle, setGpxTitle] = useState("");
  const [gpxFile, setGpxFile] = useState<File | null>(null);
  const [importingGpx, setImportingGpx] = useState(false);

  function resetCreateForm() {
    setTitle("");
    setDescription("");
    setTourDate("");
    setStart(null);
    setEnd(null);
    setPendingField("start");
  }

  function handleMapClick(lat: number, lon: number) {
    if (pendingField === "start") {
      setStart({ lat, lon });
      setPendingField("end");
    } else {
      setEnd({ lat, lon });
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!start || !end) {
      showToast(t("manager.create.missingStartEnd"), "error");
      return;
    }
    setSaving(true);
    try {
      const created = await browserApiFetch<HikingTour>("/api/hiking-tours/planned", {
        method: "POST",
        signal: AbortSignal.timeout(600_000),
        body: JSON.stringify({
          title: title.trim(),
          description: description.trim() || null,
          tour_date: tourDate || null,
          start,
          end,
          via_points: [],
          routing_profile: "wanderwege_bevorzugen",
        }),
      });
      setTours((prev) => [
        { id: created.id, title: created.title, tour_date: created.tour_date, status: created.status, created_at: created.created_at, updated_at: created.updated_at },
        ...prev,
      ]);
      setShowCreate(false);
      resetCreateForm();
      showToast(t("manager.create.created"), "success");
      router.push(`/hiking-planner/${created.id}`);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("manager.create.error"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleGpxImport(event: FormEvent) {
    event.preventDefault();
    if (!gpxFile) {
      showToast(t("manager.gpx.missingFile"), "error");
      return;
    }
    setImportingGpx(true);
    try {
      const formData = new FormData();
      formData.append("title", gpxTitle.trim() || gpxFile.name.replace(/\.gpx$/i, ""));
      formData.append("file", gpxFile);
      const created = await browserApiFetch<HikingTour>("/api/hiking-tours/gpx-import?plan=true", { method: "POST", body: formData, signal: AbortSignal.timeout(600_000) });
      setShowGpxImport(false);
      setGpxTitle("");
      setGpxFile(null);
      showToast(t("manager.gpx.imported"), "success");
      router.push(`/hiking-planner/${created.id}`);
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : t("manager.gpx.error"), "error");
    } finally {
      setImportingGpx(false);
    }
  }

  const mapWaypoints = [
    ...(start ? [{ id: "start", kind: "START" as const, lat: start.lat, lon: start.lon }] : []),
    ...(end ? [{ id: "end", kind: "END" as const, lat: end.lat, lon: end.lon }] : []),
  ];

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("manager.title")}</h1>
          <p className="muted">{t("manager.subtitle")}</p>
        </div>
        {canWrite && (
          <div className="page-header-actions">
            <button type="button" className="button-secondary" onClick={() => setShowGpxImport(true)}>
              {t("manager.importGpx")}
            </button>
            <button type="button" className="button-primary" onClick={() => setShowCreate(true)}>
              {t("manager.newTour")}
            </button>
          </div>
        )}
      </div>

      <div>
        <DataToolbar title={t("manager.listTitle")} />
        <DataTable
          columns={[t("manager.columns.title"), t("manager.columns.date"), t("manager.columns.status"), t("manager.columns.elevationProfile")]}
          emptyMessage={t("manager.empty")}
        >
          {tours.map((tour) => (
            <tr key={tour.id} className="table-row-clickable" onClick={() => router.push(`/hiking-planner/${tour.id}`)}>
              <td>{tour.title}</td>
              <td>{tour.tour_date ? formatDate(tour.tour_date) : <span className="muted">–</span>}</td>
              <td>
                <Badge variant={STATUS_VARIANT[tour.status] ?? "neutral"}>{STATUS_VARIANT[tour.status] ? t(`status.${tour.status}`) : tour.status}</Badge>
              </td>
              <td><HikingTourElevationPreview points={tour.elevation_preview} /></td>
            </tr>
          ))}
        </DataTable>
      </div>

      <Modal
        open={showCreate}
        title={t("manager.newTour")}
        onClose={() => {
          setShowCreate(false);
          resetCreateForm();
        }}
        size="fullscreen"
        className="wanderplaner-create-modal"
      >
        <form className="wanderplaner-create-form" onSubmit={(event) => void handleCreate(event)}>
          <div className="wanderplaner-create-layout">
            <div className="wanderplaner-create-fields">
              <label className="field-stack">
                <span className="field-label">{t("fields.title")}</span>
                <input required value={title} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("fields.description")}</span>
                <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} />
              </label>
              <label className="field-stack">
                <span className="field-label">{t("fields.date")}</span>
                <DateInput value={tourDate} onChange={setTourDate} />
                <span className="field-help">{t("manager.create.optional")}</span>
              </label>
            </div>
            <div className="wanderplaner-create-map-section">
              <span className="field-label">{t("manager.create.startAndEnd")}</span>
              <span className="field-help">{t("manager.create.startAndEndHelp")}</span>
              <div className="wanderplaner-map-hint">
                <div className="wanderplaner-toggle-group">
                  <button
                    type="button"
                    className={pendingField === "start" ? "button-toggle button-toggle-active" : "button-toggle"}
                    onClick={() => setPendingField("start")}
                  >
                    {t("manager.create.setStart", { done: start ? "true" : "false" })}
                  </button>
                  <button
                    type="button"
                    className={pendingField === "end" ? "button-toggle button-toggle-active" : "button-toggle"}
                    onClick={() => setPendingField("end")}
                  >
                    {t("manager.create.setEnd", { done: end ? "true" : "false" })}
                  </button>
                </div>
                <span className="field-help">
                  {pendingField === "start" ? t("manager.create.clickToSetStart") : t("manager.create.clickToSetEnd")}
                </span>
              </div>
              <HikingTourMap waypoints={mapWaypoints} onMapClick={handleMapClick} className="wanderplaner-create-map" fitSwitzerland />
            </div>
          </div>
          <div className="modal-actions">
            <button
              type="button"
              className="button-ghost"
              onClick={() => {
                setShowCreate(false);
                resetCreateForm();
              }}
            >
              {t("actions.cancel")}
            </button>
            <button type="submit" className="button-primary wanderplaner-loading-button" disabled={saving || !start || !end} aria-busy={saving}>
              {saving && <HikingTourLoadingLandscape />}
              <span className="wanderplaner-loading-label">{saving ? t("manager.create.calculating") : t("manager.create.submit")}</span>
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={showGpxImport}
        title={t("manager.importGpx")}
        onClose={() => {
          setShowGpxImport(false);
          setGpxFile(null);
        }}
      >
        <form onSubmit={(event) => void handleGpxImport(event)}>
          <div className="grid">
            <p className="field-help">{t("manager.gpx.help")}</p>
            <label className="field-stack">
              <span className="field-label">{t("fields.title")}</span>
              <input value={gpxTitle} onChange={(event) => setGpxTitle(event.target.value)} placeholder={gpxFile?.name.replace(/\.gpx$/i, "") ?? ""} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("manager.gpx.file")}</span>
              <input type="file" accept=".gpx" required onChange={(event) => setGpxFile(event.target.files?.[0] ?? null)} />
            </label>
          </div>
          <div className="modal-actions">
            <button
              type="button"
              className="button-ghost"
              onClick={() => {
                setShowGpxImport(false);
                setGpxFile(null);
              }}
            >
              {t("actions.cancel")}
            </button>
            <button type="submit" className="button-primary wanderplaner-loading-button" disabled={importingGpx || !gpxFile} aria-busy={importingGpx}>
              {importingGpx && <HikingTourLoadingLandscape />}
              <span className="wanderplaner-loading-label">{importingGpx ? t("manager.gpx.importing") : t("manager.gpx.submit")}</span>
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
