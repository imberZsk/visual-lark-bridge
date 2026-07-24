import { afterEach, describe, expect, it, vi } from "vitest";
import {
  expandHomePath,
  signalProcessTree,
} from "../../electron/serviceManager.js";

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
