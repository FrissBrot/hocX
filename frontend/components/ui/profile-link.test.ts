import { describe, expect, it } from "vitest";
import { profileTabFromLink } from "./app-shell";

describe("Direktlink ins Profil (Link im Fuss der Benachrichtigungs-Mails)", () => {
  it("öffnet den Reiter Benachrichtigungen, sonst das Profil", () => {
    expect(profileTabFromLink("notifications")).toBe("benachrichtigungen");
    expect(profileTabFromLink("profile")).toBe("profil");
    expect(profileTabFromLink("<script>")).toBe("profil");
  });
});
