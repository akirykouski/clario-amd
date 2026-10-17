import { useEffect } from "react";
import { Stethoscope, UserRound } from "lucide-react";
import { useT } from "../i18n";

export type AppRole = "patient" | "clinic";

const ROLE_ICON = { patient: UserRound, clinic: Stethoscope } as const;

/** Header wordmark: "Clario · Patient" or "Clario · Clinic", with the role badge in the app's accent. */
export function AppMark({ role, size = "md" }: { role: AppRole; size?: "md" | "lg" }) {
  const { t } = useT();
  const Icon = ROLE_ICON[role];
  const big = size === "lg";
  return (
    <span className={`inline-flex items-center min-w-0 ${big ? "gap-2" : "gap-1.5 sm:gap-2"}`} data-testid="app-mark" data-role={role}>
      <span className={`font-display font-semibold tracking-[-0.04em] leading-none ${big ? "text-5xl" : "text-2xl sm:text-[28px]"}`}>Clario</span>
      <span aria-hidden className={`text-muted leading-none ${big ? "" : "hidden sm:inline"}`}>·</span>
      <span className={`app-role ${big ? "app-role-lg" : ""}`}>
        <Icon size={big ? 16 : 14} strokeWidth={2.25} aria-hidden className={big ? "" : "hidden sm:block"} />
        {t(`app.role.${role}`)}
      </span>
    </span>
  );
}

/** Marks the document with the running app: accent tokens (index.css), tab title, favicon and theme colour. */
export function useAppIdentity(role: AppRole | null) {
  const { t, lang } = useT();
  useEffect(() => {
    if (!role || typeof document === "undefined") return;
    const root = document.documentElement;
    root.dataset.app = role;
    const icon = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
    if (icon) icon.href = `/favicon-${role}.svg`;
    const paper = getComputedStyle(root).getPropertyValue("--paper").trim();
    const meta = document.querySelector<HTMLMetaElement>("meta[name='theme-color']");
    if (meta && paper) meta.content = paper;
  }, [role]);
  useEffect(() => {
    if (!role || typeof document === "undefined") return;
    // Pages that set their own title ("Today · Clario Patient") keep it; only the bare app title follows the language.
    if (document.title === "Clario" || /^Clario [A-Za-z]+$/.test(document.title)) {
      document.title = t("app.tabTitle", { role: t(`app.role.${role}`) });
    }
  }, [role, t, lang]);
}
