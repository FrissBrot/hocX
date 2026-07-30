import { useEffect, useRef } from "react";

/**
 * Attaches an IntersectionObserver to a sentinel element. Call onLoadMore
 * automatically once the sentinel comes within `rootMargin` of the viewport,
 * instead of requiring a manual "load more" click.
 */
export function useInfiniteScroll(options: {
  hasMore: boolean;
  isLoading: boolean;
  onLoadMore: () => void;
  rootMargin?: string;
}) {
  const { hasMore, isLoading, onLoadMore, rootMargin = "400px" } = options;
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore || isLoading) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMore();
        }
      },
      { rootMargin }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, isLoading, onLoadMore, rootMargin]);

  return sentinelRef;
}
