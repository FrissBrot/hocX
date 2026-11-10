// Clientseitige Vorpruefung fuer Mandanten-Profilbilder. Das Backend akzeptiert seit Audit
// MAIN-SEC-002 nur noch JPEG/PNG/GIF/WebP bis 5 MB (SVG nicht mehr, siehe
// backend/app/services/tenant_service.py::apply_tenant_profile_image). Hier frueh und mit
// uebersetzter Meldung ablehnen statt erst nach dem Speichern mit der Backend-Meldung.
export const PROFILE_IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"] as const;
export const PROFILE_IMAGE_ACCEPT = PROFILE_IMAGE_TYPES.join(",");
export const PROFILE_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

export type ProfileImageProblem = "invalidType" | "tooLarge";

export function profileImageProblem(file: Pick<File, "type" | "size">): ProfileImageProblem | null {
  if (!(PROFILE_IMAGE_TYPES as readonly string[]).includes(file.type)) return "invalidType";
  if (file.size > PROFILE_IMAGE_MAX_BYTES) return "tooLarge";
  return null;
}
