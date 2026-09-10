import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LightboxImage } from "./lightbox-image";

describe("LightboxImage", () => {
  it("lazy-loads the trigger thumbnail and only shows the full-size image after a click", () => {
    render(<LightboxImage src="/api/stored-files/full.jpg" alt="Vereinsausflug" />);

    const trigger = screen.getByAltText("Vereinsausflug") as HTMLImageElement;
    expect(trigger.getAttribute("loading")).toBe("lazy");
    expect(trigger.getAttribute("decoding")).toBe("async");
    expect(trigger.src).toContain("/api/stored-files/full.jpg");

    // Only the trigger thumbnail exists until it's opened - the full-resolution copy in the
    // lightbox portal isn't rendered up front.
    expect(screen.getAllByAltText("Vereinsausflug")).toHaveLength(1);

    fireEvent.click(trigger);

    const images = screen.getAllByAltText("Vereinsausflug");
    expect(images).toHaveLength(2);
    const lightboxImg = images.find((img) => img !== trigger) as HTMLImageElement;
    expect(lightboxImg.src).toContain("/api/stored-files/full.jpg");
  });

  it("shows a smaller previewSrc as the trigger, but always opens the lightbox with the full src", () => {
    render(
      <LightboxImage
        src="/api/stored-files/full.jpg"
        previewSrc="/api/stored-files/full.jpg/thumbnail"
        alt="Vereinsausflug"
      />
    );

    const trigger = screen.getByAltText("Vereinsausflug") as HTMLImageElement;
    expect(trigger.src).toContain("/thumbnail");

    fireEvent.click(trigger);

    const lightboxImg = screen.getAllByAltText("Vereinsausflug").find((img) => img !== trigger) as HTMLImageElement;
    expect(lightboxImg.src).toContain("/api/stored-files/full.jpg");
    expect(lightboxImg.src).not.toContain("/thumbnail");
  });

  it("closes the lightbox on Escape", () => {
    render(<LightboxImage src="/api/stored-files/full.jpg" alt="Vereinsausflug" />);

    fireEvent.click(screen.getByAltText("Vereinsausflug"));
    expect(screen.getAllByAltText("Vereinsausflug")).toHaveLength(2);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getAllByAltText("Vereinsausflug")).toHaveLength(1);
  });
});
