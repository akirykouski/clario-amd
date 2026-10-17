import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ExternalLink, PenLine, Pencil, Plus, RotateCcw, X } from "lucide-react";
import { api } from "../api";
import type { Brief, BriefEditorItem, BriefLine, BriefSection, BriefWarning, Entry, SharePackage, Specialty } from "../types";
import { fmtDate } from "../lib";
import { ErrorBox, Spinner } from "../components/ui";
import { tn, useT, type Key } from "../i18n";

const NAME_KEY = "clario.clinicianName";
function savedName(): string {
  try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; }
}
function saveName(n: string) {
  try { localStorage.setItem(NAME_KEY, n); } catch { /* private window: the name is typed again */ }
}

/** One line in the editor. `key` is local; `id` is the drafted line it came from (absent for a line the clinician added). */
interface Card {
  key: string; id?: string; section: BriefSection; text: string; draft: string; cites: string[];
  origin: BriefEditorItem["origin"]; kind?: "patient_note" | null; rows?: BriefEditorItem["rows"];
  removed: boolean; keptAt: string | null; editing: boolean;
}

let seq = 0;
const newKey = () => `c${++seq}`;
const toCard = (i: BriefEditorItem): Card => ({
  key: newKey(), id: i.id, section: i.section, text: i.text, draft: i.text, cites: i.cites, origin: i.origin, kind: i.kind,
  rows: i.rows, removed: false, keptAt: null, editing: false,
});
/** What goes to the server: the cards still in the brief, with something written. */
const live = (cards: Card[]) => cards.filter((c) => !c.removed && c.text.trim());
const toLine = (c: Card): BriefLine => ({ ...(c.id ? { id: c.id } : {}), section: c.section, text: c.text.trim(), cites: c.cites });

/** "Edit and sign" as cards: one card per section in the specialty's order, one row per line. Click a line to edit it,
 *  × removes it (with undo), "+ Add line" adds the clinician's own. Code checks (citation check, hedge validator,
 *  diagnostic or dosing words) run on the server as the clinician edits and show on the line they belong to; a flagged
 *  line has to be edited, removed or kept anyway before Sign. Lab lines are a read-only table from the checked reports. */
