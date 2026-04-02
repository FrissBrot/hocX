"use client";

import { ReactNode } from "react";

export type DataTableColumn =
  | string
  | {
      key: string;
      label: string;
      sortable?: boolean;
      sortDirection?: "asc" | "desc" | null;
      onSort?: () => void;
    };

type DataTableProps = {
  columns: DataTableColumn[];
  children: ReactNode;
  emptyMessage?: string;
};

export function DataToolbar({
  title,
  description,
  actions
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="table-toolbar">
      <div>
        <h3>{title}</h3>
        {description ? <p className="muted">{description}</p> : null}
      </div>
      {actions ? <div className="table-toolbar-actions">{actions}</div> : null}
    </div>
  );
}

export function DataTable({ columns, children, emptyMessage }: DataTableProps) {
  return (
    <div className="table-shell">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={typeof column === "string" ? column : column.key}>
                {typeof column === "string" ? (
                  column
                ) : column.sortable && column.onSort ? (
                  <button type="button" className="table-sort-button" onClick={column.onSort}>
                    <span>{column.label}</span>
                    <span className="table-sort-indicator">
                      {column.sortDirection === "asc" ? "↑" : column.sortDirection === "desc" ? "↓" : "↕"}
                    </span>
                  </button>
                ) : (
                  column.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
      {emptyMessage ? <div className="table-empty muted">{emptyMessage}</div> : null}
    </div>
  );
}
