import { notFound } from "next/navigation";
import Link from "next/link";

import { listElements } from "@/lib/api";
import { formatDate } from "@/lib/format";

const COLORS = 4;

export default async function AssignmentElementsPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; assignmentSlug: string }>;
}) {
  const { tenantSlug, assignmentSlug } = await params;
  const elements = await listElements(tenantSlug, assignmentSlug);
  if (elements === null) {
    notFound();
  }

  return (
    <div>
      <h1>Elemente</h1>
      <p className="muted">Wähle dein Element aus, um die Datei hochzuladen.</p>

      {elements.length === 0 ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>Aktuell sind keine Elemente offen.</p>
        </div>
      ) : (
        elements.map((element, i) => {
          const c = i % COLORS;
          return (
            <Link
              key={element.element_ref}
              className={`card card-link card-colored-${c}`}
              href={`/${tenantSlug}/${assignmentSlug}/${element.element_ref}`}
            >
              <div className="card-title">
                <span className={`card-dot card-dot-${c}`} />
                {element.label}
              </div>
              {element.window_start || element.window_end ? (
                <div className="window">
                  {element.window_start && element.window_end
                    ? `${formatDate(element.window_start)} – ${formatDate(element.window_end)}`
                    : element.window_start
                      ? `ab ${formatDate(element.window_start)}`
                      : `bis ${formatDate(element.window_end)}`}
                </div>
              ) : null}
              {element.uploaded_count > 0 ? (
                <div className="window">
                  {element.uploaded_count} Datei{element.uploaded_count === 1 ? "" : "en"} bereits hochgeladen
                </div>
              ) : null}
            </Link>
          );
        })
      )}

      <Link href={`/${tenantSlug}`} className="back-btn">
        ← Zurück zur Übersicht
      </Link>
    </div>
  );
}
