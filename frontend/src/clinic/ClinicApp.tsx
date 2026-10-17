import { Link, Route, Routes } from "react-router-dom";
import { Cpu, KeyRound } from "lucide-react";
import { api } from "../api";
import type { Health } from "../types";
import { useAsync } from "../components/useAsync";
import Inbox from "./Inbox";
import PackagePage from "./PackagePage";
import PrivacyPage from "../patient/PrivacyPage";
import { LangSwitch } from "../components/LangSwitch";
import { CLINIC_TOUR, TourButton } from "../components/Tour";
import { useT } from "../i18n";
import { AppMark } from "../components/AppIdentity";
import { tokenFactoryLabel } from "../components/compute";

export function ComputeBadge({ llm }: { llm: Health["llm"] }) {
  const { t } = useT();
  const amd = !!llm.is_amd;
  const offline = llm.backend === "offline-fixtures";
  const tf = tokenFactoryLabel(llm.backend, llm.model);
  return (
    <span className="inline-flex items-center gap-1.5 text-sm rounded-full border px-2.5 py-0.5"
      style={amd ? { color: "var(--accent)", borderColor: "var(--accent)", fontWeight: 700 } : { color: "var(--muted)", borderColor: "var(--line)" }}>
      <Cpu size={14} aria-hidden />
      {tf ?? (amd ? "AMD Instinct MI300X · vLLM" : offline ? t("clinic.demoModel") : `${llm.backend ?? "unknown backend"}${llm.model ? ` · ${llm.model}` : ""}`)}
    </span>
  );
}

export default function ClinicApp({ health }: { health: Health }) {
  const { t } = useT();
  const key = useAsync(() => api.clinicKey(), []);
  return (
    <div className="min-h-screen">
      <header className="app-header no-print">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-2 min-h-14 flex items-center justify-between gap-x-4 gap-y-2 flex-wrap">
          <Link to="/" className="shrink-0"><AppMark role="clinic" /></Link>
          <div className="flex items-center gap-x-4 gap-y-2 flex-wrap justify-end">
            <Link to="/privacy" className="text-sm font-bold text-accent underline underline-offset-4">{t("clinic.callLog")}</Link>
            <LangSwitch />
            <TourButton steps={CLINIC_TOUR} />
            <ComputeBadge llm={health.llm} />
          </div>
          {key.data && <span className="w-full text-sm text-muted inline-flex items-center gap-1.5 flex-wrap" title={t("clinic.keyTitle")}><KeyRound size={14} aria-hidden />{key.data.clinic_name} <span className="font-mono text-ink break-all">{key.data.fingerprint}</span></span>}
        </div>
      </header>
      <main className="max-w-[1400px] mx-auto px-4 sm:px-6 py-5">
        <Routes>
          <Route path="/" element={<Inbox />} />
          <Route path="/p/:id" element={<PackagePage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="*" element={<Inbox />} />
        </Routes>
      </main>
    </div>
  );
}
