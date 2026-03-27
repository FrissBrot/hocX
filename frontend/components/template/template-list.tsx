type TemplateItem = {
  id: number;
  name: string;
  version: number;
  status: string;
};

export function TemplateList({ items }: { items: TemplateItem[] }) {
  return (
    <div className="grid">
      {items.map((item) => (
        <article className="card" key={item.id}>
          <div className="eyebrow">Template #{item.id}</div>
          <h3>{item.name}</h3>
          <p className="muted">
            Version {item.version} · {item.status}
          </p>
        </article>
      ))}
    </div>
  );
}

