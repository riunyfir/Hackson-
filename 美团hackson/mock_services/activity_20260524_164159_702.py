"""活动搜索 + 购票 Mock 服务。"""
import random
from mock_services.base import MockService, ServiceUnavailableError


class ActivityService(MockService):
    def __init__(self):
        super().__init__(
            name="ActivityService",
            latency_range=(0.3, 1.2),
            failure_rate=0.12,
            timeout=2.0,
            data_file="data/mock/activities.json",
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {
            "tags": ["kids_playground", "indoor"],
            "distance_km": 10.0,
            "people_count": 3,
            "duration_hours": 2,
            "action": "search" | "order",
            "activity_name": "...",    # order 时使用
        }
        """
        action = params.get("action", "search")

        if action == "search":
            items = self._filter_by_tags(self.data, params.get("tags", []))
            items = self._filter_by_distance(items, params.get("distance_km", 10))

            # 剩余票数模拟
            for item in items:
                item["remaining_tickets"] = random.randint(0, 50)
                item["availability"] = item["remaining_tickets"] >= params.get("people_count", 1)

            return {"items": items[:5]}

        elif action == "order":
            if random.random() < 0.1:
                raise ServiceUnavailableError("Tickets sold out")
            return {
                "status": "ordered",
                "activity": params.get("activity_name", ""),
                "tickets": params.get("people_count", 0),
                "total_price": params.get("people_count", 0) * random.randint(30, 150),
                "order_id": f"ORD-{random.randint(10000, 99999)}",
            }