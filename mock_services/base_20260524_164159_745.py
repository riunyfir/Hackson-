"""所有 Mock 服务的基类。"""
import asyncio
import random
import json
from abc import ABC, abstractmethod


class ServiceTimeoutError(Exception):
    """服务超时异常"""
    pass


class ServiceUnavailableError(Exception):
    """服务不可用异常"""
    pass


class MockService(ABC):
    """所有 Mock 服务的基类"""

    def __init__(
        self,
        name: str,
        latency_range: tuple[float, float] = (0.2, 1.0),
        failure_rate: float = 0.15,
        timeout: float = 2.0,
        data_file: str | None = None,
    ):
        self.name = name
        self.latency_min, self.latency_max = latency_range
        self.failure_rate = failure_rate
        self.timeout = timeout
        self.data: list[dict] = []
        if data_file:
            self._load_data(data_file)

    def _load_data(self, filepath: str):
        """从 JSON 文件加载预置数据集"""
        import os
        # 支持相对路径：从项目根目录查找
        if not os.path.isabs(filepath):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            filepath = os.path.join(base_dir, filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    async def call(self, params: dict, timeout: float | None = None) -> dict:
        """
        模拟 API 调用：
        1. 随机延迟 latency_min ~ latency_max
        2. 如果延迟 > timeout → 抛出 ServiceTimeoutError
        3. 概率 failure_rate → 抛出 ServiceUnavailableError
        4. 否则 → 调用子类 _handle(params)
        """
        effective_timeout = timeout or self.timeout
        latency = random.uniform(self.latency_min, self.latency_max)

        if latency > effective_timeout:
            await asyncio.sleep(effective_timeout)
            raise ServiceTimeoutError(f"{self.name} timeout after {effective_timeout}s")
        else:
            await asyncio.sleep(latency)

        if random.random() < self.failure_rate:
            raise ServiceUnavailableError(f"{self.name} temporarily unavailable")

        return self._handle(params)

    @abstractmethod
    def _handle(self, params: dict) -> dict:
        """
        子类实现：实际业务逻辑。
        返回格式：{"items": [{"id": "...", "name": "...", ...}]}
        """
        pass

    def _filter_by_tags(self, items: list[dict], tags: list[str]) -> list[dict]:
        """按标签过滤，匹配越多排序越靠前"""
        scored = []
        for item in items:
            item_tags = item.get("tags", [])
            score = sum(1 for t in tags if t in item_tags)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def _filter_by_distance(self, items: list[dict], max_km: float) -> list[dict]:
        """按距离过滤"""
        return [item for item in items if item.get("distance_km", 0) <= max_km]

    def _filter_by_people(self, items: list[dict], people_count: int) -> list[dict]:
        """按容纳人数过滤"""
        return [item for item in items if item.get("max_people", 999) >= people_count]