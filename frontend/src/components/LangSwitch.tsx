import { LANGS, LANG_NAME, setLang, useT, type Lang } from "../i18n";

/** EN | IT. Two buttons, current one pressed. Persisted by setLang. */
export function LangSwitch({ className = "" }: { className?: string }) {
  const { t, lang } = useT();
  return (
    <div role="group" aria-label={t("lang.label")} className={`inline-flex rounded-lg border border-line bg-panel overflow-hidden no-print ${className}`}>
      {LANGS.map((l: Lang) => (
        <button key={l} type="button" lang={l} aria-pressed={lang === l} title={LANG_NAME[l]}
          aria-label={lang === l ? LANG_NAME[l] : t("lang.switchTo", { name: LANG_NAME[l] })}
          onClick={() => setLang(l)}
          className={`min-h-[44px] min-w-[40px] px-2 text-sm font-bold ${lang === l ? "bg-accent text-accent-ink" : "text-muted"}`}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
