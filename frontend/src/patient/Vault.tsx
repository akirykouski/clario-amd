import { useState } from "react";
import { api } from "../api";
import { LangSwitch } from "../components/LangSwitch";
import { useT } from "../i18n";
import { AppMark } from "../components/AppIdentity";

export function Vault({ mode, demoOpen, onDone }: { mode: "setup" | "unlock"; demoOpen?: boolean; onDone: (o?: { tour?: boolean }) => void }) {
  const { t } = useT();
  const [pass, setPass] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const setup = mode === "setup";
  const valid = setup ? pass.length >= 12 && pass === confirm : pass.length > 0;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true); setErr(null);
    try { await (setup ? api.setup(pass) : api.unlock(pass)); onDone(); }
    catch (x) { setErr((x as Error).message); setBusy(false); }
  };
  const skip = async () => {
    setBusy(true); setErr(null);
    try { await api.demoOpen(); onDone({ tour: true }); } // a visitor on the demo gets the product tour at once
    catch (x) { setErr((x as Error).message); setBusy(false); }
  };

  return (
    <main className="min-h-screen max-w-[520px] mx-auto px-5 py-10 flex flex-col justify-center relative">
      <div className="absolute top-4 right-5"><LangSwitch /></div>
      <div aria-hidden className="grid grid-cols-7 gap-2 mb-6 px-6">
        {["var(--aqua)", "var(--lilac)", "var(--coral)", "var(--aqua)", "var(--lilac)", "var(--coral)", "var(--aqua)"].map((c, i) => (
          <span key={i} className="compartment !min-h-[46px] !rounded-[14px] pointer-events-none" style={{ ["--c" as string]: c }} />
        ))}
      </div>
      <div className="glass p-8 sm:p-10">
      <h1 className="mb-3"><AppMark role="patient" size="lg" /></h1>
      <p className="text-muted mb-6">{demoOpen ? t("vault.demoIntro") : setup ? t("vault.setupIntro") : t("vault.unlockIntro")}</p>
      {/* demo server: visitors have no passphrase, so opening the demo diary is the main action */}
      {demoOpen && (
        <div className="space-y-2 text-center mb-5 pb-5 border-b" style={{ borderColor: "var(--glass-rim)" }} data-testid="vault-skip">
          <button type="button" className="btn btn-primary w-full" onClick={skip} disabled={busy} autoFocus>{busy ? t("common.oneMoment") : t("vault.skipDemo")}</button>
          <p className="text-sm text-muted">{t("vault.skipHint")}</p>
        </div>
      )}
      {demoOpen && <p className="label mb-3">{t("vault.havePass")}</p>}
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="pp" className="label">{t("vault.passphrase")}{setup && t("vault.atLeast")}</label>
          <input id="pp" className="input" type="password" autoComplete={setup ? "new-password" : "current-password"} value={pass} onChange={(e) => setPass(e.target.value)} autoFocus={!demoOpen} />
          {setup && pass.length > 0 && pass.length < 12 && <p className="text-sm text-muted mt-1">{t("vault.moreChars", { n: 12 - pass.length })}</p>}
        </div>
        {setup && (
          <div>
            <label htmlFor="pp2" className="label">{t("vault.again")}</label>
            <input id="pp2" className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            {confirm && confirm !== pass && <p className="text-sm text-strong mt-1">{t("vault.differ")}</p>}
          </div>
        )}
        {setup && (
          <div className="card border-moderate text-[15px]" role="note">
            <strong>{t("vault.noRecoveryTitle")}</strong>{t("vault.noRecovery")}
          </div>
        )}
        {err && <p role="alert" className="text-strong text-sm">{err}</p>}
        <button className={`btn w-full ${demoOpen ? "" : "btn-primary"}`} disabled={!valid || busy}>{busy ? t("common.oneMoment") : setup ? t("vault.create") : t("vault.unlock")}</button>
      </form>
      </div>
    </main>
  );
}
