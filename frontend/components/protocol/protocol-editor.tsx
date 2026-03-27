"use client";

import { Dispatch, SetStateAction, useEffect, useMemo, useRef, useState } from "react";

import { DataToolbar } from "@/components/ui/data-table";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { ProtocolElement, ProtocolImage, ProtocolSummary, ProtocolTodo, SaveState } from "@/types/api";

type ProtocolEditorProps = {
  protocol: ProtocolSummary;
  initialElements: ProtocolElement[];
  initialTodos: Record<number, ProtocolTodo[]>;
  initialImages: Record<number, ProtocolImage[]>;
};

const TODO_STATUS = {
  open: 1,
  in_progress: 2,
  done: 3,
  cancelled: 4
} as const;

export function ProtocolEditor({ protocol, initialElements, initialTodos, initialImages }: ProtocolEditorProps) {
  const [elements, setElements] = useState(initialElements);
  const [todosByBlock, setTodosByBlock] = useState<Record<number, ProtocolTodo[]>>(initialTodos);
  const [imagesByBlock, setImagesByBlock] = useState<Record<number, ProtocolImage[]>>(initialImages);
  const [textDrafts, setTextDrafts] = useState<Record<number, string>>(
    Object.fromEntries(
      initialElements.flatMap((element) =>
        element.blocks
          .filter((block) => block.element_type_code === "text" || block.element_type_code === "static_text")
          .map((block) => [block.id, block.text_content ?? ""])
      )
    )
  );
  const [newTodoTask, setNewTodoTask] = useState<Record<number, string>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<number, File | null>>({});
  const [blockStatus, setBlockStatus] = useState<Record<number, SaveState>>({});
  const [selectedBlockId, setSelectedBlockId] = useState<number | null>(initialElements[0]?.blocks[0]?.id ?? null);
  const timers = useRef<Record<number, number>>({});

  useEffect(() => {
    return () => {
      Object.values(timers.current).forEach((timerId) => window.clearTimeout(timerId));
    };
  }, []);

  const visibleElements = useMemo(
    () =>
      [...elements]
        .filter((element) => element.is_visible_snapshot)
        .map((element) => ({
          ...element,
          blocks: [...element.blocks].filter((block) => block.is_visible_snapshot).sort((left, right) => left.sort_index - right.sort_index)
        }))
        .sort((left, right) => left.sort_index - right.sort_index),
    [elements]
  );

  const selectedEntry = useMemo(
    () =>
      visibleElements
        .flatMap((element) => element.blocks.map((block) => ({ element, block })))
        .find((entry) => entry.block.id === selectedBlockId) ?? null,
    [selectedBlockId, visibleElements]
  );

  function setStatus(protocolElementBlockId: number, status: SaveState) {
    setBlockStatus((current) => ({ ...current, [protocolElementBlockId]: status }));
  }

  function focusBlock(protocolElementBlockId: number) {
    setSelectedBlockId(protocolElementBlockId);
  }

  function updateBlockInState(blockId: number, updater: (current: ProtocolElement["blocks"][number]) => ProtocolElement["blocks"][number]) {
    setElements((current) =>
      current.map((element) => ({
        ...element,
        blocks: element.blocks.map((block) => (block.id === blockId ? updater(block) : block))
      }))
    );
  }

  function handleTextChange(protocolElementBlockId: number, content: string) {
    setTextDrafts((current) => ({ ...current, [protocolElementBlockId]: content }));
    setStatus(protocolElementBlockId, "saving");

    if (timers.current[protocolElementBlockId]) {
      window.clearTimeout(timers.current[protocolElementBlockId]);
    }

    timers.current[protocolElementBlockId] = window.setTimeout(async () => {
      try {
        await browserApiFetch(`/api/protocol-element-blocks/${protocolElementBlockId}/text`, {
          method: "PUT",
          body: JSON.stringify({ content })
        });
        updateBlockInState(protocolElementBlockId, (block) => ({ ...block, text_content: content }));
        setStatus(protocolElementBlockId, "saved");
      } catch {
        setStatus(protocolElementBlockId, "error");
      }
    }, 700);
  }

  async function addTodo(protocolElementBlockId: number) {
    const task = newTodoTask[protocolElementBlockId]?.trim();
    if (!task) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      const created = await browserApiFetch<ProtocolTodo>(`/api/protocol-element-blocks/${protocolElementBlockId}/todos`, {
        method: "POST",
        body: JSON.stringify({ task, todo_status_id: TODO_STATUS.open, created_by: null })
      });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: [...(current[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index)
      }));
      setNewTodoTask((current) => ({ ...current, [protocolElementBlockId]: "" }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function updateTodo(protocolElementBlockId: number, todoId: number, patch: Partial<ProtocolTodo>) {
    setStatus(protocolElementBlockId, "saving");
    try {
      const updated = await browserApiFetch<ProtocolTodo>(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: (current[protocolElementBlockId] ?? []).map((todo) => (todo.id === todoId ? updated : todo))
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function deleteTodo(protocolElementBlockId: number, todoId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-todos/${todoId}`, { method: "DELETE" });
      setTodosByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: (current[protocolElementBlockId] ?? []).filter((todo) => todo.id !== todoId)
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function uploadImage(protocolElementBlockId: number) {
    const file = selectedFiles[protocolElementBlockId];
    if (!file) return;
    setStatus(protocolElementBlockId, "saving");
    try {
      const body = new FormData();
      body.append("file", file);
      const created = await browserApiFetch<ProtocolImage>(`/api/protocol-element-blocks/${protocolElementBlockId}/images`, {
        method: "POST",
        body
      });
      setImagesByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: [...(current[protocolElementBlockId] ?? []), created].sort((left, right) => left.sort_index - right.sort_index)
      }));
      setSelectedFiles((current) => ({ ...current, [protocolElementBlockId]: null }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  async function deleteImage(protocolElementBlockId: number, imageId: number) {
    setStatus(protocolElementBlockId, "saving");
    try {
      await browserApiFetch(`/api/protocol-images/${imageId}`, { method: "DELETE" });
      setImagesByBlock((current) => ({
        ...current,
        [protocolElementBlockId]: (current[protocolElementBlockId] ?? []).filter((image) => image.id !== imageId)
      }));
      setStatus(protocolElementBlockId, "saved");
    } catch {
      setStatus(protocolElementBlockId, "error");
    }
  }

  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className="pill">Protocol status: {protocol.status}</span>
        <span className="pill">Autosave per block</span>
      </div>

      <div className="editor-shell">
        <aside className="editor-nav">
          <DataToolbar title="Protocol navigator" description="Open one block at a time for focused editing." />
          {visibleElements.map((element) => (
            <div className="editor-nav-section" key={element.id}>
              <h3 className="editor-nav-title">{element.section_name_snapshot}</h3>
              {element.blocks.map((block) => (
                <button
                  key={block.id}
                  type="button"
                  className={`editor-nav-item${selectedBlockId === block.id ? " editor-nav-item-active" : ""}`}
                  onClick={() => focusBlock(block.id)}
                >
                  <strong>{block.block_title_snapshot || block.display_title_snapshot || block.title_snapshot}</strong>
                  <span className="muted">{block.element_type_code ?? "unknown"}</span>
                  <div className="status-row">
                    <span className="pill">{blockStatus[block.id] ?? "saved"}</span>
                  </div>
                </button>
              ))}
            </div>
          ))}
        </aside>

        <article className="editor-panel">
          {selectedEntry ? (
            <FocusedBlockEditor
              entry={selectedEntry}
              status={blockStatus[selectedEntry.block.id] ?? "saved"}
              textDrafts={textDrafts}
              todosByBlock={todosByBlock}
              imagesByBlock={imagesByBlock}
              newTodoTask={newTodoTask}
              browserApiBaseUrl={browserApiBaseUrl}
              selectedFiles={selectedFiles}
              setTodosByBlock={setTodosByBlock}
              setSelectedFiles={setSelectedFiles}
              setNewTodoTask={setNewTodoTask}
              handleTextChange={handleTextChange}
              addTodo={addTodo}
              updateTodo={updateTodo}
              deleteTodo={deleteTodo}
              uploadImage={uploadImage}
              deleteImage={deleteImage}
            />
          ) : (
            <div className="editor-panel-empty">
              <div>
                <div className="eyebrow">No block selected</div>
                <h3>Choose a block from the navigator</h3>
                <p>Switching blocks keeps the editor focused and avoids long scrolling pages.</p>
              </div>
            </div>
          )}
        </article>
      </div>
    </div>
  );
}

function FocusedBlockEditor({
  entry,
  status,
  textDrafts,
  todosByBlock,
  imagesByBlock,
  newTodoTask,
  browserApiBaseUrl,
  selectedFiles,
  setTodosByBlock,
  setSelectedFiles,
  setNewTodoTask,
  handleTextChange,
  addTodo,
  updateTodo,
  deleteTodo,
  uploadImage,
  deleteImage
}: {
  entry: { element: ProtocolElement; block: ProtocolElement["blocks"][number] };
  status: SaveState;
  textDrafts: Record<number, string>;
  todosByBlock: Record<number, ProtocolTodo[]>;
  imagesByBlock: Record<number, ProtocolImage[]>;
  newTodoTask: Record<number, string>;
  browserApiBaseUrl: string;
  selectedFiles: Record<number, File | null>;
  setTodosByBlock: Dispatch<SetStateAction<Record<number, ProtocolTodo[]>>>;
  setSelectedFiles: Dispatch<SetStateAction<Record<number, File | null>>>;
  setNewTodoTask: Dispatch<SetStateAction<Record<number, string>>>;
  handleTextChange: (protocolElementBlockId: number, content: string) => void;
  addTodo: (protocolElementBlockId: number) => Promise<void>;
  updateTodo: (protocolElementBlockId: number, todoId: number, patch: Partial<ProtocolTodo>) => Promise<void>;
  deleteTodo: (protocolElementBlockId: number, todoId: number) => Promise<void>;
  uploadImage: (protocolElementBlockId: number) => Promise<void>;
  deleteImage: (protocolElementBlockId: number, imageId: number) => Promise<void>;
}) {
  const block = entry.block;
  const blockTitle = block.block_title_snapshot || block.display_title_snapshot || block.title_snapshot;
  const elementType = block.element_type_code ?? "unknown";

  return (
    <section className="block block-active" id={`protocol-block-${block.id}`}>
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">{entry.element.section_name_snapshot}</div>
          <h2>{blockTitle}</h2>
          {block.description_snapshot ? <p className="muted">{block.description_snapshot}</p> : null}
        </div>
        <div className="status-row">
          <span className="pill">{elementType}</span>
          <span className="pill">block #{block.id}</span>
          <span className="pill">{status}</span>
        </div>
      </div>

      {(elementType === "text" || elementType === "static_text") && (
        <textarea
          rows={12}
          value={textDrafts[block.id] ?? ""}
          onChange={(event) => handleTextChange(block.id, event.target.value)}
          readOnly={!block.is_editable_snapshot}
        />
      )}

      {elementType === "todo" && (
        <div className="grid">
          <div className="todo-list">
            {(todosByBlock[block.id] ?? []).map((todo) => {
              const isDone = todo.todo_status_code === "done";
              return (
                <article className={`todo-card${isDone ? " todo-card-done" : ""}`} key={todo.id}>
                  <button
                    type="button"
                    className={`todo-toggle${isDone ? " todo-toggle-done" : ""}`}
                    onClick={() => updateTodo(block.id, todo.id, { todo_status_id: isDone ? TODO_STATUS.open : TODO_STATUS.done })}
                    aria-label={isDone ? "Reopen todo" : "Mark todo done"}
                  >
                    {isDone ? "Done" : "Open"}
                  </button>
                  <div className="todo-main">
                    <input
                      className="todo-input"
                      value={todo.task}
                      onChange={(event) => {
                        const task = event.target.value;
                        setTodosByBlock((current) => ({
                          ...current,
                          [block.id]: (current[block.id] ?? []).map((item) => item.id === todo.id ? { ...item, task } : item)
                        }));
                        void updateTodo(block.id, todo.id, { task });
                      }}
                    />
                    <div className="todo-meta">
                      <span className={`pill todo-status-pill todo-status-${todo.todo_status_code ?? "open"}`}>
                        {todo.todo_status_code ?? todo.todo_status_id}
                      </span>
                      {todo.due_date ? <span className="muted">Due {todo.due_date}</span> : null}
                    </div>
                  </div>
                  <button type="button" className="button-inline button-danger todo-delete" onClick={() => deleteTodo(block.id, todo.id)}>
                    Delete
                  </button>
                </article>
              );
            })}
          </div>
          <div className="todo-create">
            <input value={newTodoTask[block.id] ?? ""} onChange={(event) => setNewTodoTask((current) => ({ ...current, [block.id]: event.target.value }))} placeholder="Add a new task" />
            <button type="button" onClick={() => addTodo(block.id)}>Add todo</button>
          </div>
        </div>
      )}

      {elementType === "display" && (
        <div className="card">
          <p className="muted">{block.display_compiled_text ?? "No display snapshot compiled yet."}</p>
          {block.display_snapshot_json ? <pre>{JSON.stringify(block.display_snapshot_json, null, 2)}</pre> : null}
        </div>
      )}

      {elementType === "image" && (
        <div className="grid">
          <div className="two-col">
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setSelectedFiles((current) => ({ ...current, [block.id]: event.target.files?.[0] ?? null }))}
            />
            <button type="button" onClick={() => uploadImage(block.id)} disabled={!selectedFiles[block.id]}>
              Upload image
            </button>
          </div>
          <div className="image-grid">
            {(imagesByBlock[block.id] ?? []).map((image) => (
              <div className="card image-card" key={image.id}>
                <img alt={image.title ?? image.original_name} src={`${browserApiBaseUrl}${image.content_url}`} />
                <p className="muted">{image.original_name}</p>
                <button type="button" onClick={() => deleteImage(block.id, image.id)}>Delete image</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
