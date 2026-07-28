import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

/** DEFAULT_NEWS_SOURCES 存储首次配置新闻推送时展示的默认 RSS 来源。 */
const DEFAULT_NEWS_SOURCES = Object.freeze([
  { name: "Hacker News", url: "https://hnrss.org/frontpage" },
  { name: "arXiv cs.AI", url: "https://export.arxiv.org/rss/cs.AI" },
  { name: "OpenAI", url: "https://openai.com/news/rss.xml" },
  {
    name: "Google AI",
    url: "https://blog.google/innovation-and-ai/technology/ai/rss/",
  },
]);
/** NEWS_TIME_PATTERN 存储每日推送时刻允许的 24 小时格式。 */
const NEWS_TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
/** NEWS_MAX_ITEMS_LIMIT 存储单次推送条数的配置上限。 */
const NEWS_MAX_ITEMS_LIMIT = 20;

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
  news: {
    enabled: false,
    chat_id: "",
    times: ["09:07"],
    sources: DEFAULT_NEWS_SOURCES,
    max_items: 8,
  },
});

/** ConfigStore 负责校验并原子持久化桌面端配置。 */
export class ConfigStore {
  /** 创建配置存储；userDataPath 是 Electron 用户数据目录。 */
  constructor(userDataPath) {
    /** this.userDataPath 存储应用用户数据目录。 */
    this.userDataPath = userDataPath;
    /** this.configPath 存储配置 JSON 的完整路径。 */
    this.configPath = path.join(userDataPath, "config.json");
    /** this.writeQueue 串行化所有配置修改，避免启动阶段多个 IPC 争用同一配置文件。 */
    this.writeQueue = Promise.resolve();
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
    return this.enqueueWrite(() => this.writeFile(input));
  }

  /** 更新单个配置字段并保留其他持久化配置；patch 是渲染层提交的局部配置。 */
  async update(patch) {
    return this.enqueueWrite(async () => {
      /** currentConfig 存储同一写入队列内读取的最新配置。 */
      const currentConfig = await this.read();
      return this.writeFile({ ...currentConfig, ...patch });
    });
  }

  /** 将配置修改加入串行队列；operation 是本次独占执行的异步写入。 */
  enqueueWrite(operation) {
    /** queuedWrite 存储本次排队后的写入 Promise。 */
    const queuedWrite = this.writeQueue.then(operation, operation);
    this.writeQueue = queuedWrite.then(
      () => undefined,
      () => undefined,
    );
    return queuedWrite;
  }

  /** 原子写入配置文件；input 是已进入独占写入区间的未知配置对象。 */
  async writeFile(input) {
    /** config 存储经过类型和范围校验的配置。 */
    const config = this.validate(input);
    /** temporaryPath 存储本次写入独享的临时文件路径。 */
    const temporaryPath = `${this.configPath}.${process.pid}.${Date.now()}.tmp`;
    await mkdir(this.userDataPath, { recursive: true });
    await writeFile(
      temporaryPath,
      `${JSON.stringify(config, null, 2)}\n`,
      "utf8",
    );
    await rename(temporaryPath, this.configPath);
    return config;
  }

  /** 将未知输入收敛为受支持的配置字段。 */
  validate(input) {
    /** source 存储可安全读取的输入对象。 */
    const source = input && typeof input === "object" ? input : {};
    /** timeoutValue 存储用户提交的超时秒数。 */
    const timeoutValue = Number(source.claudeTimeout);
    /** newsSource 存储可安全读取的新闻配置对象。 */
    const newsSource =
      source.news && typeof source.news === "object" ? source.news : {};
    /** newsTimes 存储去重后的有效每日推送时刻。 */
    const newsTimes = Array.isArray(newsSource.times)
      ? [
          ...new Set(
            newsSource.times
              .filter((value) => typeof value === "string")
              .map((value) => value.trim())
              .filter((value) => NEWS_TIME_PATTERN.test(value)),
          ),
        ].sort()
      : DEFAULT_CONFIG.news.times;
    /** newsSources 存储名称和 HTTP(S) URL 均有效的信息源。 */
    const newsSources = Array.isArray(newsSource.sources)
      ? newsSource.sources
          .filter(
            (item) =>
              item &&
              typeof item === "object" &&
              typeof item.url === "string" &&
              /^https?:\/\/[^\s]+$/i.test(item.url.trim()),
          )
          .map((item, index) => ({
            name:
              typeof item.name === "string" && item.name.trim()
                ? item.name.trim()
                : `信息源 ${index + 1}`,
            url: item.url.trim(),
          }))
      : DEFAULT_CONFIG.news.sources.map((item) => ({ ...item }));
    /** newsMaxItems 存储收敛到允许区间内的新闻条数。 */
    const newsMaxItemsValue = Number(newsSource.max_items);
    const newsMaxItems = Number.isInteger(newsMaxItemsValue)
      ? Math.min(Math.max(newsMaxItemsValue, 1), NEWS_MAX_ITEMS_LIMIT)
      : DEFAULT_CONFIG.news.max_items;
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
      news: {
        enabled: newsSource.enabled === true,
        chat_id:
          typeof newsSource.chat_id === "string" &&
          newsSource.chat_id.trim().startsWith("oc_")
            ? newsSource.chat_id.trim()
            : "",
        times: newsTimes,
        sources: newsSources,
        max_items: newsMaxItems,
      },
    };
  }
}
