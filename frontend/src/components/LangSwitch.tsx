import { LANGS, LANG_NAME, setLang, useT, type Lang } from "../i18n";

/** EN | IT. Two buttons, current one pressed. Persisted by setLang. */
export function LangSwitch({ className = "" }: { className?: string }) {
  const { t, lang } = useT();
  return (
    <div role="group" aria-label={t("lang.label")} className={`inline-flex items-center p-1 gap-0.5 rounded-full border no-print ${className}`} style={{ borderColor: "var(--glass-edge)", background: "rgba(255,255,255,0.55)", boxShadow: "0 1px 0 0 #fff inset, 0 6px 14px -10px rgba(20,50,58,0.45)" }}>
      {LANGS.map((l: Lang) => (
        <button key={l} type="button" lang={l} aria-pressed={lang === l} title={LANG_NAME[l]}
          aria-label={lang === l ? LANG_NAME[l] : t("lang.switchTo", { name: LANG_NAME[l] })}
          onClick={() => setLang(l)}
          className={`min-h-[36px] min-w-[40px] px-2.5 rounded-full text-sm font-semibold transition-colors ${lang === l ? "bg-accent text-accent-ink shadow-[0_6px_14px_-8px_var(--accent)]" : "text-muted hover:text-ink"}`}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
