const internalApiUrl = process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

