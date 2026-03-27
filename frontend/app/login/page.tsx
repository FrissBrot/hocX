"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { SessionInfo } from "@/types/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("superadmin@hocx.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [status, setStatus] = useState("Lokale Anmeldung ist aktiv. OIDC kann später hinter derselben Auth-Schicht ergänzt werden.");

  useEffect(() => {
    let cancelled = false;
    async function checkSession() {
      try {
        const session = await browserApiFetch<SessionInfo>("/api/auth/session");
        if (!cancelled && session.authenticated) {
          router.replace("/");
        }
      } catch {
        // ignore, login page should stay visible
      }
    }
    void checkSession();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("Anmeldung läuft...");
    try {
      await browserApiFetch<SessionInfo>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password })
      });
      router.replace("/");
      router.refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Login fehlgeschlagen");
    }
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="eyebrow">hocX Login</div>
        <h1>Mit lokalem Konto anmelden</h1>
        <p className="muted">Demo-Seed: `superadmin@hocx.local` mit Passwort `ChangeMe123!`.</p>
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">Passwort</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          <button type="submit" className="button-inline">
            Einloggen
          </button>
        </form>
        <p className="muted">{status}</p>
      </section>
    </main>
  );
}
