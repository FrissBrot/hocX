import { StructuredListValueType } from "@/types/api";

export function ListValueTypeIcon({ type }: { type: StructuredListValueType }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {type === "text" ? <path d="M5 5h14M12 5v14" />
        : type === "event" ? <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M8 3v4M16 3v4M4 10h16" /></>
        : type === "participant" ? <><circle cx="12" cy="7" r="3" /><path d="M5 20v-2a7 7 0 0 1 14 0v2" /></>
        : <><circle cx="9" cy="7" r="3" /><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 4a3 3 0 0 1 0 6M21 20v-2a6 6 0 0 0-4-5" /></>}
    </svg>
  );
}
