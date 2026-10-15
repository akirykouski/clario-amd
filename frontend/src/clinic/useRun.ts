import { useCallback, useReducer, useState } from "react";
import { api } from "../api";
import { useEventStream } from "../components/useEventStream";
import { t } from "../i18n";
import { initialRun, runReducer } from "../runReducer";
import type { RunEvent } from "../types";

export function useRun() {
  const [state, dispatch] = useReducer(runReducer, initialRun);
  const [url, setUrl] = useState<string | null>(null);
  useEventStream<RunEvent>(
    url,
    (event) => event.stage === "done" || event.stage === "error",
    (event) => dispatch({ type: "event", event }),
    () => dispatch({ type: "fail", error: t("brief.lost") }),
  );
  const start = useCallback(async (pkgId: string, lang?: string) => {
    setUrl(null);
    dispatch({ type: "start" });
    try {
      const { run_id } = await api.startBrief(pkgId, lang);
      setUrl(api.runEventsUrl(run_id));
    } catch (x) { dispatch({ type: "fail", error: (x as Error).message }); }
  }, []);
  return { state, start };
}
