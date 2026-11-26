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

type TranslateProfileImage = (key: string, values?: Record<string, string | number>) => string;

// Codes der Backend-Prüfung (tenant_service._normalize_tenant_profile_image /
// apply_tenant_profile_image) -> Schlüssel unter common.profileImage
const PROFILE_IMAGE_ERROR_KEYS: Record<string, string> = {
  profile_image_invalid: "invalidType",
  profile_image_too_large: "tooLarge",
  profile_image_too_many_pixels: "tooManyPixels",
};

/** Übersetzte Meldung zu einem abgelehnten Profilbild (`tCommon` = useTranslations("common")), sonst null. */
export function profileImageErrorMessage(error: unknown, tCommon: TranslateProfileImage): string | null {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const { code, params } = detail as { code?: unknown; params?: { max_megapixels?: unknown } };
  if (typeof code !== "string" || !Object.prototype.hasOwnProperty.call(PROFILE_IMAGE_ERROR_KEYS, code)) return null;
  const max = typeof params?.max_megapixels === "number" ? params.max_megapixels : 40;
  return tCommon(`profileImage.${PROFILE_IMAGE_ERROR_KEYS[code]}`, { max });
}
