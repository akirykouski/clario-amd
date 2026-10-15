import { Link, Route, Routes } from "react-router-dom";
import { Cpu, KeyRound } from "lucide-react";
import { api } from "../api";
import type { Health } from "../types";
import { useAsync } from "../components/useAsync";
import Inbox from "./Inbox";
import PackagePage from "./PackagePage";

export function ComputeBadge({ llm }: { llm: Health["llm"] }) {
  const amd = !!llm.is_amd;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm rounded-full border px-2.5 py-0.5"
      style={amd ? { color: "var(--accent)", borderColor: "var(--accent)", fontWeight: 700 } : { color: "var(--muted)", borderColor: "var(--line)" }}>
      <Cpu size={14} aria-hidden />
      {amd ? "AMD Instinct MI300X · vLLM" : `${llm.backend ?? "unknown backend"}${llm.model ? ` · ${llm.model}` : ""}`}
    </span>
  );
}

export default function ClinicApp({ health }: { health: Health }) {
  const key = useAsync(() => api.clinicKey(), []);
  return (
    <div className="min-h-screen">
      <header className="no-print border-b border-line bg-panel">
        <div className="max-w-[1400px] mx-auto px-6 h-14 flex items-center justify-between gap-4">
          <Link to="/" className="font-display text-2xl">Clario <span className="text-muted text-base">Clinic</span></Link>
          <div className="flex items-center gap-4 flex-wrap justify-end">
            <ComputeBadge llm={health.llm} />
            {key.data && <span className="text-sm text-muted inline-flex items-center gap-1.5" title="Clinic key fingerprint"><KeyRound size={14} aria-hidden />{key.data.clinic_name} <span className="font-mono text-ink">{key.data.fingerprint}</span></span>}
          </div>
        </div>
      </header>
      <main className="max-w-[1400px] mx-auto px-6 py-5">
        <Routes>
          <Route path="/" element={<Inbox />} />
          <Route path="/p/:id" element={<PackagePage />} />
          <Route path="*" element={<Inbox />} />
        </Routes>
      </main>
    </div>
  );
}
