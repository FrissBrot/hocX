const internalApiUrl = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const publicApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function backendFetch<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${internalApiUrl}${path}`, {
      cache: "no-store"
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function browserApiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${publicApiUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}
