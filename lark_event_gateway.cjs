#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const crypto = require("node:crypto");
const childProcess = require("node:child_process");
const path = require("node:path");
const Lark = require("@larksuiteoapi/node-sdk");

/** 读取命令行参数；name 是形如 --config 的参数名。 */
function readArgument(name) {
  // argumentIndex 存储目标参数名在 argv 中的位置。
  const argumentIndex = process.argv.indexOf(name);
  if (argumentIndex < 0 || argumentIndex + 1 >= process.argv.length) {
    return "";
  }
  return process.argv[argumentIndex + 1];
}

/** 读取 lark-cli 的 macOS Keychain 主密钥，并只在内存中返回解码后的 32 字节密钥。 */
function loadLarkMasterKey() {
  // storedValue 存储 macOS Keychain 返回的 go-keyring 编码值。
  const storedValue = childProcess.execFileSync(
    "security",
    ["find-generic-password", "-s", "lark-cli", "-a", "master.key", "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  ).trim();
  // encodedValue 存储去掉 go-keyring 格式前缀后的双层 Base64 数据。
  const encodedValue = storedValue.startsWith("go-keyring-base64:")
    ? storedValue.slice("go-keyring-base64:".length)
    : storedValue;
  // innerValue 存储第一层 Base64 解码出的内部 Base64 文本。
  const innerValue = Buffer.from(encodedValue, "base64").toString("utf8").trim();
  // masterKey 存储第二层解码得到的 AES-256 主密钥。
  const masterKey = Buffer.from(innerValue, "base64");
  if (masterKey.length !== 32) {
    throw new Error("lark-cli Keychain 主密钥格式无效");
  }
  return masterKey;
}

/** 解密 lark-cli 安全存储文件；secretId 是配置引用 ID，返回值仅保留在当前进程内存。 */
function decryptKeychainSecret(secretId) {
  // safeName 存储 lark-cli 把引用 ID 转换成安全文件名后的结果。
  const safeName = secretId.replace(/[^A-Za-z0-9._-]/g, "_");
  // encryptedPath 存储目标密钥的 AES-GCM 加密文件路径。
  const encryptedPath = path.join(
    process.env.HOME || "",
    "Library",
    "Application Support",
    "lark-cli",
    `${safeName}.enc`,
  );
  // encrypted 存储 nonce、密文和认证标签组成的二进制内容。
  const encrypted = fs.readFileSync(encryptedPath);
  if (encrypted.length <= 28) {
    throw new Error(`lark-cli 密钥文件格式无效：${secretId}`);
  }
  // nonce 存储 AES-GCM 使用的 12 字节随机数。
  const nonce = encrypted.subarray(0, 12);
  // authTag 存储 AES-GCM 最后的 16 字节认证标签。
  const authTag = encrypted.subarray(encrypted.length - 16);
  // ciphertext 存储 nonce 与认证标签之间的密文。
  const ciphertext = encrypted.subarray(12, encrypted.length - 16);
  // decipher 存储使用 Keychain 主密钥初始化的 AES-256-GCM 解密器。
  const decipher = crypto.createDecipheriv("aes-256-gcm", loadLarkMasterKey(), nonce);
  decipher.setAuthTag(authTag);
  // plaintext 存储解密后的应用密钥字节，函数返回后由调用方直接交给 SDK。
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return plaintext.toString("utf8");
}

/** 解析 lark-cli 的明文或安全引用密钥；secretValue 是 appSecret 配置字段。 */
function resolveAppSecret(secretValue) {
  if (typeof secretValue === "string" && secretValue) {
    return secretValue;
  }
  if (!secretValue || typeof secretValue !== "object") {
    throw new Error("飞书应用密钥配置无效");
  }
  // source 存储安全引用的数据来源类型。
  const source = secretValue.source || "";
  // secretId 存储安全引用的密钥标识或环境变量名。
  const secretId = secretValue.id || "";
  if (source === "keychain" && secretId) {
    return decryptKeychainSecret(secretId);
  }
  if (source === "env" && secretId && process.env[secretId]) {
    return process.env[secretId];
  }
  throw new Error(`暂不支持的 lark-cli 密钥来源：${source || "unknown"}`);
}

/** 从 lark-cli 配置中读取指定 profile；configPath 是配置文件，profileName 是配置名称。 */
function loadProfile(configPath, profileName) {
  // configText 存储 lark-cli 配置文件的原始 JSON 文本。
  const configText = fs.readFileSync(configPath, "utf8");
  // config 存储解析后的 lark-cli 配置对象。
  const config = JSON.parse(configText);
  // apps 存储配置中的所有飞书应用 profile。
  const apps = Array.isArray(config.apps) ? config.apps : [];
  // profile 存储名称或 App ID 与目标匹配的应用配置。
  const profile = apps.find((app) => app && (app.name === profileName || app.appId === profileName));
  if (!profile || !profile.appId || !profile.appSecret) {
    throw new Error(`找不到可用的飞书应用配置：${profileName}`);
  }
  return { ...profile, appSecret: resolveAppSecret(profile.appSecret) };
}

/** 递归提取富文本中的可见文字；node 是当前 JSON 节点，output 存储文字片段。 */
function collectVisibleText(node, output) {
  if (Array.isArray(node)) {
    for (const item of node) {
      collectVisibleText(item, output);
    }
    return;
  }
  if (!node || typeof node !== "object") {
    return;
  }
  for (const [key, value] of Object.entries(node)) {
    if ((key === "text" || key === "content") && typeof value === "string") {
      output.push(value);
      continue;
    }
    collectVisibleText(value, output);
  }
}

/** 将飞书消息 content JSON 转为桥接脚本可直接使用的文本；messageType 是消息类型。 */
function renderMessageContent(messageType, rawContent) {
  try {
    // parsedContent 存储飞书消息 content 字符串解析后的对象。
    const parsedContent = JSON.parse(rawContent || "{}");
    if (messageType === "text" && typeof parsedContent.text === "string") {
      return parsedContent.text;
    }
    if (messageType === "post") {
      // textParts 存储富文本中递归提取到的可见文字片段。
      const textParts = [];
      collectVisibleText(parsedContent, textParts);
      return textParts.join("\n");
    }
  } catch (error) {
    // 无法解析时保留原文，避免异常消息导致长连接退出。
    return typeof rawContent === "string" ? rawContent : "";
  }
  return "";
}

/** 以单行 NDJSON 输出事件；payload 是交给 Python 桥接进程的扁平对象。 */
function emitEvent(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

/** 把官方 SDK 的消息事件整理为原桥接器兼容格式；event 是飞书消息事件主体。 */
function handleMessage(event) {
  // message 存储飞书消息主体。
  const message = event.message || {};
  // sender 存储飞书消息发送者主体。
  const sender = event.sender || {};
  // senderId 存储发送者的 open_id。
  const senderId = sender.sender_id && sender.sender_id.open_id ? sender.sender_id.open_id : "";
  emitEvent({
    type: "im.message.receive_v1",
    event_id: event.event_id || event.uuid || message.message_id,
    timestamp: event.ts || "",
    id: message.message_id || "",
    message_id: message.message_id || "",
    create_time: message.create_time || "",
    chat_id: message.chat_id || "",
    chat_type: message.chat_type || "",
    message_type: message.message_type || "",
    sender_id: senderId,
    sender_type: sender.sender_type || "",
    content: renderMessageContent(message.message_type, message.content),
  });
}

/** 把官方 SDK 的卡片回调整理为原桥接器兼容格式；event 是卡片交互事件主体。 */
function handleCardAction(event) {
  // context 存储卡片所在消息与会话信息。
  const context = event.context || {};
  // action 存储按钮或表单触发的动作信息。
  const action = event.action || {};
  // operator 存储点击卡片的用户信息。
  const operator = event.operator || {};
  // messageId 存储卡片消息 ID。
  const messageId = context.open_message_id || event.open_message_id || "";
  // actionValue 存储按钮配置的开发者业务参数。
  const actionValue = action.value === undefined ? {} : action.value;
  // rawFormValue 存储不同 SDK 版本可能放在 action 或事件根级的表单字段。
  const rawFormValue = action.form_value ?? event.form_value ?? "";
  // normalizedFormValue 存储去除 SDK 二次 JSON 包装后的表单对象或空字符串。
  let normalizedFormValue = rawFormValue;
  if (typeof rawFormValue === "string" && rawFormValue) {
    try {
      normalizedFormValue = JSON.parse(rawFormValue);
    } catch {
      normalizedFormValue = rawFormValue;
    }
  }
  // formValue 存储供 Python 统一解析的单层 JSON 字符串。
  const formValue = normalizedFormValue === "" ? "" : JSON.stringify(normalizedFormValue);
  emitEvent({
    type: "card.action.trigger",
    event_id: event.event_id || `${messageId}:${Date.now()}`,
    timestamp: event.ts || "",
    operator_id: operator.open_id || "",
    message_id: messageId,
    chat_id: context.open_chat_id || event.open_chat_id || "",
    host: context.host || "im_message",
    token: event.token || "",
    action_tag: action.tag || "",
    action_value: JSON.stringify(actionValue),
    action_name: action.name || event.action_name || "",
    form_value: formValue,
    input_value: action.input_value || "",
    option: action.option || "",
    options: Array.isArray(action.options) ? action.options.join(",") : action.options || "",
    checked: Boolean(action.checked),
    timezone: action.timezone || "",
  });
}

/** 启动同时注册消息与卡片回调的单条飞书长连接。 */
async function main() {
  // configPath 存储 lark-cli 配置文件路径。
  const configPath = readArgument("--config");
  // profileName 存储要使用的 lark-cli profile 名称。
  const profileName = readArgument("--profile");
  if (!configPath || !profileName) {
    throw new Error("必须提供 --config 和 --profile");
  }
  // profile 存储当前飞书应用的 App ID 与密钥。
  const profile = loadProfile(path.resolve(configPath), profileName);
  // dispatcher 存储一条长连接内的全部事件处理器，回调返回前 SDK 会立即确认飞书请求。
  const dispatcher = new Lark.EventDispatcher({ loggerLevel: Lark.LoggerLevel.error }).register({
    "im.message.receive_v1": async (event) => handleMessage(event),
    "card.action.trigger": async (event) => handleCardAction(event),
  });
  // client 存储官方飞书 WebSocket 客户端。
  const client = new Lark.WSClient({
    appId: profile.appId,
    appSecret: profile.appSecret,
    domain: profile.brand === "lark" ? Lark.Domain.Lark : Lark.Domain.Feishu,
    loggerLevel: Lark.LoggerLevel.error,
    onReady: () => process.stderr.write("[gateway] ready\n"),
    onError: (error) => process.stderr.write(`[gateway] error: ${error.message}\n`),
  });
  // stopConnection 在进程退出时关闭长连接，避免留下重复在线实例。
  const stopConnection = () => {
    client.close({});
    process.exit(0);
  };
  process.on("SIGTERM", stopConnection);
  process.on("SIGINT", stopConnection);
  await client.start({ eventDispatcher: dispatcher });
}

main().catch((error) => {
  process.stderr.write(`[gateway] fatal: ${error.message}\n`);
  process.exit(1);
});
