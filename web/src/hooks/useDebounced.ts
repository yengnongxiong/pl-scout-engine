import { useEffect, useState } from "react";

const DEFAULT_DELAY_MS = 150;

/** The value after it stopped changing for `delayMs` (keeps search requests calm). */
export function useDebounced<T>(value: T, delayMs = DEFAULT_DELAY_MS): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delayMs]);
  return debounced;
}
