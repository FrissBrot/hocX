import { useEffect, useRef, useState } from "react";

function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/**
 * Turns the whole browser window into a drop target for files. `isDragging` is true while a
 * file is being dragged over the page (drives the overlay); `onDrop` receives the dropped files.
 * Drags that carry no files (text, links, in-page drags) are ignored. While `enabled` is false
 * nothing is listened to, e.g. while an upload dialog with its own dropzone is open.
 */
export function useFileDrop(onDrop: (files: File[]) => void, enabled = true): boolean {
  const [isDragging, setIsDragging] = useState(false);
  const onDropRef = useRef(onDrop);
  onDropRef.current = onDrop;

  useEffect(() => {
    if (!enabled) {
      setIsDragging(false);
      return;
    }
    // dragenter/dragleave also fire for every child element, so count them instead of
    // toggling on each event - the overlay would flicker otherwise.
    let depth = 0;

    function handleDragEnter(event: DragEvent) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setIsDragging(true);
    }

    function handleDragOver(event: DragEvent) {
      if (!hasFiles(event)) return;
      // Required for the drop event to fire at all.
      event.preventDefault();
    }

    function handleDragLeave(event: DragEvent) {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setIsDragging(false);
    }

    function handleDrop(event: DragEvent) {
      if (!hasFiles(event)) return;
      // Also stops the browser from navigating to the dropped file.
      event.preventDefault();
      depth = 0;
      setIsDragging(false);
      // Copy now: the DataTransfer is emptied once the event handler returns.
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length > 0) onDropRef.current(files);
    }

    window.addEventListener("dragenter", handleDragEnter);
    window.addEventListener("dragover", handleDragOver);
    window.addEventListener("dragleave", handleDragLeave);
    window.addEventListener("drop", handleDrop);
    return () => {
      window.removeEventListener("dragenter", handleDragEnter);
      window.removeEventListener("dragover", handleDragOver);
      window.removeEventListener("dragleave", handleDragLeave);
      window.removeEventListener("drop", handleDrop);
      setIsDragging(false);
    };
  }, [enabled]);

  return isDragging;
}

/**
 * Like useFileDrop, but only one element (e.g. a dialog) is the drop target: `isDragging` is true
 * while files are dragged over that element, `onDrop` receives them. The drop is handled there and
 * does not reach window-level dropzones underneath (useFileDrop of the page). While enabled, files
 * dropped elsewhere in the window are swallowed instead of making the browser open them - that would
 * navigate away from a dialog with unsaved input.
 */
export function useElementFileDrop(
  getTarget: () => HTMLElement | null,
  onDrop: (files: File[]) => void,
  enabled = true,
): boolean {
  const [isDragging, setIsDragging] = useState(false);
  const onDropRef = useRef(onDrop);
  onDropRef.current = onDrop;
  const getTargetRef = useRef(getTarget);
  getTargetRef.current = getTarget;

  useEffect(() => {
    const target = enabled ? getTargetRef.current() : null;
    if (!target) {
      setIsDragging(false);
      return;
    }
    // Counter instead of a flag: dragenter/dragleave fire for every child element.
    let depth = 0;

    function handleDragEnter(event: DragEvent) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setIsDragging(true);
    }

    function handleDragOver(event: DragEvent) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    }

    function handleDragLeave(event: DragEvent) {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setIsDragging(false);
    }

    function handleDrop(event: DragEvent) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      depth = 0;
      setIsDragging(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length > 0) onDropRef.current(files);
    }

    // Outside the target: only keep the browser from opening the file.
    function swallowOutside(event: DragEvent) {
      if (!hasFiles(event) || target?.contains(event.target as Node)) return;
      event.preventDefault();
      if (event.type === "dragover" && event.dataTransfer) event.dataTransfer.dropEffect = "none";
    }

    target.addEventListener("dragenter", handleDragEnter);
    target.addEventListener("dragover", handleDragOver);
    target.addEventListener("dragleave", handleDragLeave);
    target.addEventListener("drop", handleDrop);
    window.addEventListener("dragover", swallowOutside);
    window.addEventListener("drop", swallowOutside);
    return () => {
      target.removeEventListener("dragenter", handleDragEnter);
      target.removeEventListener("dragover", handleDragOver);
      target.removeEventListener("dragleave", handleDragLeave);
      target.removeEventListener("drop", handleDrop);
      window.removeEventListener("dragover", swallowOutside);
      window.removeEventListener("drop", swallowOutside);
      setIsDragging(false);
    };
  }, [enabled]);

  return isDragging;
}
