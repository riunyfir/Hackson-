"""餐厅搜索 + 订座 Mock 服务。"""
import random
from mock_services.base import MockService, ServiceUnavailableError


class RestaurantService(MockService):
    def __init__(self):
        super().__init__(
            name="RestaurantService",
            latency_range=(0.3, 1.0),
            failure_rate=0.12,
            timeout=2.0,
            data_file="data/mock/restaurants.json",
        )

    def _handle(self, params: dict) -> dict:
        action = params.get("action", "search")

        if action == "search":
            items = list(self.data)  # 复制避免修改原始数据
            items = self._filter_by_tags(items, params.get("tags", []))
            items = self._filter_by_distance(items, params.get("distance_km", 10))
            items = self._filter_by_people(items, params.get("people_count", 1))

            # 模拟实时空位状态（随机）
            for item in items:
                item["availability"] = random.random() > 0.2
                if item["availability"]:
                    item["available_slots"] = ["17:30", "18:00", "18:30", "19:00"]

            return {"items": items[:5]}

        elif action == "reserve":
            if random.random() < 0.1:
                raise ServiceUnavailableError("No table available for this time")
            return {
                "status": "reserved",
                "restaurant": params.get("restaurant_name", ""),
                "time": params.get("time", ""),
                "people": params.get("people_count", 0),
                "confirmation_code": f"RSV-{random.randint(10000, 99999)}",
            }