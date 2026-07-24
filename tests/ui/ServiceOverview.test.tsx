import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ServiceOverview } from "../../src/components/ServiceOverview";
import type { BridgeSnapshot } from "../../src/types/bridge";

afterEach(() => cleanup());

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
        onDeleteTask={vi.fn()}
      />,
    );
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /启动/ })).toBeDisabled();
    expect(screen.getByText("4321")).toBeInTheDocument();
  });

  it("keeps task rows in a drawer instead of growing the service page", () => {
    /** snapshot 存储包含两个任务的停止状态快照。 */
    const snapshot: BridgeSnapshot = {
      config: {
        profile: "visual-lark-bridge",
        provider: "claude",
        codexModel: "",
        larkConfigPath: "~/.lark-cli/config.json",
        workspacePath: "",
        claudeTimeout: 180,
        autoStartBridge: true,
        theme: "dark",
      },
      service: {
        state: "stopped",
        pid: null,
        startedAt: null,
        lastError: "",
      },
      tools: { claude: "/bin/claude", "lark-cli": "/bin/lark-cli" },
      legacyServices: [],
      autoStart: true,
      userDataPath: "/tmp/visual-lark-bridge",
      version: "0.1.0",
      tasks: [
        {
          task_id: "t1",
          title: "登录超时排查",
          status: "空闲",
          turns: 2,
          last_question: "继续检查接口日志",
        },
        {
          task_id: "t2",
          title: "成都天气",
          status: "空闲",
          turns: 1,
          last_question: "今天成都天气如何",
        },
      ],
    };
    render(
      <ServiceOverview
        snapshot={snapshot}
        busy={false}
        onStart={vi.fn()}
        onStop={vi.fn()}
        onRestart={vi.fn()}
        onDeleteTask={vi.fn()}
      />,
    );

    expect(screen.queryByText("登录超时排查")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /管理任务/ }));
    expect(screen.getByText("登录超时排查")).toBeInTheDocument();
    expect(screen.getByText("成都天气")).toBeInTheDocument();
  });
});
