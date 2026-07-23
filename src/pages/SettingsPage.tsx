import { SettingsPanel } from "../components/SettingsPanel";
import type { BridgeConfig } from "../types/bridge";

/** SettingsPageProps 描述设置页数据和保存操作。 */
interface SettingsPageProps {
  config: BridgeConfig;
  saving: boolean;
  onSave(config: BridgeConfig): void;
}

/** SettingsPage 为设置面板提供稳定页面边界。 */
export function SettingsPage(props: SettingsPageProps) {
  return (
    <SettingsPanel
      key={JSON.stringify(props.config)}
      config={props.config}
      saving={props.saving}
      onSave={props.onSave}
    />
  );
}
