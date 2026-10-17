import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { ShieldCheck } from "lucide-react";
import { api } from "../api";
import type { VerifyStarted, VerifyStatus } from "../types";
import { fmtDate } from "../lib";
import { ErrorBox } from "../components/ui";
import { useT, type Key } from "../i18n";

const POLL_MS = 1500;

/** The register line the doctor chose, shown to the patient with the two choices. Carries no conclusions: the patient
 *  build never receives them, so there is nothing here to render. */
export function VerifyConfirmCard({ hit, busy, onConfirm, onReject }: { hit: string; busy?: boolean; onConfirm: () => void; onReject: () => void }) {
  const { t } = useT();
  return (
    <div className="card card-accent space-y-3" role="status" data-testid="verify-claimed">
      <h3 className="text-lg font-display">{t("verify.claimedTitle")}</h3>
      <div>
        <p className="label">{t("verify.registerLine")}</p>
        <p className="text-lg font-bold" data-testid="verify-hit">{hit}</p>
      </div>
      <p className="text-sm text-muted">{t("verify.checkName")}</p>
      <div className="flex flex-col sm:flex-row gap-2">
        <button className="btn btn-primary flex-1" onClick={onConfirm} disabled={busy}>{t("verify.confirm")}</button>
        <button className="btn flex-1" onClick={onReject} disabled={busy}>{t("verify.notThis")}</button>
      </div>
    </div>
  );
}

function Log({ status }: { status: VerifyStatus }) {
  const { t } = useT();
  if (!status.audit.length) return null;
  return (
    <details className="text-sm" data-testid="verify-log">
      <summary className="cursor-pointer min-h-[44px] flex items-center">{t("verify.log")}</summary>
      <ul className="space-y-0.5">
        {status.audit.map((a, i) => (
          <li key={i}><span className="text-muted">{fmtDate(a.ts, { hour: "2-digit", minute: "2-digit" })}</span> {t(`verify.ev.${a.event}` as Key)}{a.who ? <span className="text-muted">, {a.who}</span> : null}</li>
        ))}
      </ul>
    </details>
  );
}

/** Share page section: start a session, show the link, wait for the doctor, confirm the register line, end. */
export default function VerifyDoctor() {
  const { t } = useT();
  const [session, setSession] = useState<VerifyStarted | null>(null);
  const [status, setStatus] = useState<VerifyStatus | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);

  const link = session ? `${window.location.origin}${session.doctor_path}` : "";
  useEffect(() => {
    if (!link) { setQr(null); return; }
    QRCode.toDataURL(link, { margin: 1, width: 200, errorCorrectionLevel: "M" }).then(setQr).catch(() => setQr(null));
  }, [link]);

  const code = session?.code;
  const state = status?.state;
  const polling = !!code && (!state || state === "waiting" || state === "claimed" || state === "confirmed");
  useEffect(() => {
    if (!polling || !code) return;
    let stop = false;
    const tick = () => api.verifyStatus(code).then((s) => { if (!stop && live.current) setStatus(s); }).catch((e: Error) => { if (!stop && live.current) setErr(e.message); });
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [polling, code]);

  const act = useCallback(async (fn: () => Promise<VerifyStatus | unknown>) => {
    setBusy(true); setErr(null);
    try { const r = await fn(); if (r && typeof r === "object" && "state" in r && "audit" in r) setStatus(r as VerifyStatus); } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  }, []);
  const start = () => act(async () => {
    const s = await api.verifyStart();
    setSession(s); setStatus(null);
    return null;
  });
  const end = () => code && act(async () => { await api.verifyEnd(code); return api.verifyStatus(code); });

  const closed = state === "rejected" || state === "ended" || state === "expired";
  return (
    <section className="card space-y-3" data-testid="verify-doctor" data-tour="verify-doctor">
      <h2 className="text-xl flex items-center gap-2"><ShieldCheck size={20} aria-hidden />{t("verify.title")}</h2>
      <p className="text-sm text-muted">{t("verify.intro")}</p>
      {err && <ErrorBox error={err} />}
      {!session && <button className="btn btn-primary w-full" onClick={start} disabled={busy}>{t("verify.start")}</button>}
      {session && !closed && state !== "confirmed" && state !== "claimed" && (
        <div className="space-y-2" data-testid="verify-waiting">
          <p className="font-bold">{t("verify.waiting")}</p>
          <p className="text-sm text-muted">{t("verify.waitingHint")}</p>
          <div className="flex flex-col items-center gap-2">
            {qr && <img src={qr} alt={t("verify.qrAlt")} width={200} height={200} className="bg-white p-2 rounded" />}
            <label className="label self-start" htmlFor="verify-link">{t("verify.linkLabel")}</label>
            <input id="verify-link" className="input font-mono text-sm" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
            <p className="text-sm text-muted self-start">{t("verify.validUntil", { time: fmtDate(session.expires_at, { hour: "2-digit", minute: "2-digit" }) })}</p>
          </div>
          <p className="text-xs text-muted">{t("verify.demoNote")}</p>
          <button className="btn w-full" onClick={end} disabled={busy}>{t("verify.endNow")}</button>
        </div>
      )}
      {session && state === "claimed" && status?.hit_display && (
        <>
          <VerifyConfirmCard hit={status.hit_display} busy={busy} onConfirm={() => act(() => api.verifyConfirm(session.code))} onReject={() => act(() => api.verifyReject(session.code))} />
          <p className="text-xs text-muted">{t("verify.demoNote")}</p>
        </>
      )}
      {session && state === "confirmed" && (
        <div className="space-y-2" role="status" data-testid="verify-confirmed">
          <p className="font-bold">{t("verify.opened", { name: status?.hit_display ?? "" })}</p>
          <p className="text-sm text-muted">{t("verify.noOpinionHere")}</p>
          <button className="btn w-full" onClick={end} disabled={busy}>{t("verify.endNow")}</button>
        </div>
      )}
      {session && closed && (
        <div className="space-y-2" role="status" data-testid="verify-closed">
          <p className="font-bold">{t(state === "rejected" ? "verify.rejected" : state === "expired" ? "verify.expired" : "verify.ended")}</p>
          <button className="btn w-full" onClick={() => { setSession(null); setStatus(null); }}>{t("verify.again")}</button>
        </div>
      )}
      {status && <Log status={status} />}
    </section>
  );
}
