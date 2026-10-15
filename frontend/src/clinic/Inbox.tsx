import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtDate } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";

const stateWord: Record<string, string> = { none: "No brief", draft: "Draft, needs review", drafted: "Draft, needs review", final: "Final", finalized: "Final" };

export default function Inbox() {
  const { data, error, loading, reload } = useAsync(() => api.inbox(), []);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "No data"} retry={reload} />;
  if (data.length === 0) return <Empty title="No packages yet">Packages sent by patients appear here after they are unsealed.</Empty>;
  return (
    <section>
      <h1 className="text-3xl mb-3">Inbox</h1>
      <div className="overflow-x-auto card p-0">
        <table className="w-full text-[15px]">
          <thead><tr className="text-left text-muted border-b border-line">
            {["Patient", "Period", "Received", "Expires", "Terms", "Brief"].map((h) => <th key={h} className="px-3 py-2 font-bold">{h}</th>)}
          </tr></thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.package_id} className="border-b border-line last:border-0 hover:bg-paper">
                <td className="px-3 py-2"><Link className="font-bold text-accent underline underline-offset-4" to={`/p/${r.package_id}`}>{r.patient_alias}</Link></td>
                <td className="px-3 py-2">{fmtDate(r.period[0])} to {fmtDate(r.period[1])}</td>
                <td className="px-3 py-2">{fmtDate(r.received_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                <td className="px-3 py-2">{fmtDate(r.expires_at)}</td>
                <td className="px-3 py-2">{r.entities}</td>
                <td className="px-3 py-2">{stateWord[r.brief_state] ?? r.brief_state}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
