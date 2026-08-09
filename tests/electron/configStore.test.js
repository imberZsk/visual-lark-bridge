import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ConfigStore, DEFAULT_CONFIG } from "../../electron/configStore.js";

describe("ConfigStore", () => {
  it("returns defaults when config does not exist", async () => {
    /** temporaryDirectory 存储本测试隔离的配置目录。 */
    const temporaryDirectory = await mkdtemp(
      path.join(os.tmpdir(), "lark-bridge-config-"),
    );
    /** store 存储待测试的配置仓库。 */
    const store = new ConfigStore(temporaryDirectory);
    expect(await store.read()).toEqual(DEFAULT_CONFIG);
  });

  it("validates and persists supported fields only", async () => {
    /** temporaryDirectory 存储本测试隔离的配置目录。 */
    const temporaryDirectory = await mkdtemp(
      path.join(os.tmpdir(), "lark-bridge-config-"),
    );
    /** store 存储待测试的配置仓库。 */
    const store = new ConfigStore(temporaryDirectory);
    /** saved 存储校验后的配置。 */
    const saved = await store.write({
      profile: "team-bot",
      larkConfigPath: "~/.lark-cli/config.json",
      workspacePath: "",
      claudeTimeout: 300,
      autoStartBridge: false,
      secret: "ignored",
    });
    /** persisted 存储磁盘中的配置对象。 */
    const persisted = JSON.parse(await readFile(store.configPath, "utf8"));
    expect(saved).toEqual(persisted);
    expect(persisted.secret).toBeUndefined();
  });

  it("serializes concurrent partial updates without losing fields", async () => {
    /** temporaryDirectory 存储本测试隔离的配置目录。 */
    const temporaryDirectory = await mkdtemp(
      path.join(os.tmpdir(), "lark-bridge-config-"),
    );
    /** store 存储待测试的配置仓库。 */
    const store = new ConfigStore(temporaryDirectory);
    await Promise.all([
      store.update({ theme: "light" }),
      store.update({ profile: "concurrent-bot" }),
    ]);
    /** persisted 存储并发更新全部完成后的磁盘配置。 */
    const persisted = await store.read();
    expect(persisted.theme).toBe("light");
    expect(persisted.profile).toBe("concurrent-bot");
  });

  it("validates news scheduling fields and removes invalid sources", async () => {
    /** temporaryDirectory 存储新闻配置测试的隔离目录。 */
    const temporaryDirectory = await mkdtemp(
      path.join(os.tmpdir(), "lark-bridge-config-"),
    );
    /** store 存储待测试的配置仓库。 */
    const store = new ConfigStore(temporaryDirectory);
    /** saved 存储经过新闻字段校验的配置。 */
    const saved = await store.write({
      news: {
        enabled: true,
        delivery_type: "webhook",
        chat_id: "invalid",
        webhook_url:
          "https://open.feishu.cn/open-apis/bot/v2/hook/test-webhook-id",
        times: ["09:07", "25:00", "09:07"],
        sources: [
          { name: "Valid", url: "https://example.com/rss" },
          { name: "Invalid", url: "file:///tmp/rss" },
        ],
        max_items: 99,
      },
    });
    expect(saved.news).toEqual({
      enabled: true,
      delivery_type: "webhook",
      chat_id: "",
      webhook_url:
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-webhook-id",
      times: ["09:07"],
      sources: [{ name: "Valid", url: "https://example.com/rss" }],
      max_items: 20,
    });
  });
});
