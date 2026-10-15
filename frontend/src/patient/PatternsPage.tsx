import { Link } from "react-router-dom";
import { Circle } from "lucide-react";
import { api } from "../api";
import { fmtDate } from "../lib";
import { Empty, ErrorBox, Loading, SignalPill } from "../components/ui";
import { useAsync } from "../components/useAsync";

export default function PatternsPage() {
  const { data, error, loading, reload } = useAsync(() => api.patterns(), []);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? "No data"} retry={reload} />;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-3xl">Patterns worth discussing with your doctor</h1>
        <p className="text-muted mt-1">Not a diagnosis. These are resemblances between what you recorded and published descriptions of conditions. Only terms you confirmed are used.</p>
      </header>
      {data.confirmed_terms < 3 && (
        <Empty title="Too early to show patterns">
          You have confirmed {data.confirmed_terms} {data.confirmed_terms === 1 ? "term" : "terms"}. Patterns need at least 3. Review your notes and confirm what is right.
        </Empty>
      )}
      {data.patterns.map((p) => (
        <article key={p.disease_id} className="card space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-2xl">{p.disease_name}</h2><SignalPill signal={p.signal} />
          </div>
          <p>{p.rationale}</p>
          <section aria-label="What you recorded">
            <h3 className="font-bold text-[15px]">What you recorded</h3>
            <ul className="mt-1 space-y-1 text-[15px]">
              {p.matched.map((m) => (
                <li key={m.hpo_id}>{m.label}: {m.count} {m.count === 1 ? "time" : "times"}, {fmtDate(m.first_seen)} to {fmtDate(m.last_seen)}.{" "}
                  {m.entry_ids.slice(0, 4).map((id, i) => <Link key={id} to={`/entry/${id}`} className="underline underline-offset-4 mr-1">note {i + 1}</Link>)}
                </li>
              ))}
            </ul>
          </section>
          {p.missing.length > 0 && (
            <section aria-label="Not recorded yet">
              <h3 className="font-bold text-[15px]">Not recorded yet</h3>
              <p className="text-sm text-muted">Only add these if they are true for you.</p>
              <ul className="mt-1 text-[15px]">{p.missing.map((t) => <li key={t.hpo_id} className="flex items-center gap-2 py-0.5"><Circle size={14} aria-hidden className="text-muted" />{t.label}</li>)}</ul>
            </section>
          )}
        </article>
      ))}
      {data.confirmed_terms >= 3 && data.patterns.length === 0 && <Empty title="No patterns to show yet">Keep writing. More confirmed notes make this clearer.</Empty>}
      {data.note && <p className="text-sm text-muted">{data.note}</p>}
    </div>
  );
}
