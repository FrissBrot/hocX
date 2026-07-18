const internalApiUrl = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const publicApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const browserApiBaseUrl = publicApiUrl;

export async function backendFetch<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const response = await fetch(`${internalApiUrl}${path}`, {
      ...init,
      cache: "no-store"
    });

    if (!response.ok) {
      console.error(`[backendFetch] ${init?.method ?? "GET"} ${path} → HTTP ${response.status}`);
      return null;
    }

    return (await response.json()) as T;
  } catch (err) {
    console.error(`[backendFetch] ${init?.method ?? "GET"} ${path} → network error:`, err);
    return null;
  }
}

export async function browserApiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(`${publicApiUrl}${path}`, {
    ...init,
    credentials: "include",
    headers: isFormData
      ? init?.headers
      : {
          "Content-Type": "application/json",
          ...(init?.headers ?? {})
        }
  });

  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed with status ${response.status}`;
    try {
      const json = JSON.parse(text);
      if (json?.detail) {
        if (typeof json.detail === "string") {
          message = json.detail;
        } else if (Array.isArray(json.detail)) {
          message = json.detail
            .map((e: { msg?: string; loc?: string[] }) => {
              const field = e.loc ? e.loc.filter((l) => l !== "body").join(".") : null;
              return field ? `${field}: ${e.msg ?? e}` : (e.msg ?? String(e));
            })
            .join(" · ");
        }
      }
    } catch {
      // keep raw text if not parseable JSON
    }
    throw new Error(message);
  }

  if (response.status === 204 || response.headers.get("content-length") === "0") {
    return null as T;
  }
  return (await response.json()) as T;
}
