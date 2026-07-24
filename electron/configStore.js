import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

/** DEFAULT_CONFIG 存储首次启动时使用的非敏感桥接配置。 */
export const DEFAULT_CONFIG = Object.freeze({
  profile: "visual-lark-bridge",
  provider: "claude",
  codexModel: "",
  larkConfigPath: "~/.lark-cli/config.json",
  workspacePath: "",
  claudeTimeout: 180,
  autoStartBridge: true,
  theme: "dark",
});

/** ConfigStore 负责校验并原子持久化桌面端配置。 */
export class ConfigStore {
  /** 创建配置存储；userDataPath 是 Electron 用户数据目录。 */
  constructor(userDataPath) {
    /** this.userDataPath 存储应用用户数据目录。 */
    this.userDataPath = userDataPath;
    /** this.configPath 存储配置 JSON 的完整路径。 */
    this.configPath = path.join(userDataPath, "config.json");
  }

  /** 读取配置，文件缺失或损坏时返回安全默认值。 */
  async read() {
    try {
      /** parsedConfig 存储磁盘 JSON 解析结果。 */
      const parsedConfig = JSON.parse(await readFile(this.configPath, "utf8"));
      return this.validate(parsedConfig);
    } catch {
      return { ...DEFAULT_CONFIG };
    }
  }

  /** 校验并写入配置；input 是渲染层提交的未知对象。 */
  async write(input) {
    /** config 存储经过类型和范围校验的配置。 */
    const config = this.validate(input);
    /** temporaryPath 存储原子替换前的临时文件路径。 */
    const temporaryPath = `${this.configPath}.tmp`;
    await mkdir(this.userDataPath, { recursive: true });
    await writeFile(
      temporaryPath,
      `${JSON.stringify(config, null, 2)}\n`,
      "utf8",
    );
    await rename(temporaryPath, this.configPath);
    return config;
  }

  /** 更新单个配置字段并保留其他持久化配置；patch 是渲染层提交的局部配置。 */
  async update(patch) {
    /** currentConfig 存储更新前的完整配置。 */
    const currentConfig = await this.read();
    return this.write({ ...currentConfig, ...patch });
  }

  /** 将未知输入收敛为受支持的配置字段。 */
  validate(input) {
    /** source 存储可安全读取的输入对象。 */
    const source = input && typeof input === "object" ? input : {};
    /** timeoutValue 存储用户提交的超时秒数。 */
    const timeoutValue = Number(source.claudeTimeout);
    return {
      profile:
        typeof source.profile === "string" && source.profile.trim()
          ? source.profile.trim()
          : DEFAULT_CONFIG.profile,
      provider: source.provider === "codex" ? "codex" : "claude",
      codexModel:
        typeof source.codexModel === "string" ? source.codexModel.trim() : "",
      larkConfigPath:
        typeof source.larkConfigPath === "string" &&
        source.larkConfigPath.trim()
          ? source.larkConfigPath.trim()
          : DEFAULT_CONFIG.larkConfigPath,
      workspacePath:
        typeof source.workspacePath === "string"
          ? source.workspacePath.trim()
          : "",
      claudeTimeout:
        Number.isInteger(timeoutValue) &&
        timeoutValue >= 30 &&
        timeoutValue <= 1800
          ? timeoutValue
          : DEFAULT_CONFIG.claudeTimeout,
      autoStartBridge: source.autoStartBridge !== false,
      theme: source.theme === "light" ? "light" : "dark",
    };
  }
}
