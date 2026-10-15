import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Cpu, FileUp } from "lucide-react";
import { api } from "../api";
import { ErrorBox } from "../components/ui";
import type { BatchEvent } from "../types";

export function gpuLoad(gpu: BatchEvent["gpu"]): number | null {
  if (!gpu) return null;
  for (const k of ["util", "utilization", "gpu_util", "gpu_util_percent", "util_percent"]) {
    const v = gpu[k];
    if (typeof v === "number") return Math.round(v);
  }
  return null;
}

export default function ImportPage() {
  const nav = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const es = useRef<EventSource | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ev, setEv] = useState<BatchEvent | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => () => es.current?.close(), []);

  const start = async (list: FileList | File[]) => {
    const files = Array.from(list);
    if (!files.length) return;
    setErr(null); setBusy(true); setEv(null);
    try {
      const { batch_id, pages } = await api.uploadBatch(files);
      setEv({ batch_id, pages_done: 0, pages_total: pages, pages_per_sec: 0, gpu: null, errors: 0, labs: 0, needs_review: 0, done: false });
      const src = new EventSource(api.batchEventsUrl(batch_id));
      es.current = src;
      src.onmessage = (m) => {
        const e = JSON.parse(m.data) as BatchEvent;
        setEv(e);
        if (e.done) { src.close(); setTimeout(() => nav("/labs"), 1200); }
      };
      src.onerror = () => { src.close(); setErr("Lost the progress stream. Your pages are saved; open Labs to see what was read."); setBusy(false); };
    } catch (e) {
      setErr((e as Error).message); setBusy(false);
    }
  };

  const pct = ev && ev.pages_total ? Math.round((ev.pages_done / ev.pages_total) * 100) : 0;
  const load = ev ? gpuLoad(ev.gpu) : null;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-3xl">Import documents</h1>
        <p className="text-muted mt-1">Drop a PDF or photos of lab reports. Pages are read in parallel, stored encrypted, and the results go to your lab history. Anything the reader is unsure about waits for your check.</p>
      </header>
      {err && <ErrorBox error={err} />}
      {!ev && (
        <div
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); start(e.dataTransfer.files); }}
          className={`card border-2 border-dashed text-center py-12 px-4 ${over ? "border-accent" : ""}`}
          data-testid="dropzone"
        >
          <FileUp className="mx-auto text-accent" size={36} aria-hidden />
          <p className="font-display text-2xl mt-3">Drop reports here</p>
          <p className="text-muted">PDF, JPEG or PNG. Several files at once are fine.</p>
          <button className="btn btn-primary mt-4" disabled={busy} onClick={() => input.current?.click()}>Choose files</button>
          <input ref={input} type="file" multiple accept="application/pdf,image/jpeg,image/png" className="sr-only" aria-label="Choose files to import" data-testid="file-input"
            onChange={(e) => { if (e.target.files) start(e.target.files); e.target.value = ""; }} />
        </div>
      )}
      {ev && (
        <section className="card text-center space-y-3 py-8" aria-live="polite" data-testid="progress">
          {ev.gpu && (
            <span className="chip font-bold" data-testid="gpu-chip"><Cpu size={14} aria-hidden /> AMD Instinct MI300X{load !== null ? `, GPU ${load}%` : ""}</span>
          )}
          <p className="font-display leading-none text-7xl tabular-nums" data-testid="pps">{ev.pages_per_sec.toFixed(1)}</p>
          <p className="text-muted font-bold">pages per second</p>
          <div className="h-2 rounded-full bg-line overflow-hidden mx-auto max-w-sm" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-sm text-muted">
            {ev.pages_done} of {ev.pages_total} pages, {ev.labs} results{ev.needs_review ? `, ${ev.needs_review} to check` : ""}{ev.errors ? `, ${ev.errors} pages failed` : ""}
          </p>
          {ev.done && <p className="font-bold">Done. Opening your lab history.</p>}
        </section>
      )}
    </div>
  );
}
