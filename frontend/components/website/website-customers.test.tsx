import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WebsiteCustomers } from "./website-customers";

describe("WebsiteCustomers", () => {
  it("shows logo and name, falls back to the name without logo", () => {
    const { container } = render(
      <WebsiteCustomers
        customers={[
          { name: "Jubla Muster", logo: { url: "/api/public/customers/logos/abcdefghijklmnopqrstuv.png", width: 256, height: 64 } },
          { name: "Turnverein Beispiel", logo: null },
        ]}
      />
    );
    const section = screen.getByRole("region", { name: "Im Einsatz bei" });
    const items = within(section).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["Jubla Muster", "Turnverein Beispiel"]);

    const logo = items[0].querySelector("img") as HTMLImageElement;
    expect(logo).not.toBeNull();
    expect(logo.getAttribute("src")).toBe("/api/public/customers/logos/abcdefghijklmnopqrstuv.png");
    // Name steht daneben: Logo dekorativ, feste Masse gegen Layoutsprünge (256×64 → 128×32)
    expect(logo.getAttribute("alt")).toBe("");
    expect(logo.getAttribute("width")).toBe("128");
    expect(logo.getAttribute("height")).toBe("32");
    expect(items[1].querySelector("img")).toBeNull();
    expect(container.querySelectorAll("img")).toHaveLength(1);
  });

  it("renders nothing without customers", () => {
    const { container } = render(<WebsiteCustomers customers={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
