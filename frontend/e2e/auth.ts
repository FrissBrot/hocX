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

// TOTP-Secrets der Mandantenkonten aus auth.setup.ts (nur Laufzeit, e2e/.auth ist gitignored), damit
// eine Spec eine abgelaufene Bestätigung (step_up_required, 15 min) per TOTP erneuern kann.
export const tenantTotpFile = "e2e/.auth/tenant-totp.json";
