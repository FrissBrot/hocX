import { describe, expect, it } from "vitest";
import { emptyUserForm, isUserFormValid, userFormBlocker, userFormToPayload } from "./user-form-shared";

describe("Teilnehmerformular", () => {
  it("legt Teilnehmer ohne E-Mail, Passwort oder Vor-/Nachnamen an", () => {
    const form = { ...emptyUserForm(), display_name: "Person" };
    expect(isUserFormValid(form)).toBe(true);
    expect(userFormToPayload(form)).toMatchObject({ email: null, login_enabled: false });
    expect(userFormToPayload(form)).not.toHaveProperty("password");
  });

  it("verlangt E-Mail und ein ausreichend langes Passwort für einen neuen Login", () => {
    const form = { ...emptyUserForm(), display_name: "Person", login_enabled: true };
    expect(isUserFormValid(form)).toBe(false);
    expect(isUserFormValid({ ...form, email: "person@example.com" })).toBe(false);
    expect(isUserFormValid({ ...form, email: "person@example.com", password: "secure-password-123" })).toBe(true);
  });

  it("erhält beim Bearbeiten das Passwort eines bestehenden Logins", () => {
    const form = { ...emptyUserForm(), id: "person-id", display_name: "Person", email: "person@example.com", login_enabled: true };
    expect(isUserFormValid(form)).toBe(true);
    expect(userFormToPayload(form)).not.toHaveProperty("password");
  });

  it("nennt den Grund, warum Speichern gesperrt ist", () => {
    const form = { ...emptyUserForm(), login_enabled: true };
    expect(userFormBlocker(form)).toBe("displayName");
    expect(userFormBlocker({ ...form, display_name: "Person" })).toBe("email");
    expect(userFormBlocker({ ...form, display_name: "Person", email: "p@example.com" })).toBe("password");
    expect(userFormBlocker({ ...form, display_name: "Person", email: "p@example.com", password: "kurz" })).toBe("password");
    expect(userFormBlocker({ ...form, display_name: "Person", email: "p@example.com", password: "secure-password-123" })).toBeNull();
    // Zu kurzes Passwort ist auch beim Bearbeiten ohne Login-Wechsel ein Sperrgrund.
    expect(userFormBlocker({ ...emptyUserForm(), id: "x", display_name: "Person", password: "kurz" })).toBe("password");
    expect(userFormBlocker({ ...emptyUserForm(), display_name: "Person" }, { requireTenant: true })).toBe("tenant");
  });
});
