import { useEffect, useMemo, useState } from "react";
import { App, Button, Empty, Input, Spin, Tabs, Tooltip } from "antd";
import {
  CodeOutlined,
  CopyOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { BridgeTask } from "../types/bridge";

/** DEFAULT_VISIBLE_LOG_LINES 存储首次打开日志页时展示的最近日志行数。 */
const DEFAULT_VISIBLE_LOG_LINES = 100;
/** LOG_LINES_PAGE_SIZE 存储每次继续查看时增加的历史日志行数。 */
const LOG_LINES_PAGE_SIZE = 100;
/** LOG_TIMESTAMP_PATTERN 存储桥接日志行开头的时间戳格式。 */
const LOG_TIMESTAMP_PATTERN = /^\[([^\]]+)]\s*(.*)$/;
/** LOG_TASK_PATTERN 存储桥接任务上下文支持的文本格式。 */
const LOG_TASK_PATTERN = /(?:task_id=|任务\s+)(t\d+)\b/i;
/** ALL_LOGS_CATEGORY 存储全部日志分类的稳定键。 */
const ALL_LOGS_CATEGORY = "all";
/** SYSTEM_LOGS_CATEGORY 存储不属于具体任务的系统日志分类键。 */
const SYSTEM_LOGS_CATEGORY = "system";

/** ParsedLogEntry 描述一行日志拆解后的显示内容和可选 JSON 数据。 */
interface ParsedLogEntry {
  lineNumber: number;
  timestamp: string;
  message: string;
  json: unknown | null;
  taskId: string;
}

/** LogsPanelProps 描述日志面板输入。 */
interface LogsPanelProps {
  logs: string;
  tasks: BridgeTask[];
  loading: boolean;
  onRefresh(): void;
  onClear(): Promise<void>;
}

