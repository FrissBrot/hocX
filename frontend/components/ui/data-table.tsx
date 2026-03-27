"use client";

import { ReactNode } from "react";

type DataTableProps = {
  columns: string[];
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
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
      {emptyMessage ? <div className="table-empty muted">{emptyMessage}</div> : null}
    </div>
  );
}
