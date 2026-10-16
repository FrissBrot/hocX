import { describe, expect, it } from "vitest";

import { PROFILE_IMAGE_MAX_BYTES, profileImageProblem } from "./profile-image";

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
