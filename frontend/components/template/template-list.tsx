import Link from "next/link";

import { TemplateSummary } from "@/types/api";

export function TemplateList({ items }: { items: TemplateSummary[] }) {
  return (
    <div className="grid">
      {items.map((item) => (
        <article className="card" key={item.id}>
          <div className="eyebrow">Template #{item.id}</div>
          <h3>{item.name}</h3>
          <p className="muted">
            Version {item.version} · {item.status}
          </p>
          <p className="muted">{item.description ?? "No description yet."}</p>
          <Link href={`/templates/${item.id}`}>Open template builder</Link>
        </article>
      ))}
    </div>
  );
}
