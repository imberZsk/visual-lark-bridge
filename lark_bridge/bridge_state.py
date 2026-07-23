"""BridgeStateMixin 拆分出的应用职责。"""

from __future__ import annotations

import json


from .config import CARD_LAYOUT_VERSION


class BridgeStateMixin:
    def _load_task_cards(self) -> dict[str, tuple[str, str, int]]:
        """读取仍有对应任务的 CardKit 映射，供服务重启后继续更新旧卡片。"""
        if not self.card_state_path.exists():
            return {}
        try:
            # payload 存储 cards-state.json 解析后的任务卡片对象。
            payload = json.loads(self.card_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        if payload.get("layout_version") != CARD_LAYOUT_VERSION:
            # 旧版卡片含已移除的折叠面板，放弃映射后下次提问会创建新版卡片。
            return {}
        # cards_payload 存储当前结构版本下的任务卡映射。
        cards_payload = payload.get("cards")
        if not isinstance(cards_payload, dict):
            return {}
        # restored_cards 存储校验通过且任务仍存在的卡片映射。
        restored_cards: dict[str, tuple[str, str, int]] = {}
        for task_id, value in cards_payload.items():
            if task_id not in self.task_manager.tasks or not isinstance(value, dict):
                continue
            # card_id 存储持久化的 CardKit 实体 ID。
            card_id = value.get("card_id")
            # message_id 存储卡片所在的飞书消息 ID。
            message_id = value.get("message_id")
            # sequence 存储下一次 CardKit 更新必须使用的递增序号。
            sequence = value.get("sequence")
            if (
                isinstance(card_id, str)
                and isinstance(message_id, str)
                and isinstance(sequence, int)
            ):
                restored_cards[task_id] = (card_id, message_id, sequence)
        return restored_cards

    def _save_task_cards(self) -> None:
        """原子保存任务到 CardKit 实体的映射，避免服务重启后旧卡失去对话能力。"""
        self.card_state_path.parent.mkdir(parents=True, exist_ok=True)
        # cards_payload 存储适合 JSON 序列化的任务卡片映射。
        cards_payload = {
            task_id: {
                "card_id": card_id,
                "message_id": message_id,
                "sequence": sequence,
            }
            for task_id, (card_id, message_id, sequence) in self.task_cards.items()
            if task_id in self.task_manager.tasks
        }
        # payload 存储布局版本和卡片映射，结构升级时可以安全弃用旧活动卡。
        payload = {
            "layout_version": CARD_LAYOUT_VERSION,
            "cards": cards_payload,
        }
        # temp_path 存储原子替换前的临时状态文件路径。
        temp_path = self.card_state_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(self.card_state_path)
