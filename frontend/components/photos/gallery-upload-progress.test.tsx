import { render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
import { GalleryUploadProgress } from "./gallery-upload-progress";

it("reports duplicates even when the queued upload finished before the first poll", async () => {
  const detail = { id: "fast-job", errors: ["foto.jpg: Exaktes Duplikat"], imported_items: [] };
  fetchMock.mockImplementation(async (url: string) => url.endsWith("/fast-job") ? detail : []);
  const onJobDone = vi.fn();
  const view = render(<GalleryUploadProgress onJobDone={onJobDone} />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  view.rerender(<GalleryUploadProgress queuedJobId="fast-job" onJobDone={onJobDone} />);
  await waitFor(() => expect(onJobDone).toHaveBeenCalledWith(detail));
  expect(onJobDone).toHaveBeenCalledTimes(1);
  view.unmount();
});
