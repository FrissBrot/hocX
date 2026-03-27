"use client";

import { useState } from "react";

type EditorBlock = {
  id: number;
  title: string;
  kind: "text" | "todo" | "image" | "display";
  content: string;
};

const initialBlocks: EditorBlock[] = [
  { id: 1, title: "Opening Notes", kind: "text", content: "Editable text block with debounce autosave later." },
  { id: 2, title: "Action Items", kind: "todo", content: "Todo items are saved immediately." },
  { id: 3, title: "Photo Evidence", kind: "image", content: "Upload endpoint placeholder." },
  { id: 4, title: "Attendance Snapshot", kind: "display", content: "Server-generated snapshot content." }
];

export function ProtocolEditor() {
  const [status, setStatus] = useState<"saved" | "saving" | "error">("saved");
  const [blocks, setBlocks] = useState(initialBlocks);

  function updateBlock(id: number, content: string) {
    setStatus("saving");
    setBlocks((current) => current.map((block) => (block.id === id ? { ...block, content } : block)));
    window.setTimeout(() => setStatus("saved"), 400);
  }

  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">Editor Status: {status}</span>
        <span className="pill">Autosave Strategy: block-wise</span>
      </div>
      <div className="block-list">
        {blocks.map((block) => (
          <section className="block" key={block.id}>
            <div className="eyebrow">{block.kind}</div>
            <h3>{block.title}</h3>
            {block.kind === "display" ? (
              <p className="muted">{block.content}</p>
            ) : (
              <textarea
                rows={4}
                value={block.content}
                onChange={(event) => updateBlock(block.id, event.target.value)}
              />
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

