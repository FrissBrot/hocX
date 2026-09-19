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
