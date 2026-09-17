export const authFiles = {
  admin: "e2e/.auth/admin.json",
  writer: "e2e/.auth/writer.json",
  reader: "e2e/.auth/reader.json",
  tenantTwo: "e2e/.auth/admin-tenant-two.json",
  // Platform admin (PlatformAdmin, /api/admin/auth/*) - a completely separate login system
  // from the tenant AppUser sessions above, gated by AdminMfaService rather than
  // MfaService (see auth.setup.ts for why both need their own TOTP enrolment dance).
  platformAdmin: "e2e/.auth/platform-admin.json",
};
