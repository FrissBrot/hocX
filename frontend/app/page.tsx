import { AppShell } from "@/components/ui/app-shell";
import { backendFetch } from "@/lib/api/client";

type HealthResponse = {
  status: string;
  service: string;
};

export default async function HomePage() {
  const health = await backendFetch<HealthResponse>("/api/health");

  return (
    <AppShell>
      <section className="panel hero">
        <div className="eyebrow">Docker-first starter</div>
        <h1 className="title">Templates, protocols and exports in one durable workspace.</h1>
        <p className="muted">
          This is the initial hocX shell with Next.js App Router on top of FastAPI, PostgreSQL and filesystem-backed
          assets.
        </p>
        <div className="grid stats">
          <article className="card">
            <div className="eyebrow">Frontend</div>
            <h3>Next.js + TypeScript</h3>
            <p className="muted">App Router layout with starter pages for templates, protocols and settings.</p>
          </article>
          <article className="card">
            <div className="eyebrow">Backend</div>
            <h3>FastAPI + SQLAlchemy</h3>
            <p className="muted">REST endpoints, service layer structure and Alembic migration base.</p>
          </article>
          <article className="card">
            <div className="eyebrow">Health</div>
            <h3>{health?.status ?? "unreachable"}</h3>
            <p className="muted">{health?.service ?? "backend not reachable yet"}</p>
          </article>
        </div>
      </section>
    </AppShell>
  );
}

