import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { api } from "../api";
import type { ClinicKey, ShareResult } from "../types";
import { daysAgo, fmtDate, today } from "../lib";
import { ErrorBox } from "../components/ui";

const LS = "clario.clinic_url";
function lsGet(): string { try { return localStorage.getItem(LS) ?? ""; } catch { return ""; } }
function lsSet(v: string) { try { localStorage.setItem(LS, v); } catch { /* ignore */ } }

export default function SharePage() {
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
    try { setKey(await api.clinicKey(url.trim())); lsSet(url.trim()); } catch (x) { setErr(`Could not reach that clinic. ${(x as Error).message}`); }
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
      <header><h1 className="text-3xl">Share with your clinic</h1>
        <p className="text-muted mt-1">You choose what goes. Only terms you confirmed and the notes in the period you pick. It is sealed to the clinic and expires.</p></header>
      <div>
        <label className="label" htmlFor="cu">Clinic address</label>
        <div className="flex gap-2">
          <input id="cu" className="input" inputMode="url" value={url} onChange={(e) => { setUrl(e.target.value); setKey(null); }} />
          <button className="btn" onClick={checkKey} disabled={keyBusy || !url.trim()}>{keyBusy ? "Checking" : "Check"}</button>
        </div>
      </div>
      {key && (
        <div className="card" role="status">
          <p className="font-bold">{key.clinic_name}</p>
          <p className="text-sm text-muted">Key fingerprint. Compare it with the one the clinic shows you.</p>
          <p className="font-mono text-lg tracking-wide break-all">{key.fingerprint}</p>
        </div>
      )}
      <fieldset>
        <legend className="label">Period</legend>
        <div className="flex gap-2">
          {[4, 8, 12].map((w) => (
            <button key={w} type="button" className="btn flex-1" aria-pressed={weeks === w} onClick={() => setWeeks(w)}
              style={weeks === w ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>{w} weeks</button>
          ))}
        </div>
        <p className="text-sm text-muted mt-1">{fmtDate(daysAgo(weeks * 7), { day: "numeric", month: "long" })} to {fmtDate(today(), { day: "numeric", month: "long" })}</p>
      </fieldset>
      <label className="flex items-center gap-2 min-h-[44px]"><input type="checkbox" className="w-5 h-5 accent-[var(--accent)]" checked={patterns} onChange={(e) => setPatterns(e.target.checked)} />Include patterns</label>
      <div><label className="label" htmlFor="nt">Note for your doctor (optional)</label>
        <textarea id="nt" className="input min-h-[90px]" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What do you want to ask at the visit?" /></div>
      <div><label className="label" htmlFor="ex">Link expires after</label>
        <select id="ex" className="input" value={hours} onChange={(e) => setHours(+e.target.value)}>
          <option value={24}>1 day</option><option value={72}>3 days</option><option value={168}>7 days</option><option value={720}>30 days</option>
        </select></div>
      {err && <ErrorBox error={err} />}
      <div className="sticky bottom-[72px] md:static py-2 bg-paper/90">
        <button className="btn btn-primary w-full" onClick={send} disabled={busy || !key}>{busy ? "Sending" : key ? "Send to clinic" : "Check the clinic first"}</button>
      </div>
    </div>
  );
}

function Success({ res, onAgain }: { res: ShareResult; onAgain: () => void }) {
  const [img, setImg] = useState<string | null>(null);
  const p = res.qr_payload;
  const direct = p.startsWith("data:image") ? p : p.trimStart().startsWith("<svg") ? `data:image/svg+xml;utf8,${encodeURIComponent(p)}` : null;
  useEffect(() => {
    if (direct) { setImg(direct); return; }
    QRCode.toDataURL(p, { margin: 1, width: 240, errorCorrectionLevel: "L" }).then(setImg).catch(() => setImg(null));
  }, [p, direct]);
  return (
    <div className="space-y-4">
      <h1 className="text-3xl">Sent</h1>
      <div className="card space-y-1" role="status">
        <p>Package <span className="font-mono">{res.package_id}</span></p>
        <p>{res.entries} notes and {res.entities} confirmed terms.</p>
        <p>Expires {fmtDate(res.expires_at, { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}.</p>
      </div>
      <div className="card flex flex-col items-center gap-2">
        {img ? <img src={img} alt="QR code for this package" width={240} height={240} className="bg-white p-2 rounded" /> : <p className="text-sm text-muted">The QR code could not be drawn.</p>}
        <details className="w-full text-sm"><summary className="cursor-pointer min-h-[44px] flex items-center">Show the code as text</summary><p className="font-mono break-all">{p}</p></details>
      </div>
      <button className="btn w-full" onClick={onAgain}>Share again</button>
    </div>
  );
}
