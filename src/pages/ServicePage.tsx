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
}

/** ServicePage 组合服务状态和本机诊断两个独立面板。 */
export function ServicePage(props: ServicePageProps) {
  return (
    <div className="content-stack">
      <ServiceOverview
        snapshot={props.snapshot}
        busy={props.busy}
        onStart={props.onStart}
        onStop={props.onStop}
        onRestart={props.onRestart}
      />
      <DiagnosticsPanel
        snapshot={props.snapshot}
        onAutoStart={props.onAutoStart}
        onReveal={props.onReveal}
        onDisableLegacy={props.onDisableLegacy}
        onClearRuntime={props.onClearRuntime}
      />
    </div>
  );
}
