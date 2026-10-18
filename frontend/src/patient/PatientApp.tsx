import { useEffect, useState, useRef } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { BookOpen, CalendarDays, FlaskConical, Lock, Send, ShieldCheck, Waypoints } from "lucide-react";
import { motion } from "framer-motion";
import { useWide } from "../components/useWide";
import { api, onLocked } from "../api";
import type { VaultState } from "../types";
import { ErrorBox, Loading } from "../components/ui";
import { LangSwitch } from "../components/LangSwitch";
import { PATIENT_TOUR, TourButton } from "../components/Tour";
import { AppMark } from "../components/AppIdentity";
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
import ReviewPage from "./ReviewPage";

export default function PatientApp() {
  const nav = useNavigate();
  const { t } = useT();
  const loc = useLocation();
  const [vault, setVault] = useState<VaultState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const wide = useWide();
  // "Open the demo diary" also starts the product tour: the first screen after unlocking carries ?tour=1
  const tourNext = useRef(false);

  const refresh = () => api.vault().then(setVault).catch((e: Error) => setErr(e.message));
  useEffect(() => { refresh(); }, []);
  useEffect(() => onLocked(() => { setVault((v) => (v ? { ...v, locked: true } : v)); nav("/unlock", { replace: true }); }), [nav]);

  if (err) return <div className="max-w-md mx-auto p-6"><ErrorBox error={err} retry={refresh} /></div>;
  if (!vault) return <Loading />;

  const open = vault.initialized && !vault.locked;
  if (!open) {
    const target = vault.initialized ? "/unlock" : "/setup";
    if (loc.pathname !== target) return <Navigate to={target} replace />;
    return <Vault mode={vault.initialized ? "unlock" : "setup"} demoOpen={!!vault.demo_open} onDone={(o) => { tourNext.current = !!o?.tour; refresh(); }} />;
  }
  if (loc.pathname === "/setup" || loc.pathname === "/unlock") {
    const to = tourNext.current ? "/?tour=1" : "/";
    tourNext.current = false;
    return <Navigate to={to} replace />;
  }

  const lock = async () => { await api.lock().catch(() => {}); await refresh(); nav("/unlock"); };
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex-1 flex flex-col items-center justify-center gap-0.5 min-h-[56px] text-xs font-semibold ${isActive ? "text-accent" : "text-muted"}`;
  const items = [
    ["/", t("nav.today"), BookOpen], ["/timeline", t("nav.timeline"), CalendarDays], ["/patterns", t("nav.patterns"), Waypoints],
    ["/labs", t("nav.labs"), FlaskConical], ["/share", t("nav.share"), Send],
  ] as const;

  return (
    <div className="min-h-screen pb-24 lg:pb-0 lg:grid lg:grid-cols-[264px_minmax(0,1fr)]">
      {wide && <aside className="no-print">
        <div className="glass sticky top-[calc(var(--demo-h,0px)+16px)] m-4 mr-0 h-[calc(100vh-var(--demo-h,0px)-32px)] flex flex-col p-5">
          <span className="px-2 pt-1 pb-6"><AppMark role="patient" /></span>
          <nav className="flex flex-col gap-1" aria-label={t("nav.main")}>
            {items.map(([to, label, Icon]) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => `relative flex items-center gap-3 min-h-[46px] px-3.5 rounded-2xl text-[15px] font-semibold transition-colors ${isActive ? "text-ink" : "text-muted hover:text-ink"}`}>
                {({ isActive }) => (<>
                  {isActive && <motion.span layoutId="nav-liquid" aria-hidden className="absolute inset-0 rounded-2xl"
                    style={{ background: "linear-gradient(180deg, color-mix(in srgb, var(--aqua) 48%, #fff), color-mix(in srgb, var(--aqua) 30%, #fff))", border: "1px solid color-mix(in srgb, var(--aqua) 50%, #fff)", boxShadow: "0 1px 0 0 #fff inset, 0 10px 20px -14px color-mix(in srgb, var(--aqua) 90%, #000)" }}
                    transition={{ type: "spring", stiffness: 420, damping: 32, mass: 0.8 }} />}
                  <Icon size={19} aria-hidden className="relative" />
                  <span className="relative">{label}</span>
                </>)}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto space-y-3 pt-6">
            <div className="flex items-center gap-2"><LangSwitch /><TourButton steps={PATIENT_TOUR} /></div>
            <div className="flex items-center gap-2">
              <NavLink to="/privacy" className="btn !px-0 w-11" aria-label={t("nav.privacy")} title={t("nav.privacy")}><ShieldCheck size={18} aria-hidden /></NavLink>
              <button className="btn flex-1" onClick={lock} aria-label={t("nav.lockAria")} title={t("nav.lockAria")}><Lock size={16} aria-hidden />{t("nav.lock")}</button>
            </div>
          </div>
        </div>
      </aside>}
      {!wide && <header data-tour-inset="top" className="app-header sticky top-[var(--demo-h,0px)] z-20">
        <div className="px-4 sm:px-6 h-14 flex items-center gap-2 sm:gap-4">
          <span className="shrink-0"><AppMark role="patient" /></span>
          <div className="flex items-center gap-1.5 sm:gap-2 shrink-0 ml-auto">
            <LangSwitch />
            <TourButton steps={PATIENT_TOUR} />
            <NavLink to="/privacy" className="btn !px-0 w-11" aria-label={t("nav.privacy")} title={t("nav.privacy")}><ShieldCheck size={18} aria-hidden /></NavLink>
            <button className="btn !px-0 w-11 sm:!px-4 sm:w-auto" onClick={lock} aria-label={t("nav.lockAria")} title={t("nav.lockAria")}><Lock size={16} aria-hidden /><span className="hidden sm:inline">{t("nav.lock")}</span></button>
          </div>
        </div>
      </header>}
      <main className="w-full max-w-[1180px] mx-auto px-4 sm:px-6 lg:px-10 py-6 lg:py-8">
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
      {!wide && <nav aria-label={t("nav.main")} data-tour-inset="bottom" className="app-header fixed bottom-0 inset-x-0 z-20 !border-b-0 border-t flex"  style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        <NavLink to="/" end className={tab}><BookOpen size={20} aria-hidden />{t("nav.today")}</NavLink>
        <NavLink to="/timeline" className={tab}><CalendarDays size={20} aria-hidden />{t("nav.timeline")}</NavLink>
        <NavLink to="/patterns" className={tab}><Waypoints size={20} aria-hidden />{t("nav.patterns")}</NavLink>
        <NavLink to="/labs" className={tab}><FlaskConical size={20} aria-hidden />{t("nav.labs")}</NavLink>
        <NavLink to="/share" className={tab}><Send size={20} aria-hidden />{t("nav.share")}</NavLink>
      </nav>}
    </div>
  );
}
