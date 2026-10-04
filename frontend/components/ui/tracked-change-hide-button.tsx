"use client";

import { useTranslations } from "next-intl";

// Small "Ausblenden" (hide) control shown on any red tracked-change highlight - clicking
// it permanently accepts that one change (see the various accept-tracked-change backend
// routes: ProtocolTodoService.accept_tracked_change, list_snapshot_service.
// accept_tracked_list_entry/accept_tracked_row, AutosaveService.accept_tracked_changes),
// so only the current/new value keeps showing, normally, from then on.
export function TrackedChangeHideButton({ onAccept, title }: { onAccept: () => void; title?: string }) {
  const t = useTranslations("protocols");
  const resolvedTitle = title ?? t("trackedChange.hide");
  return (
    <button
      type="button"
      className="tracked-accept-btn"
      title={resolvedTitle}
      aria-label={resolvedTitle}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onAccept();
      }}
    >
      ⊘
    </button>
  );
}
