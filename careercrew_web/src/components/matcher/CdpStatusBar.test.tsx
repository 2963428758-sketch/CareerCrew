// @vitest-environment jsdom
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { CdpStatusBar } from "./CdpStatusBar"

describe("CdpStatusBar", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("renders connected state when CDP port is alive", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        connected: true,
        cdp_url: "http://127.0.0.1:9222",
        boss_opened: true,
        liepin_opened: false,
        command: "powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1",
      }),
    }))

    render(<CdpStatusBar variant="card" />)

    await waitFor(() => {
      expect(screen.getByText("Chrome 实时采集器：已就绪")).toBeTruthy()
    })
    expect(screen.getByText("Boss直聘 ✓ 标签页已打开")).toBeTruthy()
    expect(screen.getByText("猎聘 待打开")).toBeTruthy()
  })

  it("renders disconnected state with launch and copy buttons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        connected: false,
        cdp_url: "http://127.0.0.1:9222",
        boss_opened: false,
        liepin_opened: false,
        command: "powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1",
      }),
    }))

    render(<CdpStatusBar variant="card" />)

    await waitFor(() => {
      expect(screen.getByText("Boss直聘与猎聘实时采集器：未启动")).toBeTruthy()
    })
    expect(screen.getByRole("button", { name: /一键启动 Chrome/i })).toBeTruthy()
    expect(screen.getByRole("button", { name: /复制命令/i })).toBeTruthy()
  })

  it("handles copy command to clipboard", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: { writeText: writeTextMock },
    })

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        connected: false,
        cdp_url: "http://127.0.0.1:9222",
        boss_opened: false,
        liepin_opened: false,
        command: "powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1",
      }),
    }))

    const toastMock = vi.fn()
    render(<CdpStatusBar variant="banner" onToast={toastMock} />)

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /复制命令/i })).toBeTruthy()
    })

    fireEvent.click(screen.getByRole("button", { name: /复制命令/i }))
    expect(writeTextMock).toHaveBeenCalledWith("powershell -ExecutionPolicy Bypass -File scripts/start_chrome_cdp.ps1")
  })
})
