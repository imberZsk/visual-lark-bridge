import { expect } from "@playwright/test";
import { e2eTest, readCalls } from "./helpers/electronApp";

e2eTest("首屏展示品牌、服务页和停止状态", {}, async (page) => {
  await expect(
    page.getByText("Visual Lark Bridge", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "服务控制" })).toBeVisible();
  await expect(page.getByText("桥接未运行")).toBeVisible();
});

e2eTest("服务设置日志三页可往返导航", {}, async (page) => {
  await page.getByText("设置", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "连接设置" })).toBeVisible();
  await page.getByText("日志", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "运行日志" })).toBeVisible();
  await page.getByText("服务", { exact: true }).click();
  await expect(page.getByRole("heading", { name: "服务控制" })).toBeVisible();
});

e2eTest("可切换到浅色主题", {}, async (page) => {
  await page.locator(".ant-segmented-item").first().click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(
    (await readCalls(page)).some(
      (call) => call.name === "setTheme" && call.value === "light",
    ),
  ).toBe(true);
});

e2eTest(
  "可切换回深色主题",
  { snapshot: { config: { theme: "light" } } },
  async (page) => {
    await page.locator(".ant-segmented-item").last().click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  },
);

e2eTest(
  "刷新渲染页后保留主题",
  { snapshot: { config: { theme: "light" } } },
  async (page) => {
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  },
);

e2eTest("停止状态仅启用启动按钮", {}, async (page) => {
  await expect(page.getByRole("button", { name: /启动$/ })).toBeEnabled();
  await expect(page.getByRole("button", { name: /停止$/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: /重启$/ })).toBeDisabled();
});

e2eTest(
  "运行状态仅启用停止和重启",
  {
    snapshot: {
      service: {
        state: "running",
        pid: 123,
        startedAt: "2026-07-25T01:00:00Z",
      },
    },
  },
  async (page) => {
    await expect(page.getByRole("button", { name: /启动$/ })).toBeDisabled();
    await expect(page.getByRole("button", { name: /停止$/ })).toBeEnabled();
    await expect(page.getByRole("button", { name: /重启$/ })).toBeEnabled();
  },
);

e2eTest("启动成功后状态与 PID 同步更新", {}, async (page) => {
  await page.getByRole("button", { name: /启动$/ }).click();
  await expect(page.getByText("运行中", { exact: true })).toBeVisible();
  await expect(page.getByText("43210", { exact: true })).toBeVisible();
  await expect(page.getByText("桥接运行中")).toBeVisible();
});

e2eTest(
  "停止成功后状态与 PID 同步更新",
  {
    snapshot: {
      service: {
        state: "running",
        pid: 123,
        startedAt: "2026-07-25T01:00:00Z",
      },
    },
  },
  async (page) => {
    await page.getByRole("button", { name: /停止$/ }).click();
    await expect(page.getByText("已停止", { exact: true })).toBeVisible();
    await expect(page.getByText("桥接未运行")).toBeVisible();
  },
);

e2eTest(
  "服务异常时展示错误摘要",
  { snapshot: { service: { state: "error", lastError: "模拟桥接启动失败" } } },
  async (page) => {
    await expect(page.getByText("异常", { exact: true })).toBeVisible();
    await expect(page.getByText("模拟桥接启动失败")).toBeVisible();
    await expect(page.getByText("桥接异常")).toBeVisible();
  },
);
