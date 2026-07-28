import { expect } from "@playwright/test";
import { e2eTest, readCalls } from "./helpers/electronApp";

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
      sources: [
        { name: "Hacker News", url: "https://example.com/ai.xml" },
      ],
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
