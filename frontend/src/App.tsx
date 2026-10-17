import { useEffect, useState } from "react";
import { matchPath, useLocation } from "react-router-dom";
import { api } from "./api";
import type { Health } from "./types";
import { ErrorBox, Loading } from "./components/ui";
import { LangSwitch } from "./components/LangSwitch";
import { useT } from "./i18n";
import PatientApp from "./patient/PatientApp";
import { DemoBanner } from "./patient/DemoBanner";
import ClinicApp from "./clinic/ClinicApp";
import { useAppIdentity } from "./components/AppIdentity";
import DoctorPage from "./doctor/DoctorPage";

/** /doctor/:code is the visiting doctor's page: it never touches the patient vault, so it skips the setup and unlock gate. */
export default function App() {
  const { pathname } = useLocation();
  const doctor = matchPath("/doctor/:code", pathname);
  if (doctor) {
    // Rendered outside <Routes>, so the code is read from the match here (useParams would be empty).
    return <><div className="ambient" aria-hidden><span /><span /><span /></div><DoctorPage code={doctor.params.code} /></>;
  }
  return <Main />;
}

function Main() {
  const { t } = useT();
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => { setErr(null); api.health().then(setHealth).catch((e: Error) => setErr(e.message)); };
  useEffect(load, []);
  useAppIdentity(health ? (health.mode === "clinic" ? "clinic" : "patient") : null);
  if (err) return <div className="max-w-md mx-auto p-6 space-y-3"><LangSwitch /><ErrorBox error={t("app.cannotReach", { err })} retry={load} /></div>;
  if (!health) return <Loading label={t("app.connecting")} />;
  return (
    <>
      <div className="ambient" aria-hidden><span /><span /><span /></div>
      {health.demo_instance && <DemoBanner />}
      {health.mode === "clinic" ? <ClinicApp health={health} /> : <PatientApp />}
    </>
  );
}