export function BriefEditor({ pkg, specialty, focusLabel, pendingLabs, onCancel, onSigned, openedAt }: {
  pkg: SharePackage; specialty?: Specialty; focusLabel?: string; pendingLabs: number; onCancel: () => void; onSigned: (b: Brief) => void; openedAt: number;
}) {
  const { t } = useT();
  const [cards, setCards] = useState<Card[] | null>(null);
  const [sections, setSections] = useState<{ key: BriefSection; title: string }[]>([]);
  const [warnings, setWarnings] = useState<Record<string, BriefWarning[]>>({});
  const [checking, setChecking] = useState(false);
  const [name, setName] = useState(savedName);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const loaded = useRef(true);  // the loaded draft came with its warnings
  const entries = useMemo(() => new Map(pkg.entries.map((e) => [e.id, e])), [pkg.entries]);

  const byIndex = (list: Card[], ws: BriefWarning[]) => {
    const sent = live(list);
    const out: Record<string, BriefWarning[]> = {};
    for (const w of ws) {
      const c = w.item != null ? sent[w.item] : undefined;
      if (c) (out[c.key] ??= []).push(w);
    }
    return out;
  };
  const load = () => {
    setErr(null);
    api.briefText(pkg.package_id, specialty)
      .then((r) => {
        const list = (r.items ?? []).map(toCard);
        loaded.current = true;
        setSections(r.sections ?? []);
        setCards(list);
        setWarnings(byIndex(list, r.warnings));
      })
      .catch((x: Error) => setErr(x.message));
  };
  useEffect(load, [pkg.package_id, specialty]); // eslint-disable-line react-hooks/exhaustive-deps

  // what the checks depend on: the lines' text and whether they are in the brief (not the open editor)
  const sig = cards ? JSON.stringify(live(cards).map((c) => [c.key, c.text.trim()])) : "";
  useEffect(() => {
    if (!cards) return;
    if (loaded.current) { loaded.current = false; return; }
    setChecking(true);
    const snapshot = cards;
    const id = setTimeout(() => {
      api.checkBrief(pkg.package_id, live(snapshot).map(toLine), specialty)
        .then((r) => setWarnings(byIndex(snapshot, r.warnings)))
        .catch(() => undefined)
        .finally(() => setChecking(false));
    }, 400);
    return () => { clearTimeout(id); };
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (key: string, p: Partial<Card>) => setCards((cs) => cs && cs.map((c) => (c.key === key ? { ...c, ...p } : c)));
  const drop = (key: string) => setCards((cs) => cs && cs.filter((c) => c.key !== key));
  const add = (section: BriefSection) => setCards((cs) => {
    if (!cs) return cs;
    const card: Card = { key: newKey(), section, text: "", draft: "", cites: [], origin: "clinician", removed: false, keptAt: null, editing: true };
    const last = cs.map((c) => c.section).lastIndexOf(section);
    return last < 0 ? [...cs, card] : [...cs.slice(0, last + 1), card, ...cs.slice(last + 1)];
  });

  if (!cards) return err ? <ErrorBox error={err} retry={load} /> : <Spinner label={t("common.loading")} />;

  const flagged = (c: Card) => !c.removed && (warnings[c.key]?.length ?? 0) > 0 && c.keptAt !== c.text.trim();
  const attention = cards.filter(flagged).length;
  const empty = live(cards).length === 0;
  const canSign = !busy && !checking && !!name.trim() && !empty && attention === 0 && pendingLabs === 0 && !cards.some((c) => c.editing);

  const sign = async () => {
    setBusy(true); setErr(null);
    try {
      saveName(name.trim());
      onSigned(await api.signBrief(pkg.package_id, { items: live(cards).map(toLine), clinician: name.trim(), specialty, seconds: (Date.now() - openedAt) / 1000 }));
    } catch (x) { setErr((x as Error).message); }
    setBusy(false);
  };
  const preview = async () => {
    const w = window.open("", "_blank");  // opened in the click, so no popup blocker; filled when the PDF is back
    try {
      const url = await api.previewBrief(pkg.package_id, live(cards).map(toLine), specialty);
      if (w) w.location.href = url; else window.open(url, "_blank");
    } catch (x) { w?.close(); setErr((x as Error).message); }
  };

  return (
    <div className="no-print space-y-3" data-testid="brief-editor">
      {focusLabel && <p className="text-sm text-muted">{t("brief.focusFixed", { sp: focusLabel })}</p>}
      <p className="text-sm text-muted">{t("brief.editHint")}</p>
      {sections.map(({ key: s, title }) => {
        const rows = cards.filter((c) => c.section === s);
        return (
          <section key={s} className="card !p-0 overflow-hidden" aria-label={title} data-testid={`brief-section-${s}`}>
            <h3 className="px-4 pt-3 pb-2 text-lg">{title}</h3>
            {s === "labs"
              ? <LabTable cards={rows} onRemove={(k) => patch(k, { removed: true })} onUndo={(k) => patch(k, { removed: false })} />
              : rows.length === 0
                ? <p className="px-4 pb-1 text-sm text-muted">{t("brief.emptySection")}</p>
                : (
                  <ul className="border-t border-line divide-y divide-line">
                    {rows.map((c) => (
                      <LineRow key={c.key} c={c} entries={entries} warnings={warnings[c.key] ?? []} flagged={flagged(c)}
                        onPatch={(p) => patch(c.key, p)} onDrop={() => drop(c.key)} />
                    ))}
                  </ul>
                )}
            {s !== "labs" && (
              <div className="px-2 py-1.5 border-t border-line">
                <button className="btn btn-sm btn-quiet !no-underline" onClick={() => add(s)}><Plus size={15} aria-hidden /> {t("brief.addLine")}</button>
              </div>
            )}
          </section>
        );
      })}
      {err && <ErrorBox error={err} />}

      <div className="sticky bottom-0 z-20 -mx-1 px-3 py-3 rounded-xl border border-line bg-panel space-y-2"
        style={{ boxShadow: "0 -8px 24px -12px rgba(0,0,0,.35)" }} data-testid="brief-footer">
        <div className="flex items-center justify-between gap-2 flex-wrap text-sm" aria-live="polite">
          {attention > 0
            ? <span className="font-bold flex items-center gap-1.5" style={{ color: "var(--moderate)" }} data-testid="attention"><AlertTriangle size={15} aria-hidden /> {tn("brief.attention", attention)}</span>
            : <span className="text-muted" data-testid="attention">{checking ? t("brief.checking") : t("brief.allClear")}</span>}
          {pendingLabs > 0 && <span className="text-muted" data-testid="labs-pending">{tn("pkg.labsPending", pendingLabs)}</span>}
        </div>
        <div className="flex gap-2 flex-wrap items-end">
          <div className="flex-1 min-w-[12rem]">
            <label htmlFor="brief-signer" className="label">{t("brief.signName")}</label>
            <input id="brief-signer" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </div>
          <button className="btn btn-primary" onClick={sign} disabled={!canSign}><PenLine size={16} aria-hidden /> {t("brief.sign")}</button>
        </div>
        <div className="flex gap-1 flex-wrap items-center">
          <button className="btn btn-sm" onClick={load} disabled={busy}><RotateCcw size={14} aria-hidden /> {t("brief.reset")}</button>
          <button className="btn btn-sm" onClick={onCancel} disabled={busy}>{t("common.cancel")}</button>
          <button className="btn btn-sm btn-quiet ml-auto" onClick={preview} disabled={busy || empty}><ExternalLink size={14} aria-hidden /> {t("brief.previewPdf")}</button>
        </div>
      </div>
    </div>
  );
}

function LineRow({ c, entries, warnings, flagged, onPatch, onDrop }: {
  c: Card; entries: Map<string, Entry>; warnings: BriefWarning[]; flagged: boolean; onPatch: (p: Partial<Card>) => void; onDrop: () => void;
}) {
  const { t } = useT();
  const [text, setText] = useState(c.text);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (c.editing) { setText(c.text); box.current?.focus(); } }, [c.editing]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // grow with the text
    const el = box.current;
    if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
  }, [text, c.editing]);
  const done = () => {
    const v = text.replace(/\s+/g, " ").trim();
    if (!v && !c.id && !c.draft) { onDrop(); return; }  // an added line left empty is no line
    if (!v) { onPatch({ editing: false, removed: true }); return; }
    onPatch({ editing: false, text: v });
  };
  const cancel = () => { if (!c.text && !c.id) onDrop(); else onPatch({ editing: false }); };
  const ai = c.origin === "ai";
  const edited = c.text !== c.draft && !!c.id;

  if (c.removed) {
    return (
      <li className="px-4 py-2 flex items-center gap-2 text-sm" data-testid="line-removed">
        <span className="chip text-xs shrink-0">{t("brief.removed")}</span>
        <span className="truncate min-w-0 flex-1 line-through text-muted" title={c.text}>{c.text}</span>
        <button className="btn btn-sm shrink-0" onClick={() => onPatch({ removed: false })}>{t("brief.undo")}</button>
      </li>
    );
  }
  return (
    <li className="px-4 py-3 text-[15px]" data-testid="brief-line" data-flagged={flagged || undefined}
      style={flagged ? { background: "var(--amber-bg)", boxShadow: "inset 4px 0 0 var(--moderate)" } : undefined}>
      {c.kind === "patient_note" && <p className="text-sm font-bold text-muted">{t("brief.patientNote")}</p>}
      {c.editing ? (
        <div>
          <label htmlFor={`line-${c.key}`} className="sr-only">{t("brief.editLine")}</label>
          <textarea id={`line-${c.key}`} ref={box} rows={1} className="input resize-none overflow-hidden leading-snug" value={text}
            placeholder={t("brief.newLinePlaceholder")} onChange={(e) => setText(e.target.value)} onBlur={done}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); done(); }
              if (e.key === "Escape") { e.preventDefault(); cancel(); }
            }} />
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <p className="flex-1 min-w-0 cursor-text break-words" onClick={() => onPatch({ editing: true })}>{c.text}</p>
          <div className="flex shrink-0 -mr-2 -mt-1">
            <button className="btn btn-sm btn-quiet !px-2" onClick={() => onPatch({ editing: true })} aria-label={t("brief.editLine")} title={t("brief.editLine")}><Pencil size={15} aria-hidden /></button>
            <button className="btn btn-sm btn-quiet !px-2" onClick={() => onPatch({ removed: true })} aria-label={t("brief.removeLine")} title={t("brief.removeLine")}><X size={16} aria-hidden /></button>
          </div>
        </div>
      )}
      {(ai || edited || c.origin === "clinician" || c.cites.length > 0) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {ai && <span className="chip text-[11px] font-bold !py-0 !px-1.5" style={{ color: "var(--accent)", borderColor: "var(--app-edge)", background: "var(--app-badge)" }} title={t("brief.aiTagTitle")}>{t("brief.aiTag")}</span>}
          {edited && <span className="text-xs text-muted">{t("brief.editedTag")}</span>}
          {c.origin === "clinician" && <span className="text-xs text-muted">{t("brief.ownTag")}</span>}
          {[...c.cites].sort((x, y) => (entries.get(x)?.occurred_on ?? "").localeCompare(entries.get(y)?.occurred_on ?? ""))
            .map((id) => <CiteChip key={id} entry={entries.get(id)} />)}
        </div>
      )}
      {warnings.length > 0 && !c.editing && (
        <div className="mt-2 space-y-1" role="note" data-testid="brief-warning">
          {warnings.map((w, i) => (
            <p key={i} className="flex gap-1.5 items-start text-sm"><AlertTriangle size={15} className="shrink-0 mt-0.5" style={{ color: "var(--moderate)" }} aria-hidden /><span>{w.message}</span></p>
          ))}
          {flagged
            ? (
              <div className="flex gap-1.5 flex-wrap pt-1">
                <button className="btn btn-sm" onClick={() => onPatch({ editing: true })}><Pencil size={14} aria-hidden /> {t("brief.edit")}</button>
                <button className="btn btn-sm" onClick={() => onPatch({ removed: true })}><X size={14} aria-hidden /> {t("brief.removeLine")}</button>
                <button className="btn btn-sm" onClick={() => onPatch({ keptAt: c.text.trim() })}>{t("brief.keepAnyway")}</button>
              </div>
            )
            : <button className="text-xs text-muted underline underline-offset-2" onClick={() => onPatch({ keptAt: null })}>{t("brief.keptAnyway")}</button>}
        </div>
      )}
    </li>
  );
}

