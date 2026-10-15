import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { BookOpen, CalendarDays, FlaskConical, Lock, Send, ShieldCheck, Waypoints } from "lucide-react";
import { api, onLocked } from "../api";
import type { VaultState } from "../types";
import { ErrorBox, Loading } from "../components/ui";
import { LangSwitch } from "../components/LangSwitch";
import { useT } from "../i18n";
import { Vault } from "./Vault";
import Today from "./Today";
import EntryPage from "./EntryPage";
import TimelinePage from "./TimelinePage";
import PatternsPage from "./PatternsPage";
import SharePage from "./SharePage";
import PrivacyPage from "./PrivacyPage";
import LabsPage from "./LabsPage";
import ImportPage from "./ImportPage";
import ReviewPage, { REVIEW_EVENT } from "./ReviewPage";

export default function PatientApp() {
  const nav = useNavigate();
  const { t } = useT();
  const loc = useLocation();
  const [vault, setVault] = useState<VaultState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [toReview, setToReview] = useState(0);

  const refresh = () => api.vault().then(setVault).catch((e: Error) => setErr(e.message));
  useEffect(() => { refresh(); }, []);
  useEffect(() => onLocked(() => { setVault((v) => (v ? { ...v, locked: true } : v)); nav("/unlock", { replace: true }); }), [nav]);

  const open0 = !!vault && vault.initialized && !vault.locked;
  useEffect(() => {
    if (!open0) return;
    const load = () => api.review().then((r) => setToReview(r.count)).catch(() => {});
    load();
    window.addEventListener(REVIEW_EVENT, load);
    const t = setInterval(load, 5000); // extraction runs in the background; new items can appear
    return () => { window.removeEventListener(REVIEW_EVENT, load); clearInterval(t); };
  }, [open0, loc.pathname]);

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
          <span className="font-display text-xl sm:text-2xl">Clario</span>
          <nav className="hidden md:flex gap-5 text-[15px] font-bold" aria-label={t("nav.main")}>
            {([["/", t("nav.today")], ["/timeline", t("nav.timeline")], ["/patterns", t("nav.patterns")], ["/labs", t("nav.labs")], ["/share", t("nav.share")]] as const).map(([to, l]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "text-accent" : "text-muted")}>{l}</NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-1.5 sm:gap-2">
            {toReview > 0 && (
              <Link to="/review" className="chip chip-review font-bold min-h-[44px] px-2.5 text-[13px] sm:text-sm" aria-label={t("nav.toReview", { n: toReview })}>{t("nav.toReview", { n: toReview })}</Link>
            )}
            <LangSwitch />
            <NavLink to="/privacy" className="btn !px-0 w-11" aria-label={t("nav.privacy")} title={t("nav.privacy")}><ShieldCheck size={18} aria-hidden /></NavLink>
            <button className="btn !px-0 w-11 sm:!px-4 sm:w-auto" onClick={lock} aria-label={t("nav.lockAria")} title={t("nav.lockAria")}><Lock size={16} aria-hidden /><span className="hidden sm:inline">{t("nav.lock")}</span></button>
          </div>
        </div>
      </header>
      <main className="max-w-2xl mx-auto px-4 py-5">
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/entry/:id" element={<EntryPage />} />
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/patterns" element={<PatternsPage />} />
          <Route path="/labs" element={<LabsPage />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/share" element={<SharePage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <nav aria-label={t("nav.main")} className="md:hidden fixed bottom-0 inset-x-0 z-20 bg-panel border-t border-line flex" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        <NavLink to="/" end className={tab}><BookOpen size={20} aria-hidden />{t("nav.today")}</NavLink>
        <NavLink to="/timeline" className={tab}><CalendarDays size={20} aria-hidden />{t("nav.timeline")}</NavLink>
        <NavLink to="/patterns" className={tab}><Waypoints size={20} aria-hidden />{t("nav.patterns")}</NavLink>
        <NavLink to="/labs" className={tab}><FlaskConical size={20} aria-hidden />{t("nav.labs")}</NavLink>
        <NavLink to="/share" className={tab}><Send size={20} aria-hidden />{t("nav.share")}</NavLink>
      </nav>
    </div>
  );
}
