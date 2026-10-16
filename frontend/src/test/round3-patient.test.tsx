import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { prettyUnit } from "../lib";
import { setLang, patientTermLine } from "../i18n";
import { SignalPill } from "../components/ui";

afterEach(() => { vi.restoreAllMocks(); setLang("en"); });

describe("units", () => {
  it("prints superscripts and micro signs", () => {
    expect(prettyUnit("10^3/uL")).toBe("10³/µL");
    expect(prettyUnit("ug/dL")).toBe("µg/dL");
    expect(prettyUnit("mg/dL")).toBe("mg/dL");
    expect(prettyUnit("U/L")).toBe("U/L");
  });
});

describe("patient term lines never show an HPO code or an English label in Italian", () => {
  it("en shows the label, it only a shipped Italian name", () => {
    expect(patientTermLine("HP:0002315", "Headache", "Pain in the head")).toBe("Headache");
    expect(patientTermLine("HP:0002315", "Headache", "Headache")).toBeNull();
    setLang("it");
    expect(patientTermLine("HP:0002315", "Headache", "Dolore")).toBe("Mal di testa");
    expect(patientTermLine("HP:9999999", "Generalized morning stiffness", "Rigidità")).toBeNull();
  });
});

describe("signal pill", () => {
  it("opens a plain explainer that is not a diagnosis", () => {
    render(<SignalPill signal="strong" />);
    fireEvent.click(screen.getByRole("button", { name: /strong signal/i }));
    expect(screen.getByRole("note").textContent).toMatch(/not a diagnosis/i);
    expect(screen.getByRole("note").textContent).not.toMatch(/%/);
  });
});
