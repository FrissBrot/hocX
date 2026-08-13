"use client";

type Props = {
  offset: number;
  limit: number;
  total: number;
  onOffsetChange: (offset: number) => void;
};

// Shared offset/limit pagination footer - "X–Y von Z" plus Zurück/Weiter buttons.
// Originally lived inline in AdminErrorLog; extracted so every server-paginated
// admin list (Benutzer, Mandanten, Domains, Fehlerprotokoll) uses the same widget.
export function Pagination({ offset, limit, total, onOffsetChange }: Props) {
  if (total === 0) return null;

  const from = offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="table-actions" style={{ justifyContent: "space-between" }}>
      <span className="muted">
        {from}–{to} von {total}
      </span>
      <div className="table-actions-start">
        <button
          type="button"
          className="button-inline button-ghost"
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
        >
          Zurück
        </button>
        <button
          type="button"
          className="button-inline button-ghost"
          disabled={to >= total}
          onClick={() => onOffsetChange(offset + limit)}
        >
          Weiter
        </button>
      </div>
    </div>
  );
}
