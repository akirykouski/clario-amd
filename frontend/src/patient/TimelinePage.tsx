import { Link } from "react-router-dom";
import { api } from "../api";
import { buildHeat, fmtDate } from "../lib";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAsync } from "../components/useAsync";
import { HeatStrip } from "../components/HeatStrip";
import { termLabel, useT } from "../i18n";

export default function TimelinePage() {
  const { t } = useT();
  const { data, error, loading, reload } = useAsync(() => api.timeline(), []);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? t("common.noData")} retry={reload} />;
  if (data.days.length === 0) return <Empty title={t("timeline.emptyTitle")}>{t("timeline.emptyText")}</Empty>;
  const dates: Record<string, string> = {};
  data.days.forEach((d) => d.entries.forEach((e) => { dates[e.id] = d.date; }));
  const heat = buildHeat(data.terms, dates);
  return (
    <div className="space-y-6">
      <h1 className="text-3xl">{t("timeline.title")}</h1>
      <section aria-labelledby="hs"><h2 id="hs" className="text-xl mb-2">{t("timeline.byWeek")}</h2>
        {heat.rows.length === 0 ? <p className="text-muted">{t("timeline.confirmHint")}</p> : <HeatStrip heat={heat} />}
      </section>
      <section aria-labelledby="dy"><h2 id="dy" className="text-xl mb-2">{t("timeline.days")}</h2>
        <ol className="space-y-3">
          {data.days.map((d) => (
            <li key={d.date} className="card">
              <p className="font-bold">{fmtDate(d.date, { weekday: "long", day: "numeric", month: "long" })}</p>
              {d.entries.map((e) => <p key={e.id} className="text-[15px] mt-1 line-clamp-2"><Link to={`/entry/${e.id}`} className="underline underline-offset-4">{e.text}</Link></p>)}
              <div className="mt-2 flex flex-wrap gap-1.5">{d.terms.map((x) => <span key={x.hpo_id} className="chip">{termLabel(x.hpo_id, x.label)}</span>)}</div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
