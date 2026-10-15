import { useState } from "react";
import { api } from "../api";

export function Vault({ mode, onDone }: { mode: "setup" | "unlock"; onDone: () => void }) {
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
    <main className="min-h-screen max-w-md mx-auto px-5 py-10 flex flex-col justify-center">
      <h1 className="text-4xl mb-2">Clario</h1>
      <p className="text-muted mb-6">{setup ? "A private diary that stays on this device. Choose a passphrase to lock it." : "Your diary is locked. Enter your passphrase to open it."}</p>
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="pp" className="label">Passphrase{setup && " (at least 12 characters)"}</label>
          <input id="pp" className="input" type="password" autoComplete={setup ? "new-password" : "current-password"} value={pass} onChange={(e) => setPass(e.target.value)} autoFocus />
          {setup && pass.length > 0 && pass.length < 12 && <p className="text-sm text-muted mt-1">{12 - pass.length} more characters needed.</p>}
        </div>
        {setup && (
          <div>
            <label htmlFor="pp2" className="label">Type it again</label>
            <input id="pp2" className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            {confirm && confirm !== pass && <p className="text-sm text-strong mt-1">The two passphrases differ.</p>}
          </div>
        )}
        {setup && (
          <div className="card border-moderate text-[15px]" role="note">
            <strong>There is no recovery.</strong> Your notes are encrypted with this passphrase. If you forget it, nobody can open them, including us. Write it down somewhere safe.
          </div>
        )}
        {err && <p role="alert" className="text-strong text-sm">{err}</p>}
        <button className="btn btn-primary w-full" disabled={!valid || busy}>{busy ? "One moment" : setup ? "Create diary" : "Unlock"}</button>
      </form>
    </main>
  );
}
