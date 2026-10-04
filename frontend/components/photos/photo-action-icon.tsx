const paths = {
  album: "M3 5h18v14H3zM3 9h18",
  tag: "M3 3h8l10 10-8 8L3 11V3ZM7 7h.01",
  star: "m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z",
  download: "M12 3v12m-5-5 5 5 5-5M4 18v3h16v-3",
  share: "M8 12 17 6M8 12l9 6M8 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM22 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM22 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  delete: "M4 7h16M9 7V3h6v4M6 7l1 14h10l1-14M10 10v7m4-7v7",
  close: "m6 6 12 12M18 6 6 18",
  expand: "M14 4h6v6m0-6-7 7M10 20H4v-6m0 6 7-7",
};
export function PhotoActionIcon({ name }: { name: keyof typeof paths }) {
  return <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
