import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtDate } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { useT, type Key } from "../i18n";

const stateKey: Record<string, Key> = { none: "inbox.state.none", draft: "inbox.state.draft", drafted: "inbox.state.draft", final: "inbox.state.final", finalized: "inbox.state.final" };

export default function Inbox() {
  const { t } = useT();
  const { data, error, loading, reload } = useAsync(() => api.inbox(), []);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.noData")} retry={reload} />;
  if (data.length === 0) return <Empty title={t("inbox.emptyTitle")}>{t("inbox.emptyText")}</Empty>;
  return (
    <section>
      <h1 className="text-3xl mb-3">{t("inbox.title")}</h1>
      <div className="overflow-x-auto card p-0">
        <table className="w-full text-[15px]">
          <thead><tr className="text-left text-muted border-b border-line">
            {(["inbox.patient", "inbox.period", "inbox.received", "inbox.expires", "inbox.terms", "inbox.brief"] as Key[]).map((h) => <th key={h} className="px-3 py-2 font-bold">{t(h)}</th>)}
          </tr></thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.package_id} className="border-b border-line last:border-0 hover:bg-paper">
                <td className="px-3 py-2"><Link className="font-bold text-accent underline underline-offset-4" to={`/p/${r.package_id}`}>{r.patient_alias}</Link></td>
                <td className="px-3 py-2">{t("share.range", { a: fmtDate(r.period[0]), b: fmtDate(r.period[1]) })}</td>
                <td className="px-3 py-2">{fmtDate(r.received_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                <td className="px-3 py-2">{fmtDate(r.expires_at)}</td>
                <td className="px-3 py-2">{r.terms === undefined ? r.entities : t("pkg.mentions", { m: r.entities, t: r.terms })}</td>
                <td className="px-3 py-2">{stateKey[r.brief_state] ? t(stateKey[r.brief_state]) : r.brief_state}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
