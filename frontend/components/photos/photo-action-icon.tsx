const paths = {
  album: "M3 5h18v14H3zM3 9h18",
  tag: "M3 3h8l10 10-8 8L3 11V3ZM7 7h.01",
  star: "m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z",
  download: "M12 3v12m-5-5 5 5 5-5M4 18v3h16v-3",
  share: "M8 12 17 6M8 12l9 6M8 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM22 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM22 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  delete: "M4 7h16M9 7V3h6v4M6 7l1 14h10l1-14M10 10v7m4-7v7",
  close: "m6 6 12 12M18 6 6 18",
  expand: "M14 4h6v6m0-6-7 7M10 20H4v-6m0 6 7-7",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4m8-4v4",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  back: "M15 5l-7 7 7 7",
  prev: "M15 5l-7 7 7 7",
  next: "M9 5l7 7-7 7",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  external: "M14 4h6v6M20 4l-9 9M18 14v5H5V6h5",
  live: "M12 12h.01M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8",
  place: "M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11ZM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
};
export function PhotoActionIcon({ name }: { name: keyof typeof paths }) {
  return <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
