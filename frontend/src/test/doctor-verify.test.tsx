import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api, ApiError } from "../api";
import { en } from "../i18n/en";
import { it as itDict } from "../i18n/it";
import DoctorPage from "../doctor/DoctorPage";
import VerifyDoctor, { VerifyConfirmCard } from "../patient/VerifyDoctor";
import type { VerifyStatus } from "../types";

afterEach(() => { vi.restoreAllMocks(); });

const HIT = "Rossi Maria, Ordine di Milano, Albo medici chirurghi";
const DIAGNOSIS = "Fibromyalgia";

function doctor() {
  return render(<MemoryRouter initialEntries={["/doctor/ABCD2345"]}><Routes><Route path="/doctor/:code" element={<DoctorPage />} /></Routes></MemoryRouter>);
}
function mockDoctorBase() {
  vi.spyOn(api, "verifyRegister").mockResolvedValue({ register: "demo", register_note: "", provinces: ["Milano", "Roma"] });
  vi.spyOn(api, "verifyDoctorStatus").mockResolvedValue({ state: "waiting" });
}

describe("doctor page", () => {
  it("looks up, claims a hit, waits for the patient, then shows the conclusions with the session note", async () => {
    mockDoctorBase();
    const lookup = vi.spyOn(api, "verifyLookup").mockResolvedValue({ register: "demo", register_note: "", hits: [{ id: "demo-001", display: HIT }] });
    const claim = vi.spyOn(api, "verifyClaim").mockResolvedValue({ register: "demo", doctor_token: "tok123", hit_display: HIT });
    let confirmed = false;
    vi.spyOn(api, "verifyDoctorStatus").mockImplementation(async (_c, tk) => ({ state: tk && confirmed ? "confirmed" : tk ? "claimed" : "waiting" }));
    const conclusions = vi.spyOn(api, "verifyConclusions").mockResolvedValue({
      register: "demo", doctor: HIT, message: null,
      previous: [{ clinician: "GP", date: "2026-09-01", diagnosis: [{ name: DIAGNOSIS }], conditions: [{ name: "Stress-related pain" }], accepted: [], rejected: [], notes: "Review in 3 months" }],
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const user = userEvent.setup();
    doctor();
    expect(screen.getByTestId("doctor-demo-note")).toHaveTextContent(en["doctor.demoNote"]);
    const go = screen.getByRole("button", { name: en["doctor.lookup"] });
    expect(go).toBeDisabled();
    await user.type(screen.getByLabelText(en["doctor.name"]), "maria");
    await user.type(screen.getByLabelText(en["doctor.surname"]), "ROSSI");
    await user.type(screen.getByLabelText(en["doctor.province"]), "milano");
    await user.click(go);
    expect(lookup).toHaveBeenCalledWith("ABCD2345", { name: "maria", surname: "ROSSI", province: "milano" });
    expect(await screen.findByText(HIT)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en["doctor.choose"] }));
    expect(claim).toHaveBeenCalledWith("ABCD2345", "demo-001");
    expect(await screen.findByText(en["doctor.waitingTitle"])).toBeInTheDocument();
    expect(conclusions).not.toHaveBeenCalled();
    confirmed = true;
    expect(await screen.findByTestId("doctor-open", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(conclusions).toHaveBeenCalledWith("ABCD2345", "tok123");
    expect(screen.getByText(DIAGNOSIS)).toBeInTheDocument();
    expect(screen.getByText("Stress-related pain")).toBeInTheDocument();
    expect(screen.getByText(en["doctor.sessionOnly"])).toBeInTheDocument();
    expect(setItem.mock.calls.flat().join(" ")).not.toContain("tok123");
  });

  it("says so when the register has no match", async () => {
    mockDoctorBase();
    vi.spyOn(api, "verifyLookup").mockResolvedValue({ register: "demo", register_note: "", hits: [] });
    const user = userEvent.setup();
    doctor();
    await user.type(screen.getByLabelText(en["doctor.name"]), "Zed");
    await user.type(screen.getByLabelText(en["doctor.surname"]), "Nobody");
    await user.type(screen.getByLabelText(en["doctor.province"]), "Roma");
    await user.click(screen.getByRole("button", { name: en["doctor.lookup"] }));
    expect(await screen.findByTestId("doctor-nohits")).toBeInTheDocument();
  });

  it("shows a dead link when the code is unknown", async () => {
    vi.spyOn(api, "verifyRegister").mockResolvedValue({ register: "demo", register_note: "", provinces: [] });
    vi.spyOn(api, "verifyDoctorStatus").mockRejectedValue(new ApiError(404, "unknown code"));
    doctor();
    expect(await screen.findByTestId("doctor-closed")).toHaveTextContent(en["doctor.badLink"]);
  });

  it("ends the session when the patient declines", async () => {
    vi.spyOn(api, "verifyRegister").mockResolvedValue({ register: "demo", register_note: "", provinces: [] });
    vi.spyOn(api, "verifyLookup").mockResolvedValue({ register: "demo", register_note: "", hits: [{ id: "demo-001", display: HIT }] });
    vi.spyOn(api, "verifyClaim").mockResolvedValue({ register: "demo", doctor_token: "t", hit_display: HIT });
    vi.spyOn(api, "verifyDoctorStatus").mockImplementation(async (_c, tk) => ({ state: tk ? "rejected" : "waiting" }));
    const conclusions = vi.spyOn(api, "verifyConclusions");
    const user = userEvent.setup();
    doctor();
    await user.type(screen.getByLabelText(en["doctor.name"]), "Maria");
    await user.type(screen.getByLabelText(en["doctor.surname"]), "Rossi");
    await user.type(screen.getByLabelText(en["doctor.province"]), "Milano");
    await user.click(screen.getByRole("button", { name: en["doctor.lookup"] }));
    await user.click(await screen.findByRole("button", { name: en["doctor.choose"] }));
    expect(await screen.findByTestId("doctor-closed")).toHaveTextContent(en["doctor.rejected"]);
    expect(conclusions).not.toHaveBeenCalled();
  });
});

describe("patient confirm card", () => {
  it("shows the register line with confirm and decline, and calls back", async () => {
    const ok = vi.fn(), no = vi.fn();
    const user = userEvent.setup();
    render(<VerifyConfirmCard hit={HIT} onConfirm={ok} onReject={no} />);
    expect(screen.getByTestId("verify-hit")).toHaveTextContent(HIT);
    await user.click(screen.getByRole("button", { name: en["verify.confirm"] }));
    await user.click(screen.getByRole("button", { name: en["verify.notThis"] }));
    expect(ok).toHaveBeenCalledTimes(1);
    expect(no).toHaveBeenCalledTimes(1);
  });

  it("runs the whole patient flow and never renders a diagnosis or condition name", async () => {
    const started = { code: "ABCD2345", doctor_path: "/doctor/ABCD2345", expires_at: "2026-10-17T10:15:00+00:00", register: "demo" as const, register_note: "" };
    const base: VerifyStatus = { register: "demo", state: "waiting", hit_display: null, expires_at: started.expires_at, audit: [] };
    let cur: VerifyStatus = base;
    vi.spyOn(api, "verifyStart").mockResolvedValue(started);
    vi.spyOn(api, "verifyStatus").mockImplementation(async () => cur);
    const confirm = vi.spyOn(api, "verifyConfirm").mockImplementation(async () => (cur = { ...base, state: "confirmed", hit_display: HIT }));
    const end = vi.spyOn(api, "verifyEnd").mockResolvedValue({ ok: true, state: "ended" });
    const user = userEvent.setup();
    const { container } = render(<VerifyDoctor />);
    await user.click(screen.getByRole("button", { name: en["verify.start"] }));
    expect(await screen.findByText(en["verify.waiting"])).toBeInTheDocument();
    expect((screen.getByLabelText(en["verify.linkLabel"]) as HTMLInputElement).value).toBe(`${window.location.origin}/doctor/ABCD2345`);
    cur = { ...base, state: "claimed", hit_display: HIT };
    expect(await screen.findByTestId("verify-hit", {}, { timeout: 4000 })).toHaveTextContent(HIT);
    await user.click(screen.getByRole("button", { name: en["verify.confirm"] }));
    expect(confirm).toHaveBeenCalledWith("ABCD2345");
    expect(await screen.findByTestId("verify-confirmed")).toHaveTextContent(en["verify.opened"].replace("{name}", HIT));
    expect(container.textContent).not.toMatch(new RegExp(`${DIAGNOSIS}|fibromyalg|diagnos`, "i"));
    cur = { ...base, state: "ended", hit_display: HIT };
    await user.click(screen.getByRole("button", { name: en["verify.endNow"] }));
    expect(end).toHaveBeenCalledWith("ABCD2345");
    expect(await screen.findByTestId("verify-closed")).toBeInTheDocument();
  });
});

describe("verify copy", () => {
  it("has the same keys in English and Italian and follows the copy rules", () => {
    const keys = Object.keys(en).filter((k) => k.startsWith("verify.") || k.startsWith("doctor."));
    expect(keys.length).toBeGreaterThan(40);
    for (const k of keys) {
      for (const d of [en, itDict] as Record<string, string>[]) {
        expect(d[k], k).toBeTruthy();
        expect(d[k], k).not.toMatch(/[—!]/);
      }
    }
  });
});
