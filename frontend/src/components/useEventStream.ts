import { useEffect, useRef } from "react";

/**
 * Follow a server-sent event stream. Opens `url` (null = idle), calls `onEvent` with every parsed frame, closes the
 * stream after the frame for which `isDone` is true or on unmount, and calls `onLost` when the connection drops
 * before that. A frame that is not valid JSON is skipped.
 */
export function useEventStream<T>(url: string | null, isDone: (e: T) => boolean, onEvent: (e: T) => void, onLost: () => void): void {
  const cb = useRef({ isDone, onEvent, onLost });
  cb.current = { isDone, onEvent, onLost };
  useEffect(() => {
    if (!url) return;
    const src = new EventSource(url);
    src.onmessage = (m) => {
      let e: T;
      try { e = JSON.parse(m.data) as T; } catch { return; }
      cb.current.onEvent(e);
      if (cb.current.isDone(e)) src.close();
    };
    src.onerror = () => { src.close(); cb.current.onLost(); };
    return () => src.close();
  }, [url]);
}
