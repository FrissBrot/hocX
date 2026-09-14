import { describe, expect, it } from "vitest";

import { groupPhotosByDate } from "./grouping";
import type { FileAlbumRef, FileOverviewItem } from "@/types/api";

function makeAlbum(overrides: Partial<FileAlbumRef> = {}): FileAlbumRef {
  return { id: "album-1", name: "Sommerlager 2026", kind: "cycle", is_best: false, ...overrides };
}

function makeItem(overrides: Partial<FileOverviewItem> = {}): FileOverviewItem {
  const id = overrides.id ?? `file-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    original_name: "foto.jpg",
    mime_type: "image/jpeg",
    file_size_bytes: 1000,
    created_at: "2026-07-10T08:00:00Z",
    source: "gallery_upload",
    is_image: true,
    content_url: `/api/stored-files/${id}`,
    thumbnail_url: `/api/stored-files/${id}/thumbnail`,
    tags_url: `/api/stored-files/${id}/tags`,
    metadata_url: `/api/stored-files/${id}/metadata`,
    ref_label: "",
    ref_date: null,
    ref_href: null,
    tags: [],
    origin_tag: "Direkt hochgeladen",
    sharpness_score: null,
    exposure_score: null,
    face_quality_score: null,
    face_analyzed_at: null,
    group_date: "2026-07-10",
    context_label: null,
    albums: [],
    is_best: null,
    ...overrides,
  };
}

describe("groupPhotosByDate", () => {
  it("groups contiguous items sharing the same group_date", () => {
    const items = [
      makeItem({ id: "a", group_date: "2026-07-10" }),
      makeItem({ id: "b", group_date: "2026-07-10" }),
      makeItem({ id: "c", group_date: "2026-07-09" }),
    ];

    const groups = groupPhotosByDate(items);

    expect(groups).toHaveLength(2);
    expect(groups[0].date).toBe("2026-07-10");
    expect(groups[0].items.map((item) => item.id)).toEqual(["a", "b"]);
    expect(groups[1].date).toBe("2026-07-09");
    expect(groups[1].items.map((item) => item.id)).toEqual(["c"]);
  });

  it("falls back to created_at's date when group_date is missing", () => {
    const items = [makeItem({ id: "a", group_date: null, created_at: "2026-01-05T12:00:00Z" })];

    const groups = groupPhotosByDate(items);

    expect(groups[0].date).toBe("2026-01-05");
  });

  it("combines a shared cycle-album name with a per-item context label", () => {
    const items = [
      makeItem({ id: "a", albums: [makeAlbum({ kind: "cycle", name: "Sommerlager 2026" })], context_label: "Tag 1" }),
      makeItem({ id: "b", albums: [makeAlbum({ kind: "cycle", name: "Sommerlager 2026" })], context_label: "Tag 1" }),
    ];

    const groups = groupPhotosByDate(items);

    expect(groups[0].contextLabel).toBe("Sommerlager 2026 · Tag 1");
  });

  it("uses only the context label when there is no cycle album", () => {
    const items = [
      makeItem({ id: "a", albums: [], context_label: "Vorstandssitzung · Bilder im Protokoll" }),
    ];

    const groups = groupPhotosByDate(items);

    expect(groups[0].contextLabel).toBe("Vorstandssitzung · Bilder im Protokoll");
  });

  it("omits a submission/manual album from the header (only cycle albums count)", () => {
    const items = [makeItem({ id: "a", albums: [makeAlbum({ kind: "submission", name: "Abgabe X" })], context_label: null })];

    const groups = groupPhotosByDate(items);

    expect(groups[0].contextLabel).toBeUndefined();
  });

  it("preserves the input order of distinct dates", () => {
    const items = [
      makeItem({ id: "a", group_date: "2026-08-12" }),
      makeItem({ id: "b", group_date: "2026-07-10" }),
      makeItem({ id: "c", group_date: "2026-08-12" }),
    ];

    const groups = groupPhotosByDate(items);

    expect(groups.map((group) => group.date)).toEqual(["2026-08-12", "2026-07-10"]);
  });
});
