import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { FileOverviewItem } from "@/types/api";
import { PhotoTile } from "./photo-tile";

const item = {
  id: "photo-1",
  original_name: "photo.jpg",
  thumbnail_url: "/api/stored-files/photo-1/thumbnail",
  content_url: "/api/stored-files/photo-1/content",
  width: 800,
  height: 600,
} as FileOverviewItem;

const observers: { callback: IntersectionObserverCallback; options?: IntersectionObserverInit }[] = [];
beforeEach(() => {
  observers.length = 0;
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) { observers.push({ callback, options }); }
    observe() {}
    disconnect() {}
  });
});
function intersect(index: number, visible: boolean) {
  act(() => observers[index].callback([{ isIntersecting: visible, intersectionRatio: visible ? 1 : 0 } as IntersectionObserverEntry], {} as IntersectionObserver));
}
afterEach(() => vi.unstubAllGlobals());

afterEach(() => vi.restoreAllMocks());

function renderTile() {
  render(<PhotoTile item={item} selected={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />);
  intersect(0, true);
  return screen.getByRole("img").parentElement;
}

it("reveals an image that finished loading before hydration without another load event", () => {
  vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockReturnValue(true);
  vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(480);
  expect(renderTile()).toHaveClass("photo-tile-preview-loaded");
});

it("keeps the placeholder while loading and reveals the image on load", () => {
  vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockReturnValue(false);
  const preview = renderTile();
  expect(preview).not.toHaveClass("photo-tile-preview-loaded");
  fireEvent.load(screen.getByRole("img"));
  expect(preview).toHaveClass("photo-tile-preview-loaded");
});

it("does not treat a failed image request as a successfully loaded image", () => {
  vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockReturnValue(true);
  vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(0);
  expect(renderTile()).not.toHaveClass("photo-tile-preview-loaded");
});

it("starts requests only for visible tiles, preserving offscreen placeholders until scrolling", () => {
  render(<>
    <PhotoTile item={item} selected={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />
    <PhotoTile item={{ ...item, id: "photo-2", thumbnail_url: "/second.jpg" }} selected={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />
  </>);
  const images = screen.getAllByRole("img");
  expect(images[0]).not.toHaveAttribute("src");
  expect(images[1]).not.toHaveAttribute("src");
  expect(observers[0].options).toEqual({ rootMargin: "0px", threshold: 0 });
  intersect(0, false);
  expect(images[0]).not.toHaveAttribute("src");
  intersect(0, true);
  expect(images[0]).toHaveAttribute("src", expect.stringContaining("/thumbnail"));
  expect(images[1]).not.toHaveAttribute("src");
  fireEvent.load(images[0]);
  expect(images[0].parentElement).toHaveClass("photo-tile-preview-loaded");
  expect(images[1].parentElement).not.toHaveClass("photo-tile-preview-loaded");
  intersect(1, true);
  expect(images[1]).toHaveAttribute("src", expect.stringContaining("/second.jpg"));
});
