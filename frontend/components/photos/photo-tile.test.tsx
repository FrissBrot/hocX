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
  render(<PhotoTile item={item} selected={false} selectionMode={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />);
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

it("opens the photo on click when nothing is selected", () => {
  const onOpen = vi.fn();
  const onToggleSelect = vi.fn();
  render(<PhotoTile item={item} selected={false} selectionMode={false} onOpen={onOpen} onToggleSelect={onToggleSelect} />);
  fireEvent.click(screen.getByRole("img").parentElement!);
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(onToggleSelect).not.toHaveBeenCalled();
});

it("toggles selection on click instead of opening once a selection is active", () => {
  const onOpen = vi.fn();
  const onToggleSelect = vi.fn();
  render(<PhotoTile item={item} selected={false} selectionMode={true} onOpen={onOpen} onToggleSelect={onToggleSelect} />);
  fireEvent.click(screen.getByRole("img").parentElement!);
  expect(onToggleSelect).toHaveBeenCalledTimes(1);
  expect(onOpen).not.toHaveBeenCalled();
});

it("starts requests only for visible tiles, preserving offscreen placeholders until scrolling", () => {
  render(<>
    <PhotoTile item={item} selected={false} selectionMode={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />
    <PhotoTile item={{ ...item, id: "photo-2", thumbnail_url: "/second.jpg" }} selected={false} selectionMode={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />
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

// --- Live Photo: der Clip spielt beim Hovern über dem Standbild ---

const liveItem = { ...item, live_video_url: "/api/stored-files/clip-1/content" } as FileOverviewItem;

function renderLiveTile() {
  const { container } = render(<PhotoTile item={liveItem} selected={false} selectionMode={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />);
  return { tile: container.querySelector(".photo-tile") as HTMLElement, video: () => container.querySelector("video") };
}

function stubMedia() {
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  return { play, pause };
}

it("shows no LIVE badge and loads no video for an ordinary photo", () => {
  vi.useFakeTimers();
  const { container } = render(<PhotoTile item={item} selected={false} selectionMode={false} onOpen={vi.fn()} onToggleSelect={vi.fn()} />);
  fireEvent.mouseEnter(container.querySelector(".photo-tile")!);
  act(() => { vi.advanceTimersByTime(1000); });
  expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  expect(container.querySelector("video")).toBeNull();
  vi.useRealTimers();
});

it("marks a Live Photo but does not load its clip until it is hovered", () => {
  vi.useFakeTimers();
  const { video } = renderLiveTile();
  expect(screen.getByText("LIVE")).toBeInTheDocument();
  act(() => { vi.advanceTimersByTime(1000); });
  expect(video()).toBeNull();
  vi.useRealTimers();
});

it("plays the clip while hovered and stops and rewinds it on leave", () => {
  vi.useFakeTimers();
  const { play, pause } = stubMedia();
  const { tile, video } = renderLiveTile();

  fireEvent.mouseEnter(tile);
  expect(video()).toBeNull(); // erst nach kurzer Verzögerung, damit Überstreichen nichts lädt
  act(() => { vi.advanceTimersByTime(200); });
  expect(video()).toHaveAttribute("src", "/api/stored-files/clip-1/content");
  expect(video()).toHaveProperty("muted", true);
  expect(play).toHaveBeenCalled();
  expect(video()).not.toHaveClass("photo-tile-live-video-playing"); // Standbild bleibt bis zum ersten Videobild

  fireEvent.playing(video()!);
  expect(video()).toHaveClass("photo-tile-live-video-playing");

  fireEvent.mouseLeave(tile);
  expect(pause).toHaveBeenCalled();
  expect(video()).not.toHaveClass("photo-tile-live-video-playing");
  vi.useRealTimers();
});

it("does not request the clip when the pointer only passes over the tile", () => {
  vi.useFakeTimers();
  stubMedia();
  const { tile, video } = renderLiveTile();
  fireEvent.mouseEnter(tile);
  act(() => { vi.advanceTimersByTime(50); });
  fireEvent.mouseLeave(tile);
  act(() => { vi.advanceTimersByTime(1000); });
  expect(video()).toBeNull();
  vi.useRealTimers();
});

it("never plays the clip when the user prefers reduced motion", () => {
  vi.useFakeTimers();
  const { play } = stubMedia();
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("prefers-reduced-motion"), addEventListener() {}, removeEventListener() {} }));
  const { tile } = renderLiveTile();
  fireEvent.mouseEnter(tile);
  act(() => { vi.advanceTimersByTime(200); });
  expect(play).not.toHaveBeenCalled();
  vi.useRealTimers();
});

it("falls back to the still photo when the clip cannot be loaded", () => {
  vi.useFakeTimers();
  stubMedia();
  const { tile, video } = renderLiveTile();
  fireEvent.mouseEnter(tile);
  act(() => { vi.advanceTimersByTime(200); });
  fireEvent.error(video()!);
  expect(video()).toBeNull();
  expect(screen.getByRole("img")).toBeInTheDocument();
  vi.useRealTimers();
});
