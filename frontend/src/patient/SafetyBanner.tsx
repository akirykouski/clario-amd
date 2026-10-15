import { useEffect, useState } from "react";
import type { SafetyNotice } from "../types";

export function SafetyBanner({ notice, onDismiss }: { notice: SafetyNotice; onDismiss: () => void }) {
  const emergency = notice.level === "emergency";
  const [wait, setWait] = useState(emergency ? 5 : 0);
  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);
  return (
    <div role="alert" className="rounded-xl p-4 border-2 w-full" style={{ borderColor: emergency ? "var(--strong)" : "var(--moderate)", background: emergency ? "var(--danger-bg)" : "var(--panel)" }}>
      {emergency && <p className="font-display text-2xl mb-1">If this is happening now, call 112</p>}
      <p>{notice.message}</p>
      <p className="text-sm text-muted mt-2">Your note was saved.</p>
      <button className="btn mt-3" onClick={onDismiss} disabled={wait > 0}>{wait > 0 ? `You can close this in ${wait}` : "Close"}</button>
    </div>
  );
}
