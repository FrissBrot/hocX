import { redirect } from "next/navigation";

import { SubmissionPhotosView } from "@/components/photos/submission-photos-view";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession } from "@/lib/api/server";
import { can } from "@/lib/permissions";

// «Fotos aus Abgaben» (Plan «Berechtigungen», Phase 5): Bilder, die der Verein über
// Kontext-Freigaben für Teilnehmende freigibt - auch ohne Rollenrecht «Fotos ansehen».
export default async function SubmissionPhotosPage() {
  const session = await requireSession();
  if (!can(session, "meetings.read")) {
    redirect("/");
  }

  return (
    <AppShell initialSession={session}>
      <section className="panel">
        <SubmissionPhotosView />
      </section>
    </AppShell>
  );
}
