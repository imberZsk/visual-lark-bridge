import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ServiceOverview } from "../../src/components/ServiceOverview";
import type { BridgeSnapshot } from "../../src/types/bridge";

describe("ServiceOverview", () => {
  it("shows running process and disables start action", () => {
    /** snapshot 存储运行状态下的完整测试快照。 */
    const snapshot: BridgeSnapshot = {
      config: {
        profile: "visual-lark-bridge",
        larkConfigPath: "~/.lark-cli/config.json",
        workspacePath: "",
        claudeTimeout: 180,
        autoStartBridge: true,
      },
      service: {
        state: "running",
        pid: 4321,
        startedAt: "2026-07-23T00:00:00.000Z",
        lastError: "",
      },
      tools: { claude: "/bin/claude", "lark-cli": "/bin/lark-cli" },
      legacyServices: [],
      autoStart: true,
      userDataPath: "/tmp/visual-lark-bridge",
      version: "0.1.0",
    };
    render(
      <ServiceOverview
        snapshot={snapshot}
        busy={false}
        onStart={vi.fn()}
        onStop={vi.fn()}
        onRestart={vi.fn()}
      />,
    );
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动/ })).toBeDisabled();
    expect(screen.getByText("4321")).toBeInTheDocument();
  });
});
