import { useEffect, useRef } from "react";

interface UsePollingOptions<T> {
  enabled: boolean;
  fetcher: () => Promise<T>;
  onResult: (result: T) => void;
  onError?: (error: unknown) => void;
  interval?: number;
  maxInterval?: number;
  jitterRange?: number;
}

export function usePolling<T>({
  enabled,
  fetcher,
  onResult,
  onError,
  interval = 2500,
  maxInterval = 30000,
  jitterRange = 1000,
}: UsePollingOptions<T>) {
  const fetcherRef = useRef(fetcher);
  const onResultRef = useRef(onResult);
  const onErrorRef = useRef(onError);

  fetcherRef.current = fetcher;
  onResultRef.current = onResult;
  onErrorRef.current = onError;

  useEffect(() => {
    if (!enabled) return;

    let stopped = false;
    let failureCount = 0;
    let currentInterval = interval;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      try {
        const result = await fetcherRef.current();
        failureCount = 0;
        if (!stopped) onResultRef.current(result);
      } catch (err) {
        failureCount++;
        if (!stopped) onErrorRef.current?.(err);
      }
    };

    const schedule = () => {
      const jitter = (Math.random() - 0.5) * jitterRange;
      timer = window.setTimeout(async () => {
        await poll();
        if (!stopped) {
          currentInterval = Math.min(
            currentInterval * (failureCount > 0 ? 2 : 1),
            maxInterval
          );
          schedule();
        }
      }, currentInterval + jitter);
    };

    schedule();

    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [enabled, interval, maxInterval, jitterRange]);
}
