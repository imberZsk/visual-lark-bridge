import { DiagnosticsPanel } from "../components/DiagnosticsPanel";
import { ServiceOverview } from "../components/ServiceOverview";
import type { BridgeSnapshot } from "../types/bridge";

/** ServicePageProps 描述服务页数据和维护操作。 */
interface ServicePageProps {
  snapshot: BridgeSnapshot;
  busy: boolean;
  onStart(): void;
  onStop(): void;
  onRestart(): void;
  onAutoStart(enabled: boolean): void;
  onReveal(): void;
  onDisableLegacy(): void;
  onClearRuntime(): void;
  onDeleteTask(taskId: string): Promise<void>;
}

/** ServicePage 在单一工作区中组合服务状态和本机诊断。 */
export function ServicePage(props: ServicePageProps) {
  return (
    <section className="panel service-page service-panel">
      <ServiceOverview
        snapshot={props.snapshot}
        busy={props.busy}
        onStart={props.onStart}
        onStop={props.onStop}
        onRestart={props.onRestart}
        onDeleteTask={props.onDeleteTask}
      />
      <Divider />
      <DiagnosticsPanel
        snapshot={props.snapshot}
        onAutoStart={props.onAutoStart}
        onReveal={props.onReveal}
        onDisableLegacy={props.onDisableLegacy}
        onClearRuntime={props.onClearRuntime}
      />
    </section>
  );
}
import { Divider } from "antd";
