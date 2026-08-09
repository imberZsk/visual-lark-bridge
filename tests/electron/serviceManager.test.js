import { EventEmitter } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { spawn } from "node:child_process";
import {
  ServiceManager,
  expandHomePath,
  extractExistingBridgePid,
  isProcessRunning,
  signalProcessTree,
} from "../../electron/serviceManager.js";

vi.mock("node:child_process", async (importOriginal) => {
  /** originalModule 存储 Node 子进程模块的其余真实导出。 */
  const originalModule = await importOriginal();
  /** spawnMock 存储命名导出和默认命名空间共同使用的启动替身。 */
  const spawnMock = vi.fn();
  return {
    ...originalModule,
    default: { ...originalModule.default, spawn: spawnMock },
    spawn: spawnMock,
  };
});

afterEach(() => vi.restoreAllMocks());

describe("expandHomePath", () => {
  it("expands only a leading home marker", () => {
    expect(expandHomePath("~/bridge/config.json", "/Users/test")).toBe(
      "/Users/test/bridge/config.json",
    );
    expect(expandHomePath("/tmp/~/config.json", "/Users/test")).toBe(
      "/tmp/~/config.json",
    );
  });
});

describe("signalProcessTree", () => {
  it("signals the detached process group", () => {
    /** processKill 存储对 Node 进程组信号调用的监视器。 */
    const processKill = vi.spyOn(process, "kill").mockReturnValue(true);
    /** childKill 存储不应在正常路径调用的单进程回退方法。 */
    const childKill = vi.fn();

    expect(signalProcessTree({ pid: 321, kill: childKill }, "SIGTERM")).toBe(
      true,
    );
    expect(processKill).toHaveBeenCalledWith(-321, "SIGTERM");
    expect(childKill).not.toHaveBeenCalled();
  });

  it("falls back to the child when group signaling is unavailable", () => {
    vi.spyOn(process, "kill").mockImplementation(() => {
      throw new Error("process group unavailable");
    });
    /** childKill 存储进程组不可用时的单进程回退结果。 */
    const childKill = vi.fn().mockReturnValue(true);

    expect(signalProcessTree({ pid: 321, kill: childKill }, "SIGKILL")).toBe(
      true,
    );
    expect(childKill).toHaveBeenCalledWith("SIGKILL");
  });
});

describe("existing bridge process", () => {
  it("extracts the lock holder pid from the stable bridge error", () => {
    expect(
      extractExistingBridgePid(
        "桥接服务已在运行：同一运行目录已有桥接服务正在运行（pid=4321）",
      ),
    ).toBe(4321);
    expect(extractExistingBridgePid("桥接服务异常：未知错误")).toBeNull();
  });

  it("checks whether a validated pid is still running", () => {
    /** processKill 存储 PID 存活探测调用。 */
    const processKill = vi.spyOn(process, "kill").mockReturnValue(true);

    expect(isProcessRunning(4321)).toBe(true);
    expect(isProcessRunning(0)).toBe(false);
    expect(processKill).toHaveBeenCalledWith(4321, 0);
  });

  it("adopts the running lock holder instead of reporting a startup error", async () => {
    /** userDataPath 存储本用例隔离出的桌面运行数据目录。 */
    const userDataPath = await mkdtemp(
      path.join(tmpdir(), "visual-lark-service-manager-"),
    );
    /** child 存储模拟因单实例锁冲突而退出的新桥接子进程。 */
    const child = new EventEmitter();
    child.pid = 9876;
    child.stderr = new EventEmitter();
    child.kill = vi.fn();
    vi.mocked(spawn).mockReturnValue(child);
    /** manager 存储本用例验证状态接管行为的服务管理器。 */
    const manager = new ServiceManager({
      isPackaged: false,
      projectRoot: "/tmp/project",
      resourcesPath: "/tmp/resources",
      userDataPath,
      homePath: "/tmp/home",
    });
    /** config 存储启动命令所需的最小配置。 */
    const config = {
      workspacePath: "",
      profile: "test",
      larkConfigPath: "/tmp/lark.json",
      claudeTimeout: 180,
      provider: "claude",
      codexModel: "",
    };

    try {
      await manager.start(config, "/usr/bin");
      child.stderr.emit(
        "data",
        `桥接服务已在运行：同一运行目录已有桥接服务正在运行（pid=${process.pid}）`,
      );
      child.emit("exit", 73, null);

      expect(manager.status()).toEqual(
        expect.objectContaining({
          state: "running",
          pid: process.pid,
          lastError: "",
        }),
      );
    } finally {
      await rm(userDataPath, { recursive: true, force: true });
    }
  });
});
