"use client";

import { SOURCE_BADGE_VARIANT, SOURCE_LABEL } from "./file-detail-modal";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { browserApiBaseUrl } from "@/lib/api/client";
import { formatDate, formatFileSize } from "@/lib/utils/format";
import { FileOverviewItem } from "@/types/api";

export function FilesTable({
  items,
  onOpenDetail,
  onNavigate,
}: {
  items: FileOverviewItem[];
  onOpenDetail: (item: FileOverviewItem) => void;
  onNavigate: (href: string) => void;
}) {
  return (
    <DataTable
      columns={["Name", "Quelle", "Bezug", "Hochgeladen", "Grösse", ""]}
      emptyMessage="Keine Dateien gefunden."
    >
      {items.map((item) => {
        return (
          <tr key={item.id} className="table-row-clickable" onClick={() => onOpenDetail(item)}>
            <td>
              <span className="files-table-name">
                <FileTypeIcon />
                <span title={item.original_name}>{item.original_name}</span>
              </span>
            </td>
            <td><Badge variant={SOURCE_BADGE_VARIANT[item.source]}>{SOURCE_LABEL[item.source]}</Badge></td>
            <td onClick={(event) => item.ref_href && event.stopPropagation()}>
              {item.ref_label ? (
                item.ref_href ? (
                  <button type="button" className="file-card-ref" onClick={() => onNavigate(item.ref_href!)}>
                    {item.source === "protocol_image" ? `Protokoll ${item.ref_label}` : item.ref_label}
                  </button>
                ) : (
                  <span className="muted">{item.ref_label}</span>
                )
              ) : (
                <span className="muted">–</span>
              )}
              {item.ref_date ? <span className="muted"> · {formatDate(item.ref_date)}</span> : null}
            </td>
            <td>{formatDate(item.created_at)}</td>
            <td>{item.file_size_bytes ? formatFileSize(item.file_size_bytes) : <span className="muted">–</span>}</td>
            <td onClick={(event) => event.stopPropagation()}>
              <a href={`${browserApiBaseUrl}${item.content_url}`} target="_blank" rel="noreferrer" className="button-inline button-ghost">
                Download
              </a>
            </td>
          </tr>
        );
      })}
    </DataTable>
  );
}

function FileTypeIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}
