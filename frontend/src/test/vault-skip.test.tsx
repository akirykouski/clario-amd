import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../api";
import { Vault } from "../patient/Vault";

afterEach(() => vi.restoreAllMocks());

describe("Open the demo diary", () => {
  it("is shown only when the server offers it", () => {
    render(<Vault mode="unlock" onDone={() => {}} />);
    expect(screen.queryByRole("button", { name: "Open the demo diary" })).toBeNull();
  });

  it("opens the diary through the server, without a passphrase", async () => {
    const open = vi.spyOn(api, "demoOpen").mockResolvedValue({ ok: true });
    const unlock = vi.spyOn(api, "unlock");
    const done = vi.fn();
    render(<Vault mode="unlock" demoOpen onDone={done} />);
    fireEvent.click(screen.getByRole("button", { name: "Open the demo diary" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith({ tour: true }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(unlock).not.toHaveBeenCalled();
  });

  it("says why when the server refuses", async () => {
    vi.spyOn(api, "demoOpen").mockRejectedValue(new Error("This diary was created with another passphrase"));
    render(<Vault mode="setup" demoOpen onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Open the demo diary" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("another passphrase");
  });
});
