import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** currentDirectory 存储当前脚本目录。 */
const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
/** projectRoot 存储项目根目录。 */
const projectRoot = path.resolve(currentDirectory, "..");
/** electronPath 存储本项目 Electron 可执行文件路径。 */
const electronPath = path.join(projectRoot, "node_modules", ".bin", "electron");
/** child 存储正在冒烟验证的 Electron 进程。 */
const child = spawn(electronPath, ["."], {
  cwd: projectRoot,
  env: { ...process.env, NODE_ENV: "production", LARK_BRIDGE_SMOKE: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});
/** output 存储进程输出，用于识别成功标记。 */
let output = "";
for (const stream of [child.stdout, child.stderr])
  stream.on("data", (chunk) => {
    output += String(chunk);
    process.stdout.write(chunk);
  });
/** timeout 存储冒烟测试的超时保护。 */
const timeout = setTimeout(() => {
  child.kill("SIGKILL");
  process.exit(2);
}, 30000);
child.on("exit", (code) => {
  clearTimeout(timeout);
  if (output.includes("SMOKE_OK")) process.exit(0);
  console.error(`Electron 启动检查失败（exit=${code}）`);
  process.exit(code || 1);
});
