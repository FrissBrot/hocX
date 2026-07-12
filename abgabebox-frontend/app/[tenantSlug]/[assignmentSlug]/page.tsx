import { notFound } from "next/navigation";
import Link from "next/link";

import { listElements } from "@/lib/api";

const COLORS = 4;

export default async function AssignmentElementsPage({
  params,
}: {
  params: { tenantSlug: string; assignmentSlug: string };
}) {
  const elements = await listElements(params.tenantSlug, params.assignmentSlug);
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
              href={`/${params.tenantSlug}/${params.assignmentSlug}/${element.element_ref}`}
            >
              <div className="card-title">
                <span className={`card-dot card-dot-${c}`} />
                {element.label}
              </div>
              {element.window_start || element.window_end ? (
                <div className="window">
                  {element.window_start ? `${element.window_start} – ` : ""}
                  {element.window_end}
                </div>
              ) : null}
            </Link>
          );
        })
      )}

      <Link href={`/${params.tenantSlug}`} className="back-btn">
        ← Zurück zur Übersicht
      </Link>
    </div>
  );
}
