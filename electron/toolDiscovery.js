import { access } from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

/** execFileAsync 存储无 shell 命令执行器。 */
const execFileAsync = promisify(execFile);
/** REQUIRED_TOOLS 存储桥接运行依赖的外部命令。 */
export const REQUIRED_TOOLS = Object.freeze(["claude", "codex", "lark-cli"]);

/** 读取登录 shell 的 PATH，保证桌面启动时也能找到用户命令。 */
export async function readLoginPath() {
  try {
    /** result 存储 zsh 输出的登录环境 PATH。 */
    const result = await execFileAsync("/bin/zsh", [
      "-lic",
      'printf %s "$PATH"',
    ]);
    return result.stdout.trim() || process.env.PATH || "";
  } catch {
    return process.env.PATH || "";
  }
}

/** 在指定 PATH 中寻找命令；commandName 必须来自固定工具白名单。 */
export async function findCommand(commandName, searchPath) {
  if (!REQUIRED_TOOLS.includes(commandName)) return null;
  /** directories 存储 PATH 中可搜索的目录列表。 */
  const directories = searchPath.split(path.delimiter).filter(Boolean);
  for (const directory of directories) {
    /** candidatePath 存储当前待检查的命令路径。 */
    const candidatePath = path.join(directory, commandName);
    try {
      await access(candidatePath);
      return candidatePath;
    } catch {
      // 当前目录不存在该命令时继续搜索后续 PATH 项。
    }
  }
  return null;
}

/** 探测桥接运行依赖，并返回可直接传给子进程的 PATH。 */
export async function discoverTools() {
  /** searchPath 存储登录 shell 解析得到的完整 PATH。 */
  const searchPath = await readLoginPath();
  /** entries 存储各依赖命令及其绝对路径。 */
  const entries = await Promise.all(
    REQUIRED_TOOLS.map(async (name) => [
      name,
      await findCommand(name, searchPath),
    ]),
  );
  return { path: searchPath, tools: Object.fromEntries(entries) };
}
