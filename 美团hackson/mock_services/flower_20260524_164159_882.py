"""鲜花配送 Mock 服务。"""
import random
from mock_services.base import MockService, ServiceUnavailableError


class FlowerService(MockService):
    def __init__(self):
        super().__init__(
            name="FlowerService",
            latency_range=(0.2, 0.8),
            failure_rate=0.1,
            timeout=2.0,
            data_file="data/mock/flowers.json",
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {
            "occasion": "celebration",
            "delivery_time": "16:00",
            "delivery_location": "餐厅地址",
            "action": "search" | "order",
            "item_name": "...",            # order 时使用
        }
        """
        action = params.get("action", "search")

        if action == "search":
            occasion = params.get("occasion", "")
            items = [item for item in self.data if occasion in item.get("tags", [])]
            return {"items": items[:3]}

        elif action == "order":
            delivery_time = params.get("delivery_time", "")
            if delivery_time and random.random() < 0.15:
                alternative = "17:00"
                return {
                    "status": "time_unavailable",
                    "alternative_time": alternative,
                    "message": f"配送时段 {delivery_time} 不可用，建议 {alternative}",
                }

            if random.random() < 0.1:
                raise ServiceUnavailableError("Delivery service unavailable")

            return {
                "status": "ordered",
                "item": params.get("item_name", "鲜花"),
                "delivery_time": params.get("delivery_time", ""),
                "delivery_location": params.get("delivery_location", ""),
                "order_id": f"FLW-{random.randint(10000, 99999)}",
            }