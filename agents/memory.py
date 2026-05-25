"""Memory Agent：偏好查询与记录。"""
import json
from pathlib import Path
from typing import Optional
from models.messages import ParsedIntent, ExecutionPlan, PreferenceQueryResult, PreferenceRecord
from utils.logger import memory_logger


class MemoryAgent:
    def __init__(self, storage_path: str = "data/runtime/preferences.json"):
        self.storage_path = Path(storage_path)
        self._ensure_storage()

    def _ensure_storage(self):
        """确保存储文件存在，不存在则创建空文件"""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self.storage_path.write_text('{"records": []}', encoding="utf-8")

    async def query(self, intent: ParsedIntent) -> PreferenceQueryResult:
        """
        根据意图查询匹配的历史偏好。
        匹配逻辑：按场景标签匹配，聚合标签权重
        """
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            memory_logger.warning("偏好文件损坏或不存在，返回空偏好")
            return PreferenceQueryResult(matched=False)

        records = [PreferenceRecord(**r) for r in data.get("records", [])]

        matched = []
        for r in records:
            if intent.scene in r.scenario_tags:
                matched.append(r)

        if not matched:
            memory_logger.info(f"未找到 {intent.scene} 场景的历史偏好")
            return PreferenceQueryResult(matched=False)

        weights = {}
        preferred = set()
        rejected = set()
        for r in matched[-5:]:
            for tag in r.chosen_restaurant_tags + r.chosen_activity_tags:
                weights[tag] = weights.get(tag, 1.0) + 0.5
                preferred.add(tag)
            for item in r.rejected_items:
                rejected.add(item)

        memory_logger.info(f"找到 {len(matched)} 条历史偏好，权重聚合完成")
        return PreferenceQueryResult(
            matched=True,
            weights=weights,
            preferred_tags=list(preferred),
            rejected_tags=list(rejected),
            last_scenario=matched[-1] if matched else None,
        )

    async def record(
        self,
        plan: ExecutionPlan,
        scenario_tags: list[str],
        rejected_items: Optional[list[str]] = None,
    ):
        """记录本次选择，保留最近 50 条。"""
        restaurant_tags = []
        activity_tags = []
        for booking in plan.bookings:
            if booking.service == "restaurant":
                restaurant_tags.extend(booking.payload.get("tags", []))
            elif booking.service == "activity":
                activity_tags.extend(booking.payload.get("tags", []))

        record = PreferenceRecord(
            scenario_tags=scenario_tags,
            chosen_restaurant_tags=restaurant_tags,
            chosen_activity_tags=activity_tags,
            rejected_items=rejected_items or [],
            budget_level="medium",
        )

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            data = {"records": []}

        data["records"].append(record.model_dump())
        data["records"] = data["records"][-50:]

        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        memory_logger.info(f"偏好已记录，当前共 {len(data['records'])} 条记录")