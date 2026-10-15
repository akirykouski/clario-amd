import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Cpu, FileUp } from "lucide-react";
import { api } from "../api";
import { ErrorBox } from "../components/ui";
import { useEventStream } from "../components/useEventStream";
import { isOfflineBackend, useHealth } from "../components/useHealth";
import { useT } from "../i18n";
import { fmtNum, notifyReview } from "../lib";
import type { BatchEvent, BatchStarted } from "../types";

/** GPU load in percent from the reading `GET /api/system/gpu` puts on the progress stream (`util_pct`). */
export function gpuLoad(gpu: BatchEvent["gpu"]): number | null {
  if (!gpu) return null;
  for (const k of ["util_pct", "util", "utilization", "gpu_util", "gpu_util_percent", "util_percent"]) {
    const v = gpu[k];
    if (typeof v === "number") return Math.round(v);
  }
  return null;
}

export function gpuName(gpu: BatchEvent["gpu"]): string {
  const n = gpu?.gpu_name ?? gpu?.name;
  return typeof n === "string" && n ? n : "GPU";
}

export default function ImportPage() {
  const { t } = useT();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const input = useRef<HTMLInputElement>(null);
  const [stream, setStream] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ev, setEv] = useState<BatchEvent | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEventStream<BatchEvent>(
    stream,
    (e) => e.done,
    (e) => { setEv(e); if (e.done) { notifyReview(); setTimeout(() => nav("/labs"), 1200); } },
    () => { setErr(t("import.lost")); setBusy(false); },
  );

  const follow = ({ batch_id, pages }: BatchStarted) => {
    setEv({ batch_id, pages_done: 0, pages_total: pages, pages_per_sec: 0, gpu: null, errors: 0, labs: 0, needs_review: 0, done: false });
    setStream(api.batchEventsUrl(batch_id));
  };

  const run = async (go: () => Promise<BatchStarted>) => {
    setErr(null); setBusy(true); setEv(null);
    try { follow(await go()); } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const start = (list: FileList | File[]) => {
    const files = Array.from(list);
    if (files.length) run(() => api.uploadBatch(files));
  };
  const samples = () => run(() => api.demoDocuments());

  const auto = useRef(false);
  useEffect(() => {
    if (params.get("samples") === "1" && !auto.current) { auto.current = true; samples(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pct = ev && ev.pages_total ? Math.round((ev.pages_done / ev.pages_total) * 100) : 0;
  const load = ev ? gpuLoad(ev.gpu) : null;
  // Pages per second means nothing on the offline fixtures or before enough pages have been read.
  const offline = isOfflineBackend(useHealth());
  const showSpeed = !!ev && !offline && ev.pages_done >= 10;
  const realGpu = !!ev?.gpu && !offline && (load !== null || (typeof ev.gpu.gpu_name === "string" && !!ev.gpu.gpu_name) || (typeof ev.gpu.name === "string" && !!ev.gpu.name));
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-3xl">{t("import.title")}</h1>
        <p className="text-muted mt-1">{t("import.intro")}</p>
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
          <p className="font-display text-2xl mt-3">{t("import.drop")}</p>
          <p className="text-muted">{t("import.formats")}</p>
          <button className="btn btn-primary mt-4" disabled={busy} onClick={() => input.current?.click()}>{t("import.choose")}</button>
          <input ref={input} type="file" multiple accept="application/pdf,image/jpeg,image/png" className="sr-only" aria-label={t("import.chooseAria")} data-testid="file-input"
            onChange={(e) => { if (e.target.files) start(e.target.files); e.target.value = ""; }} />
          <p className="text-sm text-muted mt-5">{t("import.noFiles")}</p>
          <button className="btn-quiet btn" disabled={busy} onClick={samples} data-testid="use-samples">{t("import.useSamples")}</button>
        </div>
      )}
      {ev && (
        <section className="card text-center space-y-3 py-8" aria-live="polite" data-testid="progress">
          {realGpu && ev.gpu && (
            <span className="chip font-bold" data-testid="gpu-chip"><Cpu size={14} aria-hidden /> {gpuName(ev.gpu)}{load !== null ? `, ${t("import.gpu", { load })}` : ""}</span>
          )}
          {showSpeed ? (
            <>
              <p className="font-display leading-none text-7xl tabular-nums" data-testid="pps">{fmtNum(ev.pages_per_sec, 1)}</p>
              <p className="text-muted font-bold">{t("import.pps")}</p>
            </>
          ) : (
            <p className="font-display text-2xl" data-testid="pps-wait">{t(offline ? "import.demoModel" : "import.reading")}</p>
          )}
          <div className="h-2 rounded-full bg-line overflow-hidden mx-auto max-w-sm" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-sm text-muted">
            {t("import.progress", { done: ev.pages_done, total: ev.pages_total, labs: ev.labs })}{ev.needs_review ? t("import.toCheck", { n: ev.needs_review }) : ""}{ev.errors ? t("import.failed", { n: ev.errors }) : ""}
          </p>
          {ev.done && <p className="font-bold">{t("import.done")}</p>}
        </section>
      )}
    </div>
  );
}
