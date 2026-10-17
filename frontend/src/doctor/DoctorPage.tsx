import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import type { PriorCondition, PriorOpinion, VerifyHit } from "../types";
import { fmtDate } from "../lib";
import { ErrorBox } from "../components/ui";
import { LangSwitch } from "../components/LangSwitch";
import { useT } from "../i18n";

const POLL_MS = 1500;
type Phase = "form" | "waiting" | "open" | "closed";
type Closed = "rejected" | "expired" | "ended" | "badLink";

/** The doctor's page: no patient vault, no storage. The token lives in this component only. */
export default function DoctorPage() {
  const { t } = useT();
  const { code = "" } = useParams();
  const [phase, setPhase] = useState<Phase>("form");
  const [closed, setClosed] = useState<Closed | null>(null);
  const [name, setName] = useState("");
  const [surname, setSurname] = useState("");
  const [province, setProvince] = useState("");
  const [provinces, setProvinces] = useState<string[]>([]);
  const [hits, setHits] = useState<VerifyHit[] | null>(null);
  const [who, setWho] = useState("");
  const [opinions, setOpinions] = useState<PriorOpinion[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const token = useRef<string | null>(null);

  useEffect(() => {
    api.verifyRegister().then((r) => setProvinces(r.provinces)).catch(() => {});
    api.verifyDoctorStatus(code, "").then(() => {}).catch((e) => { if (e instanceof ApiError && e.status === 404) { setClosed("badLink"); setPhase("closed"); } });
  }, [code]);

  // Closing the tab drops the token; tell the server too so the session ends at once.
  useEffect(() => {
    const bye = () => { if (token.current) api.verifyEnd(code, token.current).catch(() => {}); };
    window.addEventListener("pagehide", bye);
    return () => window.removeEventListener("pagehide", bye);
  }, [code]);

  const finish = (c: Closed) => { token.current = null; setOpinions([]); setClosed(c); setPhase("closed"); };

  useEffect(() => {
    if (phase !== "waiting" || !token.current) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await api.verifyDoctorStatus(code, token.current!);
        if (stop) return;
        if (s.state === "confirmed") {
          const c = await api.verifyConclusions(code, token.current!);
          if (stop) return;
          setOpinions(c.previous); setMessage(c.message ?? null); setPhase("open");
        } else if (s.state === "rejected" || s.state === "expired" || s.state === "ended") finish(s.state);
      } catch (e) { if (!stop && e instanceof ApiError && e.status === 403) finish("ended"); }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, code]);

  const lookup = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null); setHits(null);
    try { setHits((await api.verifyLookup(code, { name: name.trim(), surname: surname.trim(), province: province.trim() })).hits); }
    catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };
  const choose = async (h: VerifyHit) => {
    setBusy(true); setErr(null);
    try { const c = await api.verifyClaim(code, h.id); token.current = c.doctor_token; setWho(c.hit_display); setPhase("waiting"); }
    catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };
  const end = async () => {
    const tk = token.current ?? undefined;
    finish("ended");
    await api.verifyEnd(code, tk).catch(() => {});
  };

  return (
    <div className="min-h-screen px-4 py-6 flex justify-center">
      <div className="glass w-full max-w-xl p-5 sm:p-7 space-y-5 self-start" data-testid="doctor-page">
        <header className="flex items-center justify-between gap-3">
          <span className="font-display font-semibold tracking-[-0.04em] leading-none text-3xl">Clario</span>
          <LangSwitch />
        </header>
        <h1 className="text-2xl">{t("doctor.title")}</h1>
        <p className="text-sm text-muted" data-testid="doctor-demo-note">{t("doctor.demoNote")}</p>
        {err && <ErrorBox error={err} />}

        {phase === "form" && (
          <>
            <p>{t("doctor.intro")}</p>
            <form className="space-y-3" onSubmit={lookup}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div><label className="label" htmlFor="dn">{t("doctor.name")}</label>
                  <input id="dn" className="input" autoComplete="given-name" required value={name} onChange={(e) => setName(e.target.value)} /></div>
                <div><label className="label" htmlFor="ds">{t("doctor.surname")}</label>
                  <input id="ds" className="input" autoComplete="family-name" required value={surname} onChange={(e) => setSurname(e.target.value)} /></div>
              </div>
              <div><label className="label" htmlFor="dp">{t("doctor.province")}</label>
                <input id="dp" className="input" list="doctor-provinces" required value={province} onChange={(e) => setProvince(e.target.value)} aria-describedby="dp-hint" />
                <datalist id="doctor-provinces">{provinces.map((p) => <option key={p} value={p} />)}</datalist>
                <p id="dp-hint" className="text-xs text-muted mt-1">{t("doctor.provinceHint")}</p></div>
              <button className="btn btn-primary w-full" type="submit" disabled={busy || !name.trim() || !surname.trim() || !province.trim()}>{t("doctor.lookup")}</button>
            </form>
            {hits && hits.length === 0 && <p role="status" className="text-sm" data-testid="doctor-nohits">{t("doctor.noHits")}</p>}
            {hits && hits.length > 0 && (
              <div className="space-y-2" data-testid="doctor-hits">
                <p className="label">{t("doctor.hits")}</p>
                {hits.map((h) => (
                  <div key={h.id} className="card flex flex-col sm:flex-row sm:items-center gap-2 justify-between">
                    <p className="font-bold">{h.display}</p>
                    <button className="btn btn-primary" onClick={() => choose(h)} disabled={busy}>{t("doctor.choose")}</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {phase === "waiting" && (
          <div className="card card-accent space-y-2" role="status" data-testid="doctor-waiting">
            <h2 className="text-lg">{t("doctor.waitingTitle")}</h2>
            <p>{t("doctor.waitingHint", { who })}</p>
            <button className="btn" onClick={end}>{t("doctor.end")}</button>
          </div>
        )}

        {phase === "open" && (
          <div className="space-y-4" data-testid="doctor-open">
            <div className="card card-amber text-sm font-semibold" role="note">{t("doctor.sessionOnly")}</div>
            <h2 className="text-xl">{t("doctor.openTitle")}</h2>
            <p className="text-sm text-muted">{t("doctor.openedFor", { who })}</p>
            {opinions.length === 0 && <p>{message ?? t("doctor.none")}</p>}
            {opinions.map((o, i) => <Opinion key={i} o={o} />)}
            <button className="btn w-full" onClick={end}>{t("doctor.end")}</button>
          </div>
        )}

        {phase === "closed" && closed && (
          <p className="card font-bold" role="status" data-testid="doctor-closed">
            {t(closed === "rejected" ? "doctor.rejected" : closed === "expired" ? "doctor.expired" : closed === "badLink" ? "doctor.badLink" : "doctor.ended")}
          </p>
        )}
      </div>
    </div>
  );
}

function Conditions({ title, list }: { title: string; list: PriorCondition[] }) {
  if (!list.length) return null;
  return (
    <div><p className="label">{title}</p>
      <div className="flex flex-wrap gap-2">{list.map((c, i) => <span key={i} className="chip chip-filled">{c.name}</span>)}</div></div>
  );
}
function Lines({ title, list }: { title: string; list: string[] }) {
  if (!list.length) return null;
  return <div><p className="label">{title}</p><ul className="list-disc pl-5 space-y-0.5">{list.map((x, i) => <li key={i}>{x}</li>)}</ul></div>;
}

function Opinion({ o }: { o: PriorOpinion }) {
  const { t } = useT();
  return (
    <article className="card space-y-3" data-testid="doctor-opinion">
      <p className="font-bold">{t("doctor.by", { who: o.clinician, date: o.date ? fmtDate(o.date, { day: "numeric", month: "long", year: "numeric" }) : "?" })}</p>
      <Conditions title={t("doctor.diagnosis")} list={o.diagnosis} />
      <Conditions title={t("doctor.considered")} list={o.conditions} />
      <Lines title={t("doctor.accepted")} list={o.accepted} />
      <Lines title={t("doctor.setAside")} list={o.rejected} />
      {o.notes && <div><p className="label">{t("doctor.notes")}</p><p>{o.notes}</p></div>}
    </article>
  );
}
