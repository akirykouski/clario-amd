import { useEffect, useState } from "react";
import { api } from "../api";
import type { Health } from "../types";

let cached: Promise<Health | null> | null = null;
/** One shared GET /api/health for the whole session. A failure resolves to null (callers treat it as "unknown"). */
function loadHealth(): Promise<Health | null> {
  if (!cached) {
    cached = Promise.resolve()
      .then(() => api.health())
      .catch(() => { cached = null; return null; });
  }
  return cached;
}

export function useHealth(): Health | null {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => {
    let live = true;
    loadHealth().then((x) => { if (live) setH(x); });
    return () => { live = false; };
  }, []);
  return h;
}

/** True when the model behind this server is the offline fixture set: its confidences and speeds mean nothing. */
export function isOfflineBackend(h: Health | null | undefined): boolean {
  return h?.llm?.backend === "offline-fixtures";
}

export function resetHealthCache(): void { cached = null; }
