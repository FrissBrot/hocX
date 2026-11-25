import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { GoogleDrivePicker } from "@/components/file-import/google-drive-picker";
import { requireSession } from "@/lib/api/server";
import { NONCE_HEADER } from "@/lib/csp";
import { can } from "@/lib/permissions";

// Google Picker für den Datei-Import (Google Drive, drive.file). Einzige Seite mit gelockerter CSP
// (lib/csp.ts, proxy.ts) - bewusst ohne App-Shell und ohne App-Links: hinein und hinaus nur mit
// vollem Seitenwechsel, damit die Lockerung nie für andere Ansichten gilt.
export default async function GooglePickerPage() {
  const session = await requireSession();
  if (!can(session, "files.import")) {
    redirect("/files");
  }
  const nonce = (await headers()).get(NONCE_HEADER) ?? "";
  return (
    <main className="file-import-picker-page">
      <GoogleDrivePicker nonce={nonce} />
    </main>
  );
}
