import { expect } from "@playwright/test";
import { e2eTest, readCalls } from "./helpers/electronApp";

/** STRUCTURED_LOG_SAMPLE 存储覆盖默认分页和 JSON 解析的日志样本。 */
const STRUCTURED_LOG_SAMPLE = [
  "[2026-07-28T08:00:00] oldest entry",
  ...Array.from(
    { length: 104 },
    (_, index) =>
      `[2026-07-28T08:${String(index).padStart(2, "0")}] entry ${index}`,
  ),
  '[2026-07-28T10:00:00] 收到卡片动作：{"event_id":"evt_json","task_id":"t1","chat_id":"oc_test"}',
].join("\n");

e2eTest("设置页回显默认配置", {}, async (page) => {
  await page.getByText("设置", { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "飞书 Profile" })).toHaveValue(
    "visual-lark-bridge",
  );
  await expect(
    page.getByRole("spinbutton", { name: "响应超时（秒）" }),
  ).toHaveValue("180");
});

e2eTest("切换 Codex 提供方并保存模型", {}, async (page) => {
  await page.getByText("设置", { exact: true }).click();
  await page.getByRole("combobox", { name: "AI 提供方" }).click();
  await page.getByText("Codex CLI", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "Codex 模型（可选）" })
    .fill("gpt-5.4");
  await page.getByRole("button", { name: /保存设置/ }).click();
  await expect(page.getByText("设置已保存")).toBeVisible();
  const saveCall = (await readCalls(page)).find(
    (call) => call.name === "saveConfig",
  );
  expect(saveCall?.value).toMatchObject({
    provider: "codex",
    codexModel: "gpt-5.4",
  });
});

e2eTest("超时字段遵守范围并保存持久化", {}, async (page) => {
  await page.getByText("设置", { exact: true }).click();
  const timeout = page.getByRole("spinbutton", { name: "响应超时（秒）" });
  await timeout.fill("20");
  await page.getByRole("button", { name: /保存设置/ }).click();
  await expect(timeout).toHaveValue("30");
  await timeout.fill("600");
  await page.getByRole("button", { name: /保存设置/ }).click();
  const saveCall = (await readCalls(page))
    .filter((call) => call.name === "saveConfig")
    .at(-1);
  expect(saveCall?.value).toMatchObject({ claudeTimeout: 600 });
});

e2eTest("配置 AI 新闻定时推送并保存", {}, async (page) => {
  await page.getByText("设置", { exact: true }).click();
  await expect(page.locator(".ant-picker")).toBeVisible();
  await page.locator(".news-enabled-toggle").getByRole("switch").click();
  await page
    .getByRole("textbox", { name: "目标会话 Chat ID" })
    .fill("oc_news_target");
  await page.getByRole("spinbutton", { name: "单次新闻条数" }).fill("12");
  await page
    .getByPlaceholder("https://example.com/rss.xml")
    .fill("https://example.com/ai.xml");
  await page.getByRole("button", { name: /保存设置/ }).click();
  await expect(page.getByText("设置已保存")).toBeVisible();
  const saveCall = (await readCalls(page))
    .filter((call) => call.name === "saveConfig")
    .at(-1);
  expect(saveCall?.value).toMatchObject({
    news: {
      enabled: true,
      chat_id: "oc_news_target",
      times: ["09:07"],
      sources: [{ name: "Hacker News", url: "https://example.com/ai.xml" }],
      max_items: 12,
    },
  });
});

e2eTest("无日志时展示空状态且禁用清空", {}, async (page) => {
  await page.getByText("日志", { exact: true }).click();
  await expect(page.getByText("暂无日志", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /清空/ })).toBeDisabled();
});

e2eTest(
  "有日志时支持刷新取消和确认清空",
  { logs: "bridge started\nmessage received" },
  async (page) => {
    await page.getByText("日志", { exact: true }).click();
    await expect(page.getByText("bridge started")).toBeVisible();
    await page.getByRole("button", { name: /刷新/ }).click();
    await page.getByRole("button", { name: /清空/ }).click();
    await page.getByRole("button", { name: /取\s*消/ }).click();
    await expect(page.getByText("bridge started")).toBeVisible();
    await page.getByRole("button", { name: /清空/ }).click();
    await page
      .getByRole("button", { name: /清\s*空/ })
      .last()
      .click();
    await expect(page.getByText("暂无日志", { exact: true })).toBeVisible();
  },
);

e2eTest(
  "日志支持查询分页解析和复制 JSON",
  {
    logs: STRUCTURED_LOG_SAMPLE,
    snapshot: {
      tasks: [
        {
          task_id: "t1",
          title: "新闻分析",
          status: "idle",
          turns: 1,
          last_question: "整理新闻",
          updated_at: "2026-07-28T10:00:00",
        },
      ],
    },
  },
  async (page) => {
    await page.getByText("日志", { exact: true }).click();
    await expect(page.getByText("显示最近 100 条，共 106 条")).toBeVisible();
    await expect(page.getByText("oldest entry")).not.toBeVisible();
    await page.getByRole("tab", { name: "t1 · 新闻分析" }).click();
    await expect(page.getByText("显示最近 1 条，共 1 条")).toBeVisible();
    await page.getByPlaceholder("查询日志内容或 JSON 字段").fill("evt_json");
    await expect(page.getByText("找到 1 条日志")).toBeVisible();
    await page.getByRole("button", { name: "解析 JSON" }).click();
    await expect(page.getByText('"event_id": "evt_json"')).toBeVisible();
    await page.getByRole("button", { name: "复制 JSON" }).click();
    await expect(page.getByText("JSON 已复制")).toBeVisible();
    await page.getByPlaceholder("查询日志内容或 JSON 字段").clear();
    await page.getByRole("tab", { name: "系统" }).click();
    await expect(page.getByText("显示最近 100 条，共 105 条")).toBeVisible();
    await page.getByRole("button", { name: /显示更早日志/ }).click();
    await expect(page.getByText("oldest entry")).toBeVisible();
  },
);
