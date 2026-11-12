import { expect, it } from "vitest";

import { listDeleteErrorMessage } from "./list-manager";
import { ApiError } from "@/lib/api/client";

// Audit 07, U4: die Löschsperre nennt die Fundstellen.
const t = (key: string, values?: Record<string, string | number | Date>) => `${key}:${JSON.stringify(values ?? {})}`;

it("nennt Bausteine und Protokolle aus der 409-Antwort", () => {
  const error = new ApiError("verknüpft", "conflict", 409, {
    code: "list_in_use",
    usages: [
      { kind: "element", name: "Ämtliliste" },
      { kind: "protocol", name: "Vorstand", number: "P-7" },
    ],
  });
  const message = listDeleteErrorMessage(error, t);
  expect(message).toContain("toasts.listInUse");
  expect(message).toContain("Ämtliliste");
  expect(message).toContain("P-7");
});

it("lässt andere Fehler unverändert", () => {
  expect(listDeleteErrorMessage(new ApiError("weg", "backend", 404, "Liste nicht gefunden"), t)).toBeNull();
  expect(listDeleteErrorMessage(new Error("x"), t)).toBeNull();
});
