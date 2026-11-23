import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { PasswordBreachedBanner } from "./password-breached-banner";

it("zeigt nichts, solange das Passwort nicht als geleakt markiert ist", () => {
  const { container } = render(<PasswordBreachedBanner breached={false} onChange={() => {}} />);
  expect(container.textContent).toBe("");
});

it("zeigt den Pflichthinweis ohne «Später» und öffnet die Passwortänderung per Tastatur", () => {
  const onChange = vi.fn();
  render(<PasswordBreachedBanner breached onChange={onChange} />);
  expect(screen.getByRole("alert").textContent).toContain("Datenleck");
  expect(screen.queryByRole("button", { name: "Später" })).toBeNull();
  const button = screen.getByRole("button", { name: "Passwort ändern" });
  button.focus();
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  expect(onChange).toHaveBeenCalledTimes(1);
});

it("im Admin-Panel nur der Hinweis, ohne Knopf", () => {
  render(<PasswordBreachedBanner breached />);
  expect(screen.getByRole("alert").textContent).toContain("admin_cli");
  expect(screen.queryByRole("button")).toBeNull();
});
