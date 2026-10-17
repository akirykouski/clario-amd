import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { api } from "../api";
import type { Care, ClinicKey, Profile, ShareResult } from "../types";
import { daysAgo, fmtDate, today } from "../lib";
import { ErrorBox } from "../components/ui";
import { useHealth } from "../components/useHealth";
import { useT, type Key } from "../i18n";
import VerifyDoctor from "./VerifyDoctor";

const LS = "clario.clinic_url";
function lsGet(): string { try { return localStorage.getItem(LS) ?? ""; } catch { return ""; } }
function lsSet(v: string) { try { localStorage.setItem(LS, v); } catch { /* ignore */ } }

export default function SharePage() {
  const { t } = useT();
  const health = useHealth();
  const [url, setUrl] = useState(lsGet() || "http://localhost:8800");
  const edited = useRef(false);
  // The server's CLARIO_CLINIC_URL (demo instance) is the default until the person types another address.
  useEffect(() => { if (health?.clinic_url && !edited.current) setUrl(health.clinic_url); }, [health?.clinic_url]);
  const [weeks, setWeeks] = useState(12);
  const [patterns, setPatterns] = useState(true);
  const [note, setNote] = useState("");
  const [hours, setHours] = useState(72);
  const [key, setKey] = useState<ClinicKey | null>(null);
  const [keyBusy, setKeyBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ShareResult | null>(null);
  const [age, setAge] = useState("");
  const [sex, setSex] = useState<NonNullable<Profile["sex"]> | "">("");
  const [withProfile, setWithProfile] = useState(true);
  const [second, setSecond] = useState(false);
  const [care, setCare] = useState<Care | null>(null);
  useEffect(() => {
    api.profile().then((p) => { setAge(p.age ? String(p.age) : ""); setSex(p.sex ?? ""); }).catch(() => {});
    api.care().then(setCare).catch(() => setCare(null));
  }, []);

  const checkKey = async () => {
    setKeyBusy(true); setErr(null); setKey(null);
    try { setKey(await api.clinicKey(url.trim())); lsSet(url.trim()); } catch (x) { setErr(t("share.unreachable", { err: (x as Error).message })); }
    setKeyBusy(false);
  };
  const send = async () => {
    setBusy(true); setErr(null);
    try {
      const n = Number(age);
      await api.saveProfile({ age: age.trim() && Number.isFinite(n) ? Math.round(n) : null, sex: sex || null });
      setRes(await api.share({ clinic_url: url.trim(), since: daysAgo(weeks * 7), until: today(), include_patterns: patterns, note: note.trim() || null,
                               expires_hours: hours, include_profile: withProfile, second_opinion: second }));
    } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };

  if (res) return <Success res={res} onAgain={() => setRes(null)} />;

  return (
    <div className="space-y-5">
      <header><h1 className="text-3xl">{t("share.title")}</h1>
        <p className="text-muted mt-1">{t("share.intro")}</p></header>
      <VerifyDoctor />
      <div>
        <label className="label" htmlFor="cu">{t("share.address")}</label>
        <div className="flex gap-2">
          <input id="cu" className="input" inputMode="url" value={url} onChange={(e) => { edited.current = true; setUrl(e.target.value); setKey(null); }} />
          <button className="btn" onClick={checkKey} disabled={keyBusy || !url.trim()}>{keyBusy ? t("common.checking") : t("share.check")}</button>
        </div>
      </div>
      {key && (
        <div className="card" role="status">
          <p className="font-bold">{key.clinic_name}</p>
          <p className="text-sm text-muted">{t("share.fingerprint")}</p>
          <p className="font-mono text-lg tracking-wide break-all">{key.fingerprint}</p>
        </div>
      )}
      <div className="space-y-5" data-tour="share-period">
      <fieldset>
        <legend className="label">{t("share.period")}</legend>
        <div className="flex gap-2">
          {[4, 8, 12].map((w) => (
            <button key={w} type="button" className="btn flex-1" aria-pressed={weeks === w} onClick={() => setWeeks(w)}
              style={weeks === w ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>{t("share.weeks", { n: w })}</button>
          ))}
        </div>
        <p className="text-sm text-muted mt-1">{t("share.range", { a: fmtDate(daysAgo(weeks * 7), { day: "numeric", month: "long" }), b: fmtDate(today(), { day: "numeric", month: "long" }) })}</p>
      </fieldset>
      <label className="flex items-center gap-2 min-h-[44px]"><input type="checkbox" className="w-5 h-5 accent-[var(--accent)]" checked={patterns} onChange={(e) => setPatterns(e.target.checked)} />{t("share.includePatterns")}</label>
      </div>
      <div><label className="label" htmlFor="nt">{t("share.noteLabel")}</label>
        <textarea id="nt" className="input min-h-[90px]" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("share.notePlaceholder")} /></div>
      <fieldset className="card space-y-2" data-testid="share-second">
        <legend className="sr-only">{t("share.second")}</legend>
        <label className="flex items-center gap-2 min-h-[44px] font-bold"><input type="checkbox" className="w-5 h-5 accent-[var(--accent)]" checked={second} onChange={(e) => setSecond(e.target.checked)} />{t("share.second")}</label>
        <p className="text-sm text-muted">{t("share.secondHint")}</p>
        {second && <p className="text-sm" data-testid="share-second-previous">{care?.previous
          ? t("share.secondPrevious", { who: care.previous.clinician, date: care.previous.date ? fmtDate(care.previous.date, { day: "numeric", month: "long" }) : "?" })
          : t("share.secondNoPrevious")}</p>}
        {care && (care.tried.length > 0 || care.tested.length > 0) && <CareList care={care} />}
      </fieldset>
      <fieldset className="card space-y-2" data-testid="share-about">
        <legend className="label px-1">{t("share.about")}</legend>
        <p className="text-sm text-muted">{t("share.aboutHint")}</p>
        <div className="flex flex-wrap gap-3">
          <label className="w-28"><span className="label">{t("share.age")}</span>
            <input className="input" inputMode="numeric" value={age} onChange={(e) => setAge(e.target.value.replace(/[^0-9]/g, "").slice(0, 3))} /></label>
          <label className="flex-1 min-w-[10rem]"><span className="label">{t("share.sex")}</span>
            <select className="input" value={sex} onChange={(e) => setSex(e.target.value as typeof sex)}>
              <option value="">{t("share.sexNone")}</option><option value="female">{t("share.sexFemale")}</option>
              <option value="male">{t("share.sexMale")}</option><option value="other">{t("share.sexOther")}</option>
            </select></label>
        </div>
        <label className="flex items-center gap-2 min-h-[44px]"><input type="checkbox" className="w-5 h-5 accent-[var(--accent)]" checked={withProfile} onChange={(e) => setWithProfile(e.target.checked)} />{t("share.includeProfile")}</label>
      </fieldset>
      <div><label className="label" htmlFor="ex">{t("share.expires")}</label>
        <select id="ex" className="input" value={hours} onChange={(e) => setHours(+e.target.value)}>
          <option value={24}>{t("share.day1")}</option><option value={72}>{t("share.day3")}</option><option value={168}>{t("share.day7")}</option><option value={720}>{t("share.day30")}</option>
        </select></div>
      {err && <ErrorBox error={err} />}
      <div className="sticky bottom-[72px] lg:static py-2 bg-paper/90">
        <button className="btn btn-primary w-full" onClick={send} disabled={busy || !key}>{busy ? t("common.sending") : !key ? t("share.checkFirst") : second ? t("share.sendSecond") : t("share.send")}</button>
      </div>
    </div>
  );
}

/** What was already tried and tested: facts that go with every share. Never the previous doctor's conclusions. */
function CareList({ care }: { care: Care }) {
  const { t } = useT();
  return (
    <div className="border-t border-line pt-2 space-y-2 text-sm" data-testid="share-care">
      {care.tried.length > 0 && <div><p className="font-bold">{t("share.tried")}</p>
        <ul className="space-y-0.5">{care.tried.map((x, i) => (
          <li key={i}>{x.treatment}{x.duration ? `, ${x.duration}` : ""}: <span className={x.effect === "none" || x.effect === "worse" ? "font-bold" : ""}>{t(`effect.${x.effect}` as Key)}</span></li>
        ))}</ul></div>}
      {care.tested.length > 0 && <div><p className="font-bold">{t("share.tested")}</p>
        <ul className="space-y-0.5">{care.tested.map((x, i) => (
          <li key={i}>{x.test}: {x.result}{x.date ? <span className="text-muted"> ({fmtDate(x.date)})</span> : null}</li>
        ))}</ul></div>}
      <p className="text-muted">{t("share.careHint")}</p>
    </div>
  );
}

function Success({ res, onAgain }: { res: ShareResult; onAgain: () => void }) {
  const { t } = useT();
  const [img, setImg] = useState<string | null>(null);
  const p = res.qr_payload;
  const direct = p.startsWith("data:image") ? p : p.trimStart().startsWith("<svg") ? `data:image/svg+xml;utf8,${encodeURIComponent(p)}` : null;
  useEffect(() => {
    if (direct) { setImg(direct); return; }
    QRCode.toDataURL(p, { margin: 1, width: 240, errorCorrectionLevel: "L" }).then(setImg).catch(() => setImg(null));
  }, [p, direct]);
  return (
    <div className="space-y-4">
      <h1 className="text-3xl">{t("share.sent")}</h1>
      <div className="card space-y-1" role="status">
        <p className="font-bold text-lg">{t("share.validUntil", { date: fmtDate(res.expires_at, { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) })}</p>
        <p>{t("share.counts", { entries: res.entries, m: res.mentions ?? res.entities, t: res.terms ?? res.entities })}</p>
        {res.second_opinion && <p data-testid="share-sent-second">{t("share.sentSecond")}</p>}
        <p className="text-xs text-muted">{t("share.package")} <span className="font-mono break-all">{res.package_id}</span></p>
      </div>
      <div className="card flex flex-col items-center gap-2">
        {img ? <img src={img} alt={t("share.qrAlt")} width={240} height={240} className="bg-white p-2 rounded" /> : <p className="text-sm text-muted">{t("share.qrFail")}</p>}
        <details className="w-full text-sm"><summary className="cursor-pointer min-h-[44px] flex items-center">{t("share.showText")}</summary><p className="font-mono break-all">{p}</p></details>
      </div>
      <button className="btn w-full" onClick={onAgain}>{t("share.again")}</button>
    </div>
  );
}
