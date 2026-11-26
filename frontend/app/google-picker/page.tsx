import { headers } from "next/headers";

import { GoogleDrivePicker } from "@/components/file-import/google-drive-picker";
import { NONCE_HEADER } from "@/lib/csp";

// Google Picker für den Datei-Import (Google Drive, drive.file) auf eigener Origin
// (CLOUD_IMPORT_PICKER_DOMAIN, Security-Review 1.6): keine hocX-Sitzung, keine App-Shell, keine
// App-Links. Zugang nur über das einmalige Ticket im Fragment (backend picker_tickets.py); proxy.ts
// liefert die Seite nur auf dieser Origin aus und nur hier mit gelockerter CSP.
export const dynamic = "force-dynamic";

export default async function GooglePickerPage() {
  const nonce = (await headers()).get(NONCE_HEADER) ?? "";
  return (
    <main className="file-import-picker-page">
      <GoogleDrivePicker nonce={nonce} />
    </main>
  );
}
