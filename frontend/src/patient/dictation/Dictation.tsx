import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { useT } from "../../i18n";
import type { DictationLang, FromWorker } from "./core";
import { createWorker, decodeTo16k, dictationSupported, micPermission, startRecording, type Recording } from "./engine";

export type DictationState = "unsupported" | "denied" | "idle" | "recording" | "preparing" | "transcribing" | "error";

const MAX_RECORDING_MS = 3 * 60 * 1000;

export function useDictation(lang: DictationLang, onText: (text: string) => void) {
  const [state, setState] = useState<DictationState>(() => (dictationSupported() ? "idle" : "unsupported"));
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const worker = useRef<Worker | null>(null);
  const modelReady = useRef(false);
  const waiting = useRef<number | null>(null);
  const nextId = useRef(1);
  const recording = useRef<Recording | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  useEffect(() => {
    if (state !== "idle") return;
    let live = true;
    micPermission().then((p) => { if (live && p === "denied") setState("denied"); });
    return () => { live = false; };
    // Only checked once, on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    recording.current?.cancel();
    worker.current?.terminate();
  }, []);

  const onMessage = useCallback((e: MessageEvent<FromWorker>) => {
    const m = e.data;
    if (m.type === "progress") setProgress(m.total > 0 ? Math.round((m.loaded / m.total) * 100) : null);
    else if (m.type === "ready") {
      modelReady.current = true;
      setProgress(null);
      if (waiting.current !== null) setState("transcribing");
    } else if (m.type === "result" && m.id === waiting.current) {
      waiting.current = null;
      setState("idle");
      if (m.text) onTextRef.current(m.text);
      else setError("empty");
    } else if (m.type === "error") {
      waiting.current = null;
      setState("error");
      setError("failed");
    }
  }, []);

  const ensureWorker = useCallback(() => {
    if (worker.current) return worker.current;
    const w = createWorker();
    w.onmessage = onMessage;
    w.onerror = () => { waiting.current = null; setState("error"); setError("failed"); };
    w.postMessage({ type: "load" });
    worker.current = w;
    return w;
  }, [onMessage]);

  const stop = useCallback(async () => {
    const rec = recording.current;
    if (!rec) return;
    recording.current = null;
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    setState(modelReady.current ? "transcribing" : "preparing");
    try {
      const audio = await decodeTo16k(await rec.stop());
      const id = nextId.current++;
      waiting.current = id;
      ensureWorker().postMessage({ type: "transcribe", id, audio, lang }, [audio.buffer]);
    } catch {
      waiting.current = null;
      setState("error");
      setError("failed");
    }
  }, [ensureWorker, lang]);

  const start = useCallback(async () => {
    setError(null);
    ensureWorker(); // first tap starts the one-time model download while the user speaks
    try {
      recording.current = await startRecording();
      setState("recording");
      timer.current = setTimeout(() => { void stop(); }, MAX_RECORDING_MS);
    } catch (err) {
      const name = (err as DOMException)?.name;
      if (name === "NotAllowedError" || name === "SecurityError") setState("denied");
      else { setState("error"); setError("noMic"); }
    }
  }, [ensureWorker, stop]);

  const toggle = useCallback(() => {
    if (state === "recording") void stop();
    else if (state === "idle" || state === "error") void start();
  }, [state, start, stop]);

  return { state, progress, error, toggle };
}

export function DictationButton({ onText }: { onText: (text: string) => void }) {
  const { t, lang } = useT();
  const { state, progress, error, toggle } = useDictation(lang, onText);
  const busy = state === "preparing" || state === "transcribing";
  const disabled = state === "unsupported" || state === "denied" || busy;
  const tooltip = state === "unsupported" ? t("dictation.unsupported")
    : state === "denied" ? t("dictation.denied")
    : state === "recording" ? t("dictation.stop") : t("dictation.start");

  let status: string | null = null;
  if (state === "recording") status = t("dictation.recording");
  else if (state === "preparing") status = progress === null ? t("dictation.preparing") : t("dictation.preparingPct", { n: progress });
  else if (state === "transcribing") status = t("dictation.transcribing");
  else if (error === "empty") status = t("dictation.empty");
  else if (error === "noMic") status = t("dictation.noMic");
  else if (error === "failed") status = t("dictation.failed");

  return (
    <div className="flex items-start gap-3">
      <span title={tooltip} className="shrink-0">
      <button type="button" onClick={toggle} disabled={disabled} title={tooltip} aria-label={tooltip}
        aria-pressed={state === "recording"} data-state={state}
        className={`btn w-11 h-11 p-0 rounded-full ${state === "recording" ? "btn-primary" : ""} disabled:opacity-50`}>
        {busy ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden /> : state === "recording" ? <Square className="w-4 h-4" aria-hidden /> : <Mic className="w-5 h-5" aria-hidden />}
      </button>
      </span>
      <div className="text-sm min-h-[44px] flex flex-col justify-center">
        {status && <p role="status" aria-live="polite" className={state === "recording" ? "text-strong" : ""}>{status}</p>}
        <p className="text-muted">{state === "unsupported" || state === "denied" ? tooltip : t("dictation.privacy")}</p>
      </div>
    </div>
  );
}
