import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileUp, FlaskConical } from "lucide-react";
import { api } from "../api";
import { setLang, useT } from "../i18n";
import type { Persona } from "../types";

/** Synthetic personas for demos. Picking the Italian one also switches the app to Italian. */
export function DemoMenu({ onLoaded, open }: { onLoaded: () => void; open?: boolean }) {
  const { t, lang } = useT();
  const nav = useNavigate();
  const [persona, setPersona] = useState<Persona>(lang === "it" ? "giulia_it" : "giulia");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api.demo(persona);
      setLang(r.lang === "it" ? "it" : "en");
      setMsg(t("demo.loaded", { n: r.entries }));
      onLoaded();
    } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };

  return (
    <details open={open} className="card" data-testid="demo-menu">
      <summary className="cursor-pointer min-h-[44px] flex items-center gap-2 font-bold text-[15px]">
        <FlaskConical size={16} aria-hidden className="text-accent" />{t("demo.menuTitle")}
      </summary>
      <div className="space-y-3 pt-1">
        <p className="text-sm text-muted">{t("demo.menuIntro")}</p>
        <fieldset>
          <legend className="label">{t("demo.persona")}</legend>
          <div className="flex gap-2">
            {(["giulia", "giulia_it"] as Persona[]).map((p) => (
              <button key={p} type="button" className="btn flex-1" aria-pressed={persona === p} onClick={() => setPersona(p)}
                style={persona === p ? { borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
                {p === "giulia" ? t("demo.personaEn") : t("demo.personaIt")}
              </button>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-primary" onClick={load} disabled={busy}>{busy ? t("demo.loading") : t("demo.load")}</button>
          <button className="btn" onClick={() => nav("/import?samples=1")}><FileUp size={16} aria-hidden />{t("demo.referti")}</button>
        </div>
        <p className="text-sm text-muted">{t("demo.refertiHint")}</p>
        {msg && <p role="status" className="text-sm">{msg}</p>}
        {err && <p role="alert" className="text-sm text-strong">{err}</p>}
      </div>
    </details>
  );
}
