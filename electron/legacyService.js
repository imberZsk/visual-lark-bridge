import { access, rename } from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

/** execFileAsync 存储 launchctl 的无 shell 执行器。 */
const execFileAsync = promisify(execFile);
/** LEGACY_LABELS 存储历史安装脚本使用过的服务标识。 */
const LEGACY_LABELS = Object.freeze([
  "com.imber.lark-ai-bridge",
  "com.imber.lark-claude-bridge",
]);

/** LegacyService 负责探测和可恢复地停用历史 LaunchAgent。 */
export class LegacyService {
  /** 创建旧服务管理器；homePath 是当前用户目录。 */
  constructor(homePath) {
    /** this.homePath 存储当前用户目录。 */
    this.homePath = homePath;
  }

  /** 返回仍存在的历史 plist 列表。 */
  async inspect() {
    /** found 存储已发现的旧服务信息。 */
    const found = [];
    for (const label of LEGACY_LABELS) {
      /** plistPath 存储当前服务对应的 plist 路径。 */
      const plistPath = path.join(
        this.homePath,
        "Library",
        "LaunchAgents",
        `${label}.plist`,
      );
      try {
        await access(plistPath);
        found.push({ label, plistPath });
      } catch {
        // plist 不存在代表该历史服务未安装。
      }
    }
    return found;
  }

  /** 卸载并重命名历史 plist，保留 .disabled 文件供用户恢复。 */
  async disable() {
    /** services 存储当前可停用的历史服务。 */
    const services = await this.inspect();
    /** userDomain 存储当前用户 launchd 域。 */
    const userDomain = `gui/${process.getuid()}`;
    for (const service of services) {
      try {
        await execFileAsync("/bin/launchctl", [
          "bootout",
          userDomain,
          service.plistPath,
        ]);
      } catch {
        // 未加载的 plist 会让 bootout 失败，但仍应继续禁用配置文件。
      }
      await rename(service.plistPath, `${service.plistPath}.disabled`);
    }
    return services;
  }
}
