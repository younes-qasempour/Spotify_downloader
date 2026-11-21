import { useCallback, useEffect, useRef, useState } from "react";

interface UseVirtualListOptions {
  count: number;
  itemHeight: number;
  overscan?: number;
}

export function useVirtualList({
  count,
  itemHeight,
  overscan = 8,
}: UseVirtualListOptions) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(460);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const updateSize = () => {
      setViewportHeight(el.clientHeight || 460);
    };
    updateSize();

    const observer = new ResizeObserver(updateSize);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const totalHeight = count * itemHeight;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const maxScroll = Math.max(0, totalHeight - viewportHeight);
    if (el.scrollTop > maxScroll) {
      el.scrollTop = maxScroll;
      setScrollTop(maxScroll);
    }
  }, [totalHeight, viewportHeight]);

  const onScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  const rawStart = Math.floor(scrollTop / itemHeight);
  const visibleCount = Math.ceil(viewportHeight / itemHeight);
  const startIndex = count === 0 ? 0 : Math.max(0, rawStart - overscan);
  const endIndex =
    count === 0
      ? 0
      : Math.min(count, rawStart + visibleCount + overscan);
  const offsetY = startIndex * itemHeight;

  return {
    containerRef,
    totalHeight,
    startIndex,
    endIndex,
    offsetY,
    onScroll,
  };
}
