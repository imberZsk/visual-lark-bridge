import { expect } from "@playwright/test";
import { e2eTest, readCalls } from "./helpers/electronApp";

/** TASKS 存储任务抽屉交互使用的两条隔离任务数据。 */
const TASKS = [
  {
    task_id: "t1",
    title: "旧任务",
    status: "已完成",
    turns: 2,
    last_question: "旧问题",
    updated_at: "2026-07-24",
  },
  {
    task_id: "t2",
    title: "新任务",
    status: "进行中",
    turns: 3,
    last_question: "新问题",
    updated_at: "2026-07-25",
  },
];

e2eTest("无任务时任务抽屉展示空状态", {}, async (page) => {
  await page.getByRole("button", { name: /管理任务/ }).click();
  await expect(page.getByText("暂无任务", { exact: true })).toBeVisible();
});

e2eTest(
  "有任务时展示最近任务和倒序任务列表",
  { snapshot: { tasks: TASKS } },
  async (page) => {
    await expect(page.getByText("最近任务：新任务")).toBeVisible();
    await page.getByRole("button", { name: /管理任务/ }).click();
    const titles = await page
      .locator(".task-drawer-title strong")
      .allTextContents();
    expect(titles).toEqual(["新任务", "旧任务"]);
    await expect(page.getByText("3 轮")).toBeVisible();
  },
);

e2eTest(
  "服务运行时禁止删除任务",
  { snapshot: { tasks: TASKS, service: { state: "running", pid: 123 } } },
  async (page) => {
    await page.getByRole("button", { name: /管理任务/ }).click();
    await expect(
      page.getByRole("button", { name: "删除任务 新任务" }),
    ).toBeDisabled();
  },
);

e2eTest(
  "停止服务后确认删除任务并刷新列表",
  { snapshot: { tasks: TASKS } },
  async (page) => {
    await page.getByRole("button", { name: /管理任务/ }).click();
    await page.getByRole("button", { name: "删除任务 新任务" }).click();
    await page
      .getByRole("button", { name: /删\s*除/ })
      .last()
      .click();
    await expect(page.getByText("新任务", { exact: true })).toHaveCount(0);
    expect(
      (await readCalls(page)).some(
        (call) => call.name === "deleteTask" && call.value === "t2",
      ),
    ).toBe(true);
  },
);

e2eTest(
  "缺失命令时展示完整诊断警告",
  { snapshot: { tools: { claude: null, codex: null, "lark-cli": null } } },
  async (page) => {
    await expect(
      page.getByText("缺少命令：claude、codex、lark-cli"),
    ).toBeVisible();
    await expect(page.getByText("未找到", { exact: true })).toHaveCount(3);
  },
);

e2eTest("已安装命令展示成功状态和路径", {}, async (page) => {
  await expect(page.getByText("/bin/claude", { exact: true })).toBeVisible();
  await expect(page.getByText("/bin/lark-cli", { exact: true })).toBeVisible();
});

e2eTest(
  "检测到旧服务后可停用并移除提示",
  {
    snapshot: {
      legacyServices: [{ label: "legacy", plistPath: "/tmp/legacy.plist" }],
    },
  },
  async (page) => {
    await expect(page.getByText("检测到 1 个旧后台服务")).toBeVisible();
    await page.getByRole("button", { name: /停用旧服务/ }).click();
    await expect(page.getByText("检测到 1 个旧后台服务")).toHaveCount(0);
  },
);

e2eTest("登录启动开关可更新并同步快照", {}, async (page) => {
  await page.getByRole("switch").click();
  await expect(page.getByRole("switch")).toBeChecked();
  expect(
    (await readCalls(page)).some(
      (call) => call.name === "setAutoStart" && call.value === true,
    ),
  ).toBe(true);
});

e2eTest(
  "清理运行数据支持取消和确认",
  { snapshot: { tasks: TASKS } },
  async (page) => {
    await page.getByRole("button", { name: /清理数据/ }).click();
    await page.getByRole("button", { name: /取\s*消/ }).click();
    expect(
      (await readCalls(page)).some((call) => call.name === "clearRuntime"),
    ).toBe(false);
    await page.getByRole("button", { name: /清理数据/ }).click();
    await page
      .getByRole("button", { name: /清\s*理/ })
      .last()
      .click();
    expect(
      (await readCalls(page)).some((call) => call.name === "clearRuntime"),
    ).toBe(true);
  },
);
