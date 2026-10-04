type FileKind = "document" | "pdf" | "spreadsheet" | "presentation" | "archive" | "image" | "audio" | "video" | "code" | "generic";

const EXTENSION_KINDS: Record<string, FileKind> = {
  doc: "document", docx: "document", odt: "document", rtf: "document", txt: "document", md: "document",
  pdf: "pdf",
  xls: "spreadsheet", xlsx: "spreadsheet", ods: "spreadsheet", csv: "spreadsheet",
  ppt: "presentation", pptx: "presentation", odp: "presentation",
  zip: "archive", rar: "archive", "7z": "archive", tar: "archive", gz: "archive",
  jpg: "image", jpeg: "image", png: "image", gif: "image", webp: "image", svg: "image", heic: "image",
  mp3: "audio", wav: "audio", m4a: "audio", ogg: "audio", flac: "audio",
  mp4: "video", mov: "video", avi: "video", webm: "video", mkv: "video",
  json: "code", xml: "code", html: "code", css: "code", js: "code", ts: "code", py: "code",
};

export function FileTypeIcon({ name }: { name: string }) {
  const dot = name.lastIndexOf(".");
  const extension = dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
  const kind = EXTENSION_KINDS[extension] ?? "generic";

  return (
    <span className={`files-type-icon files-type-icon-${kind}`} aria-hidden="true">
      <svg viewBox="0 0 32 40" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
        <path d="M19 2H6a3 3 0 0 0-3 3v30a3 3 0 0 0 3 3h20a3 3 0 0 0 3-3V12L19 2Z" fill="currentColor" fillOpacity="0.08" />
        <path d="M19 2v7a3 3 0 0 0 3 3h7" fill="currentColor" fillOpacity="0.12" />
        {kind === "spreadsheet" ? (
          <path d="M9 17h14v9H9zM9 21.5h14M14 17v9" />
        ) : kind === "archive" ? (
          <path d="M15 15h3m-3 4h3m-3 4h3m-3 4h3" strokeWidth="2.5" />
        ) : kind === "presentation" ? (
          <path d="M9 17h14v9H9zM12 23l3-3 3 2 3-3" />
        ) : kind === "image" ? (
          <><circle cx="12" cy="18" r="2" /><path d="m8 26 6-5 4 3 3-4 4 6" /></>
        ) : kind === "audio" ? (
          <path d="M17 24V16l6-1v7m-6 2c0 3-5 3-5 0s5-3 5 0Zm6-2c0 3-5 3-5 0s5-3 5 0Z" />
        ) : kind === "video" ? (
          <path d="m13 16 9 5-9 5V16Z" />
        ) : kind === "code" ? (
          <path d="m12 17-4 4 4 4m8-8 4 4-4 4m-3-9-2 10" />
        ) : (
          <path d="M9 17h14M9 21h14M9 25h9" strokeLinecap="round" />
        )}
      </svg>
      {extension ? <span className="files-type-icon-extension">{extension.slice(0, 5).toUpperCase()}</span> : null}
    </span>
  );
}
