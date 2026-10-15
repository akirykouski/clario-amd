import { useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { ErrorBox, Loading } from "./components/ui";
import PatientApp from "./patient/PatientApp";
import ClinicApp from "./clinic/ClinicApp";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => { setErr(null); api.health().then(setHealth).catch((e: Error) => setErr(e.message)); };
  useEffect(load, []);
  if (err) return <div className="max-w-md mx-auto p-6"><ErrorBox error={`Cannot reach the Clario server. ${err}`} retry={load} /></div>;
  if (!health) return <Loading label="Connecting" />;
  return health.mode === "clinic" ? <ClinicApp health={health} /> : <PatientApp />;
}
