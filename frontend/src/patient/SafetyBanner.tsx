import { useEffect, useState } from "react";
import { useT } from "../i18n";
import type { SafetyNotice } from "../types";

export function SafetyBanner({ notice, onDismiss }: { notice: SafetyNotice; onDismiss: () => void }) {
  const { t } = useT();
  const emergency = notice.level === "emergency";
  const [wait, setWait] = useState(emergency ? 5 : 0);
  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);
  return (
    <div role="alert" className="rounded-xl p-4 border-2 w-full" style={{ borderColor: emergency ? "var(--strong)" : "var(--moderate)", background: emergency ? "var(--danger-bg)" : "var(--panel)" }}>
      {emergency && <p className="font-display text-2xl mb-1">{t("safety.emergency")}</p>}
      <p>{notice.message}</p>
      <p className="text-sm text-muted mt-2">{t("safety.saved")}</p>
      <button className="btn mt-3" onClick={onDismiss} disabled={wait > 0}>{wait > 0 ? t("safety.closeIn", { n: wait }) : t("common.close")}</button>
    </div>
  );
}
