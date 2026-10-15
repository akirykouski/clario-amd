import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { ErrorBox, Loading } from "./components/ui";
import { LangSwitch } from "./components/LangSwitch";
import { useT } from "./i18n";
import PatientApp from "./patient/PatientApp";
import { DemoBanner } from "./patient/DemoBanner";
import ClinicApp from "./clinic/ClinicApp";

export default function App() {
  const { t } = useT();
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => { setErr(null); api.health().then(setHealth).catch((e: Error) => setErr(e.message)); };
  useEffect(load, []);
  if (err) return <div className="max-w-md mx-auto p-6 space-y-3"><LangSwitch /><ErrorBox error={t("app.cannotReach", { err })} retry={load} /></div>;
  if (!health) return <Loading label={t("app.connecting")} />;
  return (
    <>
      {health.demo_instance && <DemoBanner />}
      {health.mode === "clinic" ? <ClinicApp health={health} /> : <PatientApp />}
    </>
  );
}
