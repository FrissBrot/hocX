import { notFound, redirect } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { backendFetchWithSession, requireSession } from "@/lib/api/server";
import { can, featureAccess } from "@/lib/permissions";
import type { UploadJobDetail } from "@/types/api";

import { UploadHistoryView } from "./upload-history-view";
import { UploadJobDetailView } from "./upload-job-detail-view";

// Server-Seiten des Upload-Verlaufs (Fotos und Ablage teilen sich die Komponenten). Die Rechte prüft
// das Backend je Kanal; die Seite selbst verlangt nur das Leserecht des Bereichs.

export async function UploadHistoryPage({ area }: { area: "photos" | "files" }) {
  const session = await requireSession();
  if (!can(session, area === "photos" ? "photos.read" : "files.read")) redirect("/");
  const canSeeAll = can(session, area === "photos" ? "photos.manage" : "files.manage");
  return (
    <AppShell initialSession={session}>
      <section className="upload-history-shell">
        <UploadHistoryView area={area} canSeeAll={canSeeAll} />
      </section>
    </AppShell>
  );
}

export async function UploadJobPage({ area, id }: { area: "photos" | "files"; id: string }) {
  const session = await requireSession();
  if (!can(session, area === "photos" ? "photos.read" : "files.read")) redirect("/");
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const job = await backendFetchWithSession<UploadJobDetail>(`/api/upload-jobs/${id}`);
  if (!job) notFound();
  return (
    <AppShell initialSession={session}>
      <section className="upload-history-shell">
        <UploadJobDetailView
          area={area}
          job={job}
          canManagePhotos={can(session, "photos.manage")}
          canShare={can(session, "sharing.public") && featureAccess(session, "photo_sharing") === "full"}
          canManageSettings={can(session, "settings.manage")}
        />
      </section>
    </AppShell>
  );
}
