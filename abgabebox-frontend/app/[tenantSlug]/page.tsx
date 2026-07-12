import { notFound } from "next/navigation";
import Link from "next/link";

import { listAssignments } from "@/lib/api";

const COLORS = 4;

export default async function TenantAssignmentsPage({ params }: { params: { tenantSlug: string } }) {
  const assignments = await listAssignments(params.tenantSlug);
  if (assignments === null) {
    notFound();
  }

  return (
    <div>
      <h1>Offene Abgaben</h1>
      <p className="muted">Wähle eine Abgabe aus, um deine Datei einzureichen.</p>

      {assignments.length === 0 ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>Aktuell sind keine Abgaben offen.</p>
        </div>
      ) : (
        assignments.map((assignment, i) => {
          const c = i % COLORS;
          return (
            <Link
              key={assignment.public_slug}
              className={`card card-link card-colored-${c}`}
              href={`/${params.tenantSlug}/${assignment.public_slug}`}
            >
              <div className="card-title">
                <span className={`card-dot card-dot-${c}`} />
                {assignment.title}
              </div>
              {assignment.description ? <div className="muted" style={{ margin: 0, paddingLeft: 16 }}>{assignment.description}</div> : null}
            </Link>
          );
        })
      )}
    </div>
  );
}
