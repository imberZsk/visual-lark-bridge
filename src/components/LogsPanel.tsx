import { useEffect, useMemo, useState } from "react";
import { App, Button, Empty, Input, Spin, Tooltip } from "antd";
import {
  CodeOutlined,
  CopyOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

/** DEFAULT_VISIBLE_LOG_LINES 存储首次打开日志页时展示的最近日志行数。 */
const DEFAULT_VISIBLE_LOG_LINES = 100;
/** LOG_LINES_PAGE_SIZE 存储每次继续查看时增加的历史日志行数。 */
const LOG_LINES_PAGE_SIZE = 100;
/** LOG_TIMESTAMP_PATTERN 存储桥接日志行开头的时间戳格式。 */
const LOG_TIMESTAMP_PATTERN = /^\[([^\]]+)]\s*(.*)$/;

/** ParsedLogEntry 描述一行日志拆解后的显示内容和可选 JSON 数据。 */
interface ParsedLogEntry {
  lineNumber: number;
  timestamp: string;
  message: string;
  json: unknown | null;
}

/** LogsPanelProps 描述日志面板输入。 */
interface LogsPanelProps {
  logs: string;
  loading: boolean;
  onRefresh(): void;
  onClear(): Promise<void>;
}

/** LogsPanel 展示可搜索、分页和解析 JSON 的桥接主日志尾部。 */
export function LogsPanel({
  logs,
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
        return { lineNumber, timestamp, message, json: parsedJson };
      })
      .filter(
        (entry) => entry.timestamp || entry.message || entry.json !== null,
      );
  }, [logs]);

  /** filteredEntries 存储匹配查询关键字的日志行。 */
  const filteredEntries = useMemo(() => {
    /** normalizedQuery 存储忽略首尾空白和大小写的查询文本。 */
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return parsedEntries;
    return parsedEntries.filter((entry) =>
      `${entry.timestamp} ${entry.message} ${entry.json === null ? "" : JSON.stringify(entry.json)}`
        .toLocaleLowerCase()
        .includes(normalizedQuery),
    );
  }, [parsedEntries, query]);

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
