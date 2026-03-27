import { AppShell } from "@/components/ui/app-shell";

export default function TemplateDetailPage({ params }: { params: { id: string } }) {
  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Template Detail</div>
        <h1>Template #{params.id}</h1>
        <div className="two-col">
          <article className="card">
            <h3>Structure</h3>
            <p className="muted">Template elements, sections and ordering will live here.</p>
          </article>
          <article className="card">
            <h3>Document Template</h3>
            <p className="muted">Versioned LaTeX template assignment belongs here.</p>
          </article>
        </div>
      </section>
    </AppShell>
  );
}

