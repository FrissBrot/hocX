export const authFiles = {
  admin: "e2e/.auth/admin.json",
  writer: "e2e/.auth/writer.json",
  reader: "e2e/.auth/reader.json",
  tenantTwo: "e2e/.auth/admin-tenant-two.json",
  // Platform admin (PlatformAdmin, /api/admin/auth/*) - a completely separate login system
  // from the tenant AppUser sessions above: password + passkey only (AdminMfaService).
  platformAdmin: "e2e/.auth/platform-admin.json",
};

// Software-Passkey des Plattform-Admins (soft-passkey.ts), damit ein späterer Lauf sich wieder anmeldet.
export const platformAdminPasskeyFile = "e2e/.auth/platform-admin-passkey.json";

// Eigener Software-Passkey je Spec, die Admin-Aktionen per Passkey bestätigt (auth.setup.ts legt sie
// als weitere Passkeys des Plattform-Admins an). Specs laufen parallel in mehreren Workern: teilten
// sie sich einen Passkey, verwendete ein Worker einen Signaturzähler, den ein anderer schon
// verbraucht hatte - das Backend sperrt den Passkey dann als möglichen Klon (admin_mfa_service.py,
// Review L8), und alle weiteren Bestätigungen scheitern mit passkey_not_registered.
// Innerhalb einer Datei laufen die Tests nacheinander (fullyParallel: false).
export const platformAdminSpecPasskeys = ["admin-passkey", "security-admin", "admin-backups", "storage-quota", "cloud-imports"] as const;
export type PlatformAdminSpecPasskey = (typeof platformAdminSpecPasskeys)[number];
export function platformAdminSpecPasskeyFile(spec: PlatformAdminSpecPasskey): string {
  return `e2e/.auth/platform-admin-passkey-${spec}.json`;
}

// TOTP-Secrets der Mandantenkonten aus auth.setup.ts (nur Laufzeit, e2e/.auth ist gitignored), damit
// eine Spec eine abgelaufene Bestätigung (step_up_required, 15 min) per TOTP erneuern kann.
export const tenantTotpFile = "e2e/.auth/tenant-totp.json";
