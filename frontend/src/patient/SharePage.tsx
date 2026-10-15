import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { api } from "../api";
import type { ClinicKey, ShareResult } from "../types";
import { daysAgo, fmtDate, today } from "../lib";
import { ErrorBox } from "../components/ui";
import { useT } from "../i18n";

const LS = "clario.clinic_url";
function lsGet(): string { try { return localStorage.getItem(LS) ?? ""; } catch { return ""; } }
function lsSet(v: string) { try { localStorage.setItem(LS, v); } catch { /* ignore */ } }

export default function SharePage() {
  const { t } = useT();
  const [url, setUrl] = useState(lsGet() || "http://localhost:8800");
  const [weeks, setWeeks] = useState(8);
  const [patterns, setPatterns] = useState(true);
  const [note, setNote] = useState("");
  const [hours, setHours] = useState(72);
  const [key, setKey] = useState<ClinicKey | null>(null);
  const [keyBusy, setKeyBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ShareResult | null>(null);

  const checkKey = async () => {
    setKeyBusy(true); setErr(null); setKey(null);
    try { setKey(await api.clinicKey(url.trim())); lsSet(url.trim()); } catch (x) { setErr(t("share.unreachable", { err: (x as Error).message })); }
    setKeyBusy(false);
  };
  const send = async () => {
    setBusy(true); setErr(null);
    try {
      setRes(await api.share({ clinic_url: url.trim(), since: daysAgo(weeks * 7), until: today(), include_patterns: patterns, note: note.trim() || null, expires_hours: hours }));
    } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };

  if (res) return <Success res={res} onAgain={() => setRes(null)} />;

  return (
    <div className="space-y-5">
      <header><h1 className="text-3xl">{t("share.title")}</h1>
        <p className="text-muted mt-1">{t("share.intro")}</p></header>
      <div>
        <label className="label" htmlFor="cu">{t("share.address")}</label>
        <div className="flex gap-2">
          <input id="cu" className="input" inputMode="url" value={url} onChange={(e) => { setUrl(e.target.value); setKey(null); }} />
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
      <div><label className="label" htmlFor="nt">{t("share.noteLabel")}</label>
        <textarea id="nt" className="input min-h-[90px]" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("share.notePlaceholder")} /></div>
      <div><label className="label" htmlFor="ex">{t("share.expires")}</label>
        <select id="ex" className="input" value={hours} onChange={(e) => setHours(+e.target.value)}>
          <option value={24}>{t("share.day1")}</option><option value={72}>{t("share.day3")}</option><option value={168}>{t("share.day7")}</option><option value={720}>{t("share.day30")}</option>
        </select></div>
      {err && <ErrorBox error={err} />}
      <div className="sticky bottom-[72px] md:static py-2 bg-paper/90">
        <button className="btn btn-primary w-full" onClick={send} disabled={busy || !key}>{busy ? t("common.sending") : key ? t("share.send") : t("share.checkFirst")}</button>
      </div>
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
        <p>{t("share.package")} <span className="font-mono">{res.package_id}</span></p>
        <p>{t("share.counts", { entries: res.entries, entities: res.entities })}</p>
        <p>{t("share.expiresAt", { date: fmtDate(res.expires_at, { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) })}</p>
      </div>
      <div className="card flex flex-col items-center gap-2">
        {img ? <img src={img} alt={t("share.qrAlt")} width={240} height={240} className="bg-white p-2 rounded" /> : <p className="text-sm text-muted">{t("share.qrFail")}</p>}
        <details className="w-full text-sm"><summary className="cursor-pointer min-h-[44px] flex items-center">{t("share.showText")}</summary><p className="font-mono break-all">{p}</p></details>
      </div>
      <button className="btn w-full" onClick={onAgain}>{t("share.again")}</button>
    </div>
  );
}