/** LogsPanel 展示可搜索、分页和解析 JSON 的桥接主日志尾部。 */
export function LogsPanel({
  logs,
  tasks,
  loading,
  onRefresh,
  onClear,
}: LogsPanelProps) {
  /** modalApi 和 messageApi 使用 Ant Design 上下文，确保弹层与提示跟随当前主题。 */
  const { modal: modalApi, message: messageApi } = App.useApp();
  /** query 存储当前日志查询关键字。 */
  const [query, setQuery] = useState("");
  /** visibleLineLimit 存储无查询时允许展示的最近日志行数。 */
  const [visibleLineLimit, setVisibleLineLimit] = useState(
    DEFAULT_VISIBLE_LOG_LINES,
  );
  /** expandedJsonLine 存储当前展开 JSON 的原始日志行号。 */
  const [expandedJsonLine, setExpandedJsonLine] = useState<number | null>(null);
  /** activeCategory 存储当前选择的全部、系统或具体任务分类。 */
  const [activeCategory, setActiveCategory] = useState(ALL_LOGS_CATEGORY);

  useEffect(() => {
    // 日志刷新后回到最近一页，避免历史展开状态让页面再次铺满。
    setVisibleLineLimit(DEFAULT_VISIBLE_LOG_LINES);
    setExpandedJsonLine(null);
  }, [logs]);

  /** parsedEntries 存储从原始文本拆出的全部非空日志行。 */
  const parsedEntries = useMemo<ParsedLogEntry[]>(() => {
    return logs
      .split(/\r?\n/)
      .map((line, lineNumber) => {
        /** timestampMatch 存储日志行可能存在的时间戳匹配结果。 */
        const timestampMatch = line.match(LOG_TIMESTAMP_PATTERN);
        /** timestamp 存储独立展示的日志时间。 */
        const timestamp = timestampMatch?.[1] ?? "";
        /** rawMessage 存储去掉时间戳后的原始日志正文。 */
        const rawMessage = timestampMatch?.[2] ?? line;
        /** objectStart 和 arrayStart 存储正文中可能的 JSON 起始位置。 */
        const objectStart = rawMessage.indexOf("{");
        const arrayStart = rawMessage.indexOf("[");
        /** jsonCandidates 存储按出现顺序排列的 JSON 候选位置。 */
        const jsonCandidates = [objectStart, arrayStart]
          .filter((index) => index >= 0)
          .sort((left, right) => left - right);
        /** jsonStart 存储最终成功解析的 JSON 起始位置。 */
        let jsonStart: number | undefined;
        /** parsedJson 存储正文末尾成功解析出的 JSON 数据。 */
        let parsedJson: unknown | null = null;
        for (const candidate of jsonCandidates) {
          // 日志正文可能先含普通方括号；逐个尝试才能识别其后的真实 JSON。
          try {
            parsedJson = JSON.parse(rawMessage.slice(candidate));
            jsonStart = candidate;
            break;
          } catch {
            parsedJson = null;
          }
        }
        /** message 存储不重复展示已解析 JSON 的人类可读正文。 */
        const message =
          parsedJson === null
            ? rawMessage
            : rawMessage.slice(0, jsonStart).trim();
        /** textTaskMatch 存储正文中显式的任务 ID。 */
        const textTaskMatch = rawMessage.match(LOG_TASK_PATTERN);
        /** jsonRecord 存储可安全读取 task_id 的 JSON 对象。 */
        const jsonRecord =
          parsedJson &&
          typeof parsedJson === "object" &&
          !Array.isArray(parsedJson)
            ? (parsedJson as Record<string, unknown>)
            : null;
        /** directJsonTaskId 存储 JSON 顶层直接携带的任务 ID。 */
        const directJsonTaskId =
          typeof jsonRecord?.task_id === "string" ? jsonRecord.task_id : "";
        /** actionValue 存储卡片回调里可能二次编码的动作 JSON。 */
        const actionValue =
          typeof jsonRecord?.action_value === "string"
            ? jsonRecord.action_value
            : "";
        /** nestedTaskId 存储从二次编码动作中解析出的任务 ID。 */
        let nestedTaskId = "";
        if (actionValue) {
          try {
            /** actionRecord 存储卡片 action_value 解码后的对象。 */
            const actionRecord = JSON.parse(actionValue) as unknown;
            if (
              actionRecord &&
              typeof actionRecord === "object" &&
              !Array.isArray(actionRecord) &&
              typeof (actionRecord as Record<string, unknown>).task_id ===
                "string"
            ) {
              nestedTaskId = String(
                (actionRecord as Record<string, unknown>).task_id,
              );
            }
          } catch {
            nestedTaskId = "";
          }
        }
        /** taskId 存储当前日志最终归属的任务 ID。 */
        const taskId = (
          textTaskMatch?.[1] ||
          directJsonTaskId ||
          nestedTaskId
        ).toLocaleLowerCase();
        return {
          lineNumber,
          timestamp,
          message,
          json: parsedJson,
          taskId,
        };
      })
      .filter(
        (entry) => entry.timestamp || entry.message || entry.json !== null,
      );
  }, [logs]);

  /** taskCategories 存储任务快照和日志历史共同组成的任务分类。 */
  const taskCategories = useMemo(() => {
    /** taskTitles 存储当前任务 ID 到可读标题的映射。 */
    const taskTitles = new Map(tasks.map((task) => [task.task_id, task.title]));
    /** taskIds 存储当前与历史日志中出现的全部任务 ID。 */
    const taskIds = new Set([
      ...tasks.map((task) => task.task_id),
      ...parsedEntries.map((entry) => entry.taskId).filter(Boolean),
    ]);
    return [...taskIds]
      .sort((left, right) =>
        left.localeCompare(right, undefined, { numeric: true }),
      )
      .map((taskId) => ({
        key: taskId,
        label: taskTitles.get(taskId)
          ? `${taskId} · ${taskTitles.get(taskId)}`
          : taskId,
      }));
  }, [parsedEntries, tasks]);

  /** filteredEntries 存储匹配查询关键字的日志行。 */
  const filteredEntries = useMemo(() => {
    /** normalizedQuery 存储忽略首尾空白和大小写的查询文本。 */
    const normalizedQuery = query.trim().toLocaleLowerCase();
    /** categoryEntries 存储当前任务分类允许查询的日志。 */
    const categoryEntries = parsedEntries.filter((entry) => {
      if (activeCategory === ALL_LOGS_CATEGORY) return true;
      if (activeCategory === SYSTEM_LOGS_CATEGORY) return !entry.taskId;
      return entry.taskId === activeCategory;
    });
    if (!normalizedQuery) return categoryEntries;
    return categoryEntries.filter((entry) =>
      `${entry.timestamp} ${entry.message} ${entry.json === null ? "" : JSON.stringify(entry.json)}`
        .toLocaleLowerCase()
        .includes(normalizedQuery),
    );
  }, [activeCategory, parsedEntries, query]);

  /** categoryItems 存储全部、系统及各任务的可点击日志分类。 */
  const categoryItems = [
    { key: ALL_LOGS_CATEGORY, label: "全部" },
    { key: SYSTEM_LOGS_CATEGORY, label: "系统" },
    ...taskCategories,
  ];

  /** visibleEntries 存储本次实际渲染的搜索结果或最近日志。 */
  const visibleEntries = query.trim()
    ? filteredEntries
    : filteredEntries.slice(-visibleLineLimit);
  /** hiddenLineCount 存储默认视图中尚未展示的更早日志数量。 */
  const hiddenLineCount = Math.max(
    filteredEntries.length - visibleEntries.length,
    0,
  );

  return (
    <section className="panel logs-panel">
      <div className="logs-toolbar">
        <Input.Search
          allowClear
          value={query}
          placeholder="查询日志内容或 JSON 字段"
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="panel-actions">
          <Button icon={<ReloadOutlined />} onClick={onRefresh}>
            刷新
          </Button>
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={!logs}
            onClick={() =>
              modalApi.confirm({
                centered: true,
                className: "center-confirm-modal",
                title: "清空运行日志",
                content: "确定清空当前桥接运行日志吗？此操作不可恢复。",
                okText: "清空",
                cancelText: "取消",
                okButtonProps: { danger: true },
                onOk: onClear,
              })
            }
          >
            清空
          </Button>
        </div>
      </div>
      <Tabs
        className="logs-categories"
        activeKey={activeCategory}
        items={categoryItems}
        onChange={(category) => {
          setActiveCategory(category);
          setVisibleLineLimit(DEFAULT_VISIBLE_LOG_LINES);
          setExpandedJsonLine(null);
        }}
      />
      <Spin spinning={loading}>
        {logs ? (
          <div className="logs-content">
            <div className="logs-summary">
              {query.trim()
                ? `找到 ${filteredEntries.length} 条日志`
                : `显示最近 ${visibleEntries.length} 条，共 ${filteredEntries.length} 条`}
            </div>
            {visibleEntries.length ? (
              <div className="log-list">
                {visibleEntries.map((entry) => {
                  /** formattedJson 存储当前日志 JSON 的缩进文本。 */
                  const formattedJson =
                    entry.json === null
                      ? ""
                      : JSON.stringify(entry.json, null, 2);
                  /** jsonExpanded 标记当前日志的 JSON 是否已展开。 */
                  const jsonExpanded = expandedJsonLine === entry.lineNumber;
                  return (
                    <div className="log-entry" key={entry.lineNumber}>
                      <div className="log-entry-main">
                        {entry.timestamp ? (
                          <time>{entry.timestamp}</time>
                        ) : null}
                        <span>{entry.message}</span>
                        {entry.json !== null ? (
                          <Tooltip
                            title={jsonExpanded ? "收起 JSON" : "解析 JSON"}
                          >
                            <Button
                              type="text"
                              size="small"
                              aria-label={
                                jsonExpanded ? "收起 JSON" : "解析 JSON"
                              }
                              icon={<CodeOutlined />}
                              onClick={() =>
                                setExpandedJsonLine(
                                  jsonExpanded ? null : entry.lineNumber,
                                )
                              }
                            />
                          </Tooltip>
                        ) : null}
                      </div>
                      {jsonExpanded ? (
                        <div className="log-json-view">
                          <Tooltip title="复制 JSON">
                            <Button
                              type="text"
                              size="small"
                              aria-label="复制 JSON"
                              icon={<CopyOutlined />}
                              onClick={async () => {
                                try {
                                  await navigator.clipboard.writeText(
                                    formattedJson,
                                  );
                                  void messageApi.success("JSON 已复制");
                                } catch {
                                  void messageApi.error(
                                    "复制失败，请检查剪贴板权限",
                                  );
                                }
                              }}
                            />
                          </Tooltip>
                          <pre>{formattedJson}</pre>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="没有匹配的日志"
              />
            )}
            {!query.trim() && hiddenLineCount > 0 ? (
              <Button
                className="load-more-logs"
                onClick={() =>
                  setVisibleLineLimit(
                    (currentLimit) => currentLimit + LOG_LINES_PAGE_SIZE,
                  )
                }
              >
                显示更早日志（还有 {hiddenLineCount} 条）
              </Button>
            ) : null}
          </div>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无日志" />
        )}
      </Spin>
    </section>
  );
}
