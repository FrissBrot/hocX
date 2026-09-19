// Full-window hint shown while files are dragged over a page that acts as one big dropzone
// (see useFileDrop). Purely visual - pointer-events are off so it never swallows the drop.
export function FileDropOverlay({ active, title, hint }: { active: boolean; title: string; hint?: string }) {
  if (!active) return null;
  return (
    <div className="file-drop-overlay" role="presentation" aria-hidden="true">
      <div className="file-drop-overlay-card">
        <span className="gallery-upload-dropzone-badge">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M12 16V5m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M5 15v2.5A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <p className="gallery-upload-dropzone-title">{title}</p>
        {hint && <p className="muted">{hint}</p>}
      </div>
    </div>
  );
}
