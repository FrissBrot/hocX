import { expect, it } from "vitest";
import { canCollectAsSubmission } from "./use-create-submission-from-todo";

// Sichtbarkeit von «Als Abgabe einsammeln» (Pendenz-Dialog und Menü der Pendenz im Protokoll)
it("offers collecting only open todos that are no submission, no package item and not pending delete", () => {
  expect(canCollectAsSubmission({ todo_status_code: "open" })).toBe(true);
  expect(canCollectAsSubmission({ todo_status_code: "in_progress", submission_assignment_id: null })).toBe(true);
  expect(canCollectAsSubmission({ todo_status_code: "open", submission_assignment_id: "sa-1" })).toBe(false);
  expect(canCollectAsSubmission({ todo_status_code: "done" })).toBe(false);
  expect(canCollectAsSubmission({ todo_status_code: "cancelled" })).toBe(false);
  expect(canCollectAsSubmission({ todo_status_code: "open", pending_delete: true })).toBe(false);
  expect(canCollectAsSubmission({ todo_status_code: "open", task_package_id: "pkg-1" })).toBe(false);
});
