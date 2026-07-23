import { spawn } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { EventEmitter } from "node:events";

/** STOP_TIMEOUT_MS 存储等待桥接进程正常退出的最长毫秒数。 */
const STOP_TIMEOUT_MS = 5000;
/** LOG_TAIL_LIMIT 存储控制台单次读取的最大日志字符数。 */
const LOG_TAIL_LIMIT = 50000;

/** expandHomePath 展开配置路径开头的波浪号；value 是用户配置路径。 */
export function expandHomePath(value, homePath) {
  if (!value) return value;
  if (value === "~") return homePath;
  return value.startsWith("~/") ? path.join(homePath, value.slice(2)) : value;
}

/** ServiceManager 管理当前桌面应用拥有的 Python 桥接子进程。 */
export class ServiceManager extends EventEmitter {
  /** 创建服务管理器；options 提供运行路径和打包状态。 */
  constructor(options) {
    super();
    /** this.options 存储不可变运行路径配置。 */
    this.options = options;
    /** this.child 存储当前桥接子进程。 */
    this.child = null;
    /** this.startedAt 存储当前进程启动时间。 */
    this.startedAt = null;
    /** this.lastError 存储最近一次启动或退出错误。 */
    this.lastError = "";
  }

  /** 返回当前服务状态快照。 */
  status() {
    return {
      state: this.child ? "running" : this.lastError ? "error" : "stopped",
      pid: this.child?.pid ?? null,
      startedAt: this.startedAt,
      lastError: this.lastError,
    };
  }

  /** 解析开发和打包环境各自的桥接启动命令。 */
  resolveCommand() {
    if (this.options.isPackaged) {
      return {
        command: path.join(
          this.options.resourcesPath,
          "sidecars",
          "lark-ai-bridge",
        ),
        prefixArgs: [],
        gatewayPath: path.join(
          this.options.resourcesPath,
          "sidecars",
          "lark-event-gateway",
        ),
      };
    }
    return {
      command: path.join(this.options.projectRoot, ".venv", "bin", "python"),
      prefixArgs: [path.join(this.options.projectRoot, "lark_ai_bridge.py")],
      gatewayPath: path.join(
        this.options.projectRoot,
        "lark_bridge",
        "event_gateway.py",
      ),
    };
  }

  /** 启动桥接服务；config 是已校验配置，runtimePath 是外部工具 PATH。 */
  async start(config, runtimePath) {
    if (this.child) return this.status();
    /** runtimePaths 存储本次启动需要的可写目录。 */
    const runtimePaths = {
      logs: path.join(this.options.userDataPath, "logs"),
      workspace: config.workspacePath
        ? expandHomePath(config.workspacePath, this.options.homePath)
        : path.join(this.options.userDataPath, "workspace"),
    };
    await Promise.all(
      Object.values(runtimePaths).map((directory) =>
        mkdir(directory, { recursive: true }),
      ),
    );
    /** launchTarget 存储当前环境的程序、前置参数和网关路径。 */
    const launchTarget = this.resolveCommand();
    /** args 存储桥接进程的完整命令参数。 */
    const args = [
      ...launchTarget.prefixArgs,
      "--workspace",
      runtimePaths.workspace,
      "--log-dir",
      runtimePaths.logs,
      "--lark-profile",
      config.profile,
      "--lark-config",
      expandHomePath(config.larkConfigPath, this.options.homePath),
      "--event-gateway",
      launchTarget.gatewayPath,
      "--claude-timeout",
      String(config.claudeTimeout),
    ];
    this.lastError = "";
    /** child 存储新启动的桥接进程。 */
    const child = spawn(launchTarget.command, args, {
      cwd: runtimePaths.workspace,
      env: { ...process.env, PATH: runtimePath },
      stdio: ["ignore", "ignore", "pipe"],
    });
    this.child = child;
    this.startedAt = new Date().toISOString();
    child.stderr.on("data", (chunk) => {
      this.lastError = String(chunk).trim().slice(-1000);
      this.emit("changed", this.status());
    });
    child.once("error", (error) => {
      this.lastError = error.message;
    });
    child.once("exit", (code, signal) => {
      this.child = null;
      this.startedAt = null;
      if (code && code !== 0)
        this.lastError = `桥接进程退出（code=${code}, signal=${signal ?? "none"}）`;
      this.emit("changed", this.status());
    });
    this.emit("changed", this.status());
    return this.status();
  }

  /** 停止当前桥接服务并等待进程回收。 */
  async stop() {
    /** child 存储停止操作开始时的进程引用。 */
    const child = this.child;
    if (!child) return this.status();
    /** exitPromise 存储进程退出或超时强制结束的等待逻辑。 */
    const exitPromise = new Promise((resolve) => {
      /** timeout 存储正常退出等待计时器。 */
      const timeout = setTimeout(() => child.kill("SIGKILL"), STOP_TIMEOUT_MS);
      child.once("exit", () => {
        clearTimeout(timeout);
        resolve();
      });
    });
    child.kill("SIGTERM");
    await exitPromise;
    return this.status();
  }

  /** 使用新配置重启桥接服务。 */
  async restart(config, runtimePath) {
    await this.stop();
    return this.start(config, runtimePath);
  }

  /** 读取桥接主日志尾部，日志不存在时返回空字符串。 */
  async readLogs() {
    try {
      /** content 存储桥接日志完整文本。 */
      const content = await readFile(
        path.join(this.options.userDataPath, "logs", "bridge.log"),
        "utf8",
      );
      return content.slice(-LOG_TAIL_LIMIT);
    } catch {
      return "";
    }
  }
}
