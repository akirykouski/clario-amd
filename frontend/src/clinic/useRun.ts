import { useCallback, useEffect, useReducer, useRef } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { initialRun, runReducer } from "../runReducer";
import type { RunEvent } from "../types";

export function useRun() {
  const [state, dispatch] = useReducer(runReducer, initialRun);
  const es = useRef<EventSource | null>(null);
  const close = () => { es.current?.close(); es.current = null; };
  useEffect(() => close, []);
  const start = useCallback(async (pkgId: string, lang?: string) => {
    close();
    dispatch({ type: "start" });
    try {
      const { run_id } = await api.startBrief(pkgId, lang);
      const src = new EventSource(api.runEventsUrl(run_id));
      es.current = src;
      src.onmessage = (m) => {
        try {
          const event = JSON.parse(m.data) as RunEvent;
          dispatch({ type: "event", event });
          if (event.stage === "done" || event.stage === "error") close();
        } catch { /* ignore malformed frame */ }
      };
      src.onerror = () => { if (es.current) { close(); dispatch({ type: "fail", error: t("brief.lost") }); } };
    } catch (x) { dispatch({ type: "fail", error: (x as Error).message }); }
  }, []);
  return { state, start };
}
