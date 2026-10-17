/** Where the model runs, in words for the screen. Backend ids come from GET /api/health `llm.backend`. */
export const TOKEN_FACTORY = "amd-token-factory";

/** "Gemma-4-31B-IT" -> "Gemma 4 31B", "gemma4:e4b" -> "Gemma 4 E4B"; any other id is shown as is. */
export function modelName(id?: string | null): string {
  if (!id) return "";
  const m = /gemma[-_ ]?4[-_ :]?(e?\d+b)/i.exec(id);
  return m ? `Gemma 4 ${m[1].toUpperCase()}` : id;
}

/** Models that read a document page: "MinerU2.5-Pro + Gemma-4-31B-IT" -> "MinerU2.5-Pro + Gemma 4 31B". */
export function readerName(model?: string | null): string {
  return (model ?? "").split(" + ").map((m) => modelName(m.trim())).filter(Boolean).join(" + ");
}

/** Label for a run on AMD Token Factory, else null (the caller keeps its own wording). */
export function tokenFactoryLabel(backend?: string | null, model?: string | null): string | null {
  return backend === TOKEN_FACTORY ? `${modelName(model) || "Gemma 4"} · AMD Token Factory` : null;
}
