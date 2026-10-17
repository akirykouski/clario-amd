import { useState } from "react";
import { api } from "../api";
import { LangSwitch } from "../components/LangSwitch";
import { useT } from "../i18n";
import { AppMark } from "../components/AppIdentity";

export function Vault({ mode, onDone }: { mode: "setup" | "unlock"; onDone: () => void }) {
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

  return (
    <main className="min-h-screen max-w-md mx-auto px-5 py-10 flex flex-col justify-center relative">
      <div className="absolute top-4 right-5"><LangSwitch /></div>
      <h1 className="mb-3"><AppMark role="patient" size="lg" /></h1>
      <p className="text-muted mb-6">{setup ? t("vault.setupIntro") : t("vault.unlockIntro")}</p>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="pp" className="label">{t("vault.passphrase")}{setup && t("vault.atLeast")}</label>
          <input id="pp" className="input" type="password" autoComplete={setup ? "new-password" : "current-password"} value={pass} onChange={(e) => setPass(e.target.value)} autoFocus />
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
        <button className="btn btn-primary w-full" disabled={!valid || busy}>{busy ? t("common.oneMoment") : setup ? t("vault.create") : t("vault.unlock")}</button>
      </form>
    </main>
  );
}
