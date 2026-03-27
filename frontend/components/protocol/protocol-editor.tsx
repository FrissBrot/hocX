"use client";

import { useEffect, useMemo, useRef, useState } from "react";

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
  const [todosByElement, setTodosByElement] = useState<Record<number, ProtocolTodo[]>>(initialTodos);
  const [imagesByElement, setImagesByElement] = useState<Record<number, ProtocolImage[]>>(initialImages);
  const [textDrafts, setTextDrafts] = useState<Record<number, string>>(
    Object.fromEntries(
      initialElements
        .filter((element) => element.element_type_code === "text" || element.element_type_code === "static_text")
        .map((element) => [element.id, element.text_content ?? ""])
    )
  );
  const [newTodoTask, setNewTodoTask] = useState<Record<number, string>>({});
  const [selectedFiles, setSelectedFiles] = useState<Record<number, File | null>>({});
  const [blockStatus, setBlockStatus] = useState<Record<number, SaveState>>({});
  const timers = useRef<Record<number, number>>({});

  useEffect(() => {
    return () => {
      Object.values(timers.current).forEach((timerId) => window.clearTimeout(timerId));
    };
  }, []);

  const visibleElements = useMemo(
    () => [...elements].filter((element) => element.is_visible_snapshot).sort((left, right) => left.sort_index - right.sort_index),
    [elements]
  );

  function setStatus(protocolElementId: number, status: SaveState) {
    setBlockStatus((current) => ({ ...current, [protocolElementId]: status }));
  }

  function handleTextChange(protocolElementId: number, content: string) {
    setTextDrafts((current) => ({ ...current, [protocolElementId]: content }));
    setStatus(protocolElementId, "saving");

    if (timers.current[protocolElementId]) {
      window.clearTimeout(timers.current[protocolElementId]);
    }

    timers.current[protocolElementId] = window.setTimeout(async () => {
      try {
        await browserApiFetch(`/api/protocol-elements/${protocolElementId}/text`, {
          method: "PUT",
          body: JSON.stringify({ content })
        });
        setElements((current) =>
          current.map((element) =>
            element.id === protocolElementId ? { ...element, text_content: content } : element
          )
        );
        setStatus(protocolElementId, "saved");
      } catch {
        setStatus(protocolElementId, "error");
      }
    }, 700);
  }

  async function addTodo(protocolElementId: number) {
    const task = newTodoTask[protocolElementId]?.trim();
    if (!task) {
      return;
    }
    setStatus(protocolElementId, "saving");

    try {
      const created = await browserApiFetch<ProtocolTodo>(`/api/protocol-elements/${protocolElementId}/todos`, {
        method: "POST",
        body: JSON.stringify({ task, todo_status_id: TODO_STATUS.open, created_by: null })
      });
      setTodosByElement((current) => ({
        ...current,
        [protocolElementId]: [...(current[protocolElementId] ?? []), created].sort(
          (left, right) => left.sort_index - right.sort_index
        )
      }));
      setNewTodoTask((current) => ({ ...current, [protocolElementId]: "" }));
      setStatus(protocolElementId, "saved");
    } catch {
      setStatus(protocolElementId, "error");
    }
  }

  async function updateTodo(protocolElementId: number, todoId: number, patch: Partial<ProtocolTodo>) {
    setStatus(protocolElementId, "saving");
    try {
      const updated = await browserApiFetch<ProtocolTodo>(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      setTodosByElement((current) => ({
        ...current,
        [protocolElementId]: (current[protocolElementId] ?? []).map((todo) => (todo.id === todoId ? updated : todo))
      }));
      setStatus(protocolElementId, "saved");
    } catch {
      setStatus(protocolElementId, "error");
    }
  }

  async function deleteTodo(protocolElementId: number, todoId: number) {
    setStatus(protocolElementId, "saving");
    try {
      await browserApiFetch(`/api/protocol-todos/${todoId}`, { method: "DELETE" });
      setTodosByElement((current) => ({
        ...current,
        [protocolElementId]: (current[protocolElementId] ?? []).filter((todo) => todo.id !== todoId)
      }));
      setStatus(protocolElementId, "saved");
    } catch {
      setStatus(protocolElementId, "error");
    }
  }

  async function uploadImage(protocolElementId: number) {
    const file = selectedFiles[protocolElementId];
    if (!file) {
      return;
    }
    setStatus(protocolElementId, "saving");
    try {
      const body = new FormData();
      body.append("file", file);
      const created = await browserApiFetch<ProtocolImage>(`/api/protocol-elements/${protocolElementId}/images`, {
        method: "POST",
        body
      });
      setImagesByElement((current) => ({
        ...current,
        [protocolElementId]: [...(current[protocolElementId] ?? []), created].sort(
          (left, right) => left.sort_index - right.sort_index
        )
      }));
      setSelectedFiles((current) => ({ ...current, [protocolElementId]: null }));
      setStatus(protocolElementId, "saved");
    } catch {
      setStatus(protocolElementId, "error");
    }
  }

  async function deleteImage(protocolElementId: number, imageId: number) {
    setStatus(protocolElementId, "saving");
    try {
      await browserApiFetch(`/api/protocol-images/${imageId}`, { method: "DELETE" });
      setImagesByElement((current) => ({
        ...current,
        [protocolElementId]: (current[protocolElementId] ?? []).filter((image) => image.id !== imageId)
      }));
      setStatus(protocolElementId, "saved");
    } catch {
      setStatus(protocolElementId, "error");
    }
  }

  return (
    <div className="grid">
      <div className="status-row">
        <span className="pill">{protocol.protocol_number}</span>
        <span className="pill">Protocol status: {protocol.status}</span>
        <span className="pill">Autosave: text debounced, todos immediate</span>
      </div>

      <div className="block-list">
        {visibleElements.map((element) => {
          const status = blockStatus[element.id] ?? "saved";
          const elementType = element.element_type_code ?? "unknown";

          return (
            <section className="block" key={element.id}>
              <div className="status-row">
                <span className="pill">{elementType}</span>
                <span className="pill">block #{element.id}</span>
                <span className="pill">{status}</span>
              </div>
              <h3>{element.heading_text_snapshot ?? element.display_title_snapshot ?? element.title_snapshot}</h3>
              {element.description_snapshot ? <p className="muted">{element.description_snapshot}</p> : null}

              {(elementType === "text" || elementType === "static_text") && (
                <textarea
                  rows={6}
                  value={textDrafts[element.id] ?? ""}
                  onChange={(event) => handleTextChange(element.id, event.target.value)}
                  readOnly={!element.is_editable_snapshot}
                />
              )}

              {elementType === "todo" && (
                <div className="grid">
                  <div className="grid">
                    {(todosByElement[element.id] ?? []).map((todo) => (
                      <div className="card" key={todo.id}>
                        <input
                          value={todo.task}
                          onChange={(event) => {
                            const task = event.target.value;
                            setTodosByElement((current) => ({
                              ...current,
                              [element.id]: (current[element.id] ?? []).map((item) =>
                                item.id === todo.id ? { ...item, task } : item
                              )
                            }));
                            void updateTodo(element.id, todo.id, { task });
                          }}
                        />
                        <div className="status-row">
                          <button
                            type="button"
                            onClick={() =>
                              updateTodo(element.id, todo.id, {
                                todo_status_id:
                                  todo.todo_status_code === "done" ? TODO_STATUS.open : TODO_STATUS.done
                              })
                            }
                          >
                            {todo.todo_status_code === "done" ? "Reopen" : "Mark done"}
                          </button>
                          <button type="button" onClick={() => deleteTodo(element.id, todo.id)}>
                            Delete todo
                          </button>
                        </div>
                        <p className="muted">Status: {todo.todo_status_code ?? todo.todo_status_id}</p>
                      </div>
                    ))}
                  </div>
                  <div className="two-col">
                    <input
                      placeholder="New todo task"
                      value={newTodoTask[element.id] ?? ""}
                      onChange={(event) =>
                        setNewTodoTask((current) => ({ ...current, [element.id]: event.target.value }))
                      }
                    />
                    <button type="button" onClick={() => addTodo(element.id)}>
                      Add todo
                    </button>
                  </div>
                </div>
              )}

              {elementType === "display" && (
                <div className="card">
                  <p className="muted">{element.display_compiled_text ?? "No display snapshot compiled yet."}</p>
                  {element.display_snapshot_json ? (
                    <pre>{JSON.stringify(element.display_snapshot_json, null, 2)}</pre>
                  ) : null}
                </div>
              )}

              {elementType === "image" && (
                <div className="grid">
                  <div className="two-col">
                    <input
                      type="file"
                      accept="image/*"
                      onChange={(event) =>
                        setSelectedFiles((current) => ({
                          ...current,
                          [element.id]: event.target.files?.[0] ?? null
                        }))
                      }
                    />
                    <button type="button" onClick={() => uploadImage(element.id)}>
                      Upload image
                    </button>
                  </div>
                  <div className="grid">
                    {(imagesByElement[element.id] ?? []).map((image) => (
                      <div className="card" key={image.id}>
                        <img
                          alt={image.title ?? image.original_name}
                          src={`${browserApiBaseUrl}${image.content_url}`}
                          style={{ maxWidth: "100%", borderRadius: "16px" }}
                        />
                        <p className="muted">{image.original_name}</p>
                        <button type="button" onClick={() => deleteImage(element.id, image.id)}>
                          Delete image
                        </button>
                      </div>
                    ))}
                    {(imagesByElement[element.id] ?? []).length === 0 ? (
                      <div className="card">
                        <p className="muted">No images uploaded yet.</p>
                      </div>
                    ) : null}
                  </div>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