/** A cited diary note: its date; hover, focus or click shows what the patient wrote. */
function CiteChip({ entry }: { entry?: Entry }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  if (!entry) return null;
  const date = fmtDate(entry.occurred_on, { day: "numeric", month: "short" });
  const quote = entry.text.length > 280 ? `${entry.text.slice(0, 277)}…` : entry.text;
  return (
    <span className="relative group" onMouseLeave={() => setOpen(false)}>
      <button className="chip text-xs hover:border-accent" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        aria-label={t("brief.citeTitle", { date })}>{date}</button>
      <span role="tooltip" className={`${open ? "block" : "hidden"} group-hover:block group-focus-within:block absolute left-0 top-full z-30 mt-1 w-[min(20rem,80vw)] rounded-lg border border-line bg-panel p-3 text-sm shadow-lg`}>
        <span className="block text-xs font-bold text-muted mb-1">{t("brief.citeTitle", { date })}</span>
        <span className="block italic">“{quote}”</span>
      </span>
    </span>
  );
}

const FLAG_KEY: Record<string, Key> = { low: "pkg.lab.low", high: "pkg.lab.high", normal: "pkg.lab.normal", positive: "pkg.lab.positive" };

/** Lab lines from the checked reports: not AI text, read only. One block of rows per test; × leaves the test out. */
function LabTable({ cards, onRemove, onUndo }: { cards: Card[]; onRemove: (key: string) => void; onUndo: (key: string) => void }) {
  const { t } = useT();
  if (cards.length === 0) return <p className="px-4 pb-3 text-sm text-muted">{t("brief.emptySection")}</p>;
  const tables = cards.filter((c) => c.rows?.length);
  const notes = cards.filter((c) => !c.rows?.length);
  return (
    <div className="border-t border-line" data-testid="brief-labs">
      <p className="px-4 pt-2 text-xs text-muted">{t("brief.labsReadOnly")}</p>
      {tables.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead className="text-xs text-muted text-left">
              <tr>
                <th className="font-bold px-4 py-1.5">{t("pkg.lab.test")}</th>
                <th className="font-bold px-2 py-1.5">{t("pkg.lab.value")}</th>
                <th className="font-bold px-2 py-1.5">{t("pkg.lab.flag")}</th>
                <th className="font-bold px-2 py-1.5">{t("pkg.lab.date")}</th>
                <th className="font-bold px-2 py-1.5">{t("brief.colPage")}</th>
                <th className="px-2 py-1.5"><span className="sr-only">{t("brief.removeLine")}</span></th>
              </tr>
            </thead>
            {tables.map((c) => (
              <tbody key={c.key} className={`border-t border-line ${c.removed ? "opacity-50" : ""}`}>
                {(c.rows ?? []).map((r, i) => (
                  <tr key={i} className={c.removed ? "[&>td:not(:last-child)]:line-through" : ""}>
                    <td className="px-4 py-1 font-bold">{i === 0 ? r.test : ""}</td>
                    <td className="px-2 py-1 whitespace-nowrap">{r.value}{r.corrected ? " *" : ""}</td>
                    <td className="px-2 py-1 whitespace-nowrap" style={r.abnormal ? { color: "var(--strong)", fontWeight: 700 } : { color: "var(--muted)" }}>{r.flag ? t(FLAG_KEY[r.flag]) : "–"}</td>
                    <td className="px-2 py-1 whitespace-nowrap">{fmtDate(r.date, { day: "numeric", month: "short", year: "2-digit" })}</td>
                    <td className="px-2 py-1">{r.page}</td>
                    <td className="px-2 py-0.5 text-right">
                      {i === 0 && (c.removed
                        ? <button className="btn btn-sm btn-quiet !px-1" onClick={() => onUndo(c.key)}>{t("brief.undo")}</button>
                        : <button className="btn btn-sm btn-quiet !px-2 !min-h-[30px]" onClick={() => onRemove(c.key)} aria-label={`${t("brief.removeLine")}: ${r.test}`} title={t("brief.removeLine")}><X size={15} aria-hidden /></button>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
      {notes.map((c) => (
        <div key={c.key} className="px-4 py-2 border-t border-line text-sm flex items-center gap-2 text-muted">
          <span className={`flex-1 ${c.removed ? "line-through" : ""}`}>{c.text}</span>
          {c.removed
            ? <button className="btn btn-sm btn-quiet" onClick={() => onUndo(c.key)}>{t("brief.undo")}</button>
            : <button className="btn btn-sm btn-quiet !px-2 !min-h-[30px]" onClick={() => onRemove(c.key)} aria-label={t("brief.removeLine")}><X size={15} aria-hidden /></button>}
        </div>
      ))}
    </div>
  );
}
