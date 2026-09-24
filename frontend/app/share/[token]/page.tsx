import { backendFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import { PublicShare } from "@/types/api";

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export default async function PublicSharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const share = await backendFetch<PublicShare>(`/api/public/share/${token}`);

  if (!share) {
    return (
      <main className="public-share-page">
        <div className="card public-share-card">
          <h1 className="page-title">Link nicht verfügbar</h1>
          <p className="muted">Dieser Link ist ungültig, abgelaufen oder wurde widerrufen.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="public-share-page">
      <div className="card public-share-card">
        <div className="page-header">
          <div>
            <h1 className="page-title">{share.name}</h1>
            <p className="muted">
              {share.files.length} {share.files.length === 1 ? "Datei" : "Dateien"} zum Herunterladen
            </p>
          </div>
          {share.download_all_url ? (
            <a href={share.download_all_url} className="button-primary">
              Alle herunterladen
            </a>
          ) : null}
        </div>
        {share.files.length === 0 ? (
          <p className="muted">Keine Dateien verfügbar.</p>
        ) : (
          <div className="public-share-grid">
            {share.files.map((file) => (
              <a key={file.id} href={file.download_url} className="public-share-item">
                {file.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={file.thumbnail_url} alt="" className="public-share-thumb" />
                ) : (
                  <span className="public-share-thumb public-share-thumb-file">
                    <FileIcon />
                  </span>
                )}
                <span className="public-share-item-name" title={file.original_name}>
                  {file.original_name}
                </span>
                <span className="muted public-share-item-size">
                  {file.file_size_bytes ? formatFileSize(file.file_size_bytes) : ""}
                </span>
              </a>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
