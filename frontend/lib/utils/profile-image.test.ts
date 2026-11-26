import { describe, expect, it } from "vitest";

import { PROFILE_IMAGE_MAX_BYTES, profileImageErrorMessage, profileImageProblem } from "./profile-image";

describe("profileImageProblem", () => {
  it("lehnt SVG und andere Formate ab, die das Backend nicht mehr annimmt", () => {
    expect(profileImageProblem({ type: "image/svg+xml", size: 100 })).toBe("invalidType");
    expect(profileImageProblem({ type: "text/html", size: 100 })).toBe("invalidType");
  });
  it("lehnt Bilder ueber 5 MB ab", () => {
    expect(profileImageProblem({ type: "image/png", size: PROFILE_IMAGE_MAX_BYTES + 1 })).toBe("tooLarge");
  });
  it("akzeptiert JPEG, PNG, GIF und WebP", () => {
    for (const type of ["image/png", "image/jpeg", "image/gif", "image/webp"]) {
      expect(profileImageProblem({ type, size: 1024 })).toBeNull();
    }
  });
});

describe("profileImageErrorMessage", () => {
  const tCommon = (key: string, values?: Record<string, string | number>) => (values ? `${key}:${JSON.stringify(values)}` : key);

  it("übersetzt die Ablehnung des Backends über den Code (über 40 MP hiess es vorher «muss ein JPEG… sein»)", () => {
    const error = { detail: { code: "profile_image_too_many_pixels", message: "…", params: { max_megapixels: 40 } } };
    expect(profileImageErrorMessage(error, tCommon)).toBe('profileImage.tooManyPixels:{"max":40}');
    expect(profileImageErrorMessage({ detail: { code: "profile_image_invalid" } }, tCommon)).toContain("profileImage.invalidType");
    expect(profileImageErrorMessage({ detail: { code: "toString" } }, tCommon)).toBeNull();
    expect(profileImageErrorMessage(new Error("Netzwerk"), tCommon)).toBeNull();
  });
});
