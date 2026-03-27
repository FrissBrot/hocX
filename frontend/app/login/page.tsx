import { AppShell } from "@/components/ui/app-shell";

export default function LoginPage() {
  return (
    <AppShell>
      <section className="panel">
        <div className="eyebrow">Auth placeholder</div>
        <h1>Login stays replaceable.</h1>
        <p className="muted">
          OIDC is not implemented in V1. This page exists to keep the frontend structure ready for a later auth flow.
        </p>
      </section>
    </AppShell>
  );
}

