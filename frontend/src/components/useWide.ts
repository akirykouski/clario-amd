import { useEffect, useState } from "react";

/** True at desktop widths (lg, 1024px+). False where matchMedia is missing (tests, old browsers). */
export function useWide(query = "(min-width: 1024px)") {
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [wide, setWide] = useState(get);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const m = window.matchMedia(query);
    const on = () => setWide(m.matches);
    m.addEventListener?.("change", on);
    return () => m.removeEventListener?.("change", on);
  }, [query]);
  return wide;
}
