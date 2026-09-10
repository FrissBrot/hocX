import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useInfiniteScroll } from "./use-infinite-scroll";

// jsdom has no real IntersectionObserver - stand in a controllable fake so tests can fire
// "the sentinel scrolled into view" without a real layout/viewport.
class FakeIntersectionObserver implements IntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];
  readonly root = null;
  readonly rootMargin: string;
  readonly thresholds: ReadonlyArray<number> = [];
  observedElements: Element[] = [];
  disconnected = false;

  constructor(private callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.rootMargin = options?.rootMargin ?? "";
    FakeIntersectionObserver.instances.push(this);
  }

  observe(element: Element) {
    this.observedElements.push(element);
  }

  unobserve(element: Element) {
    this.observedElements = this.observedElements.filter((el) => el !== element);
  }

  disconnect() {
    this.disconnected = true;
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  trigger(isIntersecting: boolean) {
    this.callback([{ isIntersecting } as IntersectionObserverEntry], this);
  }
}

function Sentinel(props: { hasMore: boolean; isLoading: boolean; onLoadMore: () => void; rootMargin?: string }) {
  const ref = useInfiniteScroll(props);
  return <div ref={ref} data-testid="sentinel" />;
}

describe("useInfiniteScroll", () => {
  beforeEach(() => {
    FakeIntersectionObserver.instances = [];
    vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("observes the sentinel and calls onLoadMore once it intersects", () => {
    const onLoadMore = vi.fn();
    render(<Sentinel hasMore isLoading={false} onLoadMore={onLoadMore} />);

    expect(FakeIntersectionObserver.instances).toHaveLength(1);
    const observer = FakeIntersectionObserver.instances[0];
    expect(observer.observedElements).toHaveLength(1);
    expect(onLoadMore).not.toHaveBeenCalled();

    observer.trigger(true);
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it("does not call onLoadMore when the sentinel is not intersecting", () => {
    const onLoadMore = vi.fn();
    render(<Sentinel hasMore isLoading={false} onLoadMore={onLoadMore} />);

    FakeIntersectionObserver.instances[0].trigger(false);
    expect(onLoadMore).not.toHaveBeenCalled();
  });

  it("does not set up an observer once hasMore is false", () => {
    const onLoadMore = vi.fn();
    render(<Sentinel hasMore={false} isLoading={false} onLoadMore={onLoadMore} />);

    expect(FakeIntersectionObserver.instances).toHaveLength(0);
  });

  it("does not set up an observer while a load is already in flight", () => {
    const onLoadMore = vi.fn();
    render(<Sentinel hasMore isLoading onLoadMore={onLoadMore} />);

    expect(FakeIntersectionObserver.instances).toHaveLength(0);
  });

  it("disconnects the observer once isLoading flips to true, so a second page can't double-fire", () => {
    const onLoadMore = vi.fn();
    const { rerender } = render(<Sentinel hasMore isLoading={false} onLoadMore={onLoadMore} />);

    const observer = FakeIntersectionObserver.instances[0];
    expect(observer.disconnected).toBe(false);

    rerender(<Sentinel hasMore isLoading onLoadMore={onLoadMore} />);
    expect(observer.disconnected).toBe(true);
    // No new observer is created while loading.
    expect(FakeIntersectionObserver.instances).toHaveLength(1);
  });

  it("passes a custom rootMargin through to the observer", () => {
    const onLoadMore = vi.fn();
    render(<Sentinel hasMore isLoading={false} onLoadMore={onLoadMore} rootMargin="50px" />);

    expect(FakeIntersectionObserver.instances[0].rootMargin).toBe("50px");
  });
});
