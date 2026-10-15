import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { BookOpen, CalendarDays, Lock, Send, Waypoints } from "lucide-react";
import { api, onLocked } from "../api";
import type { VaultState } from "../types";
import { ErrorBox, Loading } from "../components/ui";
import { Vault } from "./Vault";
import Today from "./Today";
import EntryPage from "./EntryPage";
import TimelinePage from "./TimelinePage";
import PatternsPage from "./PatternsPage";
import SharePage from "./SharePage";

export default function PatientApp() {
  const nav = useNavigate();
  const loc = useLocation();
  const [vault, setVault] = useState<VaultState | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = () => api.vault().then(setVault).catch((e: Error) => setErr(e.message));
  useEffect(() => { refresh(); }, []);
  useEffect(() => onLocked(() => { setVault((v) => (v ? { ...v, locked: true } : v)); nav("/unlock", { replace: true }); }), [nav]);

  if (err) return <div className="max-w-md mx-auto p-6"><ErrorBox error={err} retry={refresh} /></div>;
  if (!vault) return <Loading />;

  const open = vault.initialized && !vault.locked;
  if (!open) {
    const target = vault.initialized ? "/unlock" : "/setup";
    if (loc.pathname !== target) return <Navigate to={target} replace />;
    return <Vault mode={vault.initialized ? "unlock" : "setup"} onDone={() => { refresh().then(() => nav("/", { replace: true })); }} />;
  }
  if (loc.pathname === "/setup" || loc.pathname === "/unlock") return <Navigate to="/" replace />;

  const lock = async () => { await api.lock().catch(() => {}); await refresh(); nav("/unlock"); };
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex-1 flex flex-col items-center justify-center gap-0.5 min-h-[56px] text-xs font-bold ${isActive ? "text-accent" : "text-muted"}`;

  return (
    <div className="min-h-screen pb-24 md:pb-8">
      <header className="sticky top-[var(--demo-h,0px)] z-20 bg-paper/95 backdrop-blur border-b border-line">
        <div className="max-w-2xl mx-auto px-4 h-14 flex items-center justify-between">
          <span className="font-display text-2xl">Clario</span>
          <nav className="hidden md:flex gap-5 text-[15px] font-bold" aria-label="Main">
            {[["/", "Today"], ["/timeline", "Timeline"], ["/patterns", "Patterns"], ["/share", "Share"]].map(([to, l]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "text-accent" : "text-muted")}>{l}</NavLink>
            ))}
          </nav>
          <button className="btn" onClick={lock} aria-label="Lock diary"><Lock size={16} aria-hidden /> Lock</button>
        </div>
      </header>
      <main className="max-w-2xl mx-auto px-4 py-5">
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/entry/:id" element={<EntryPage />} />
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/patterns" element={<PatternsPage />} />
          <Route path="/share" element={<SharePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <nav aria-label="Main" className="md:hidden fixed bottom-0 inset-x-0 z-20 bg-panel border-t border-line flex" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        <NavLink to="/" end className={tab}><BookOpen size={20} aria-hidden />Today</NavLink>
        <NavLink to="/timeline" className={tab}><CalendarDays size={20} aria-hidden />Timeline</NavLink>
        <NavLink to="/patterns" className={tab}><Waypoints size={20} aria-hidden />Patterns</NavLink>
        <NavLink to="/share" className={tab}><Send size={20} aria-hidden />Share</NavLink>
      </nav>
    </div>
  );
}
