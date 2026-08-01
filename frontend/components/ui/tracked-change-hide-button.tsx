"use client";

// Small "Ausblenden" (hide) control shown on any red tracked-change highlight - clicking
// it permanently accepts that one change (see the various accept-tracked-change backend
// routes: ProtocolTodoService.accept_tracked_change, list_snapshot_service.
// accept_tracked_list_entry/accept_tracked_row, AutosaveService.accept_tracked_changes),
// so only the current/new value keeps showing, normally, from then on.
export function TrackedChangeHideButton({ onAccept, title = "Änderung ausblenden" }: { onAccept: () => void; title?: string }) {
  return (
    <button
      type="button"
      className="tracked-accept-btn"
      title={title}
      aria-label={title}
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
