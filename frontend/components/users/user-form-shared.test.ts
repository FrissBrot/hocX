import { describe, expect, it } from "vitest";
import { emptyUserForm, isUserFormValid, userFormToPayload } from "./user-form-shared";

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
});
