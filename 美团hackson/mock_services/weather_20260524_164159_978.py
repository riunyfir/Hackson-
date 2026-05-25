"""天气查询 Mock 服务。"""
import random
from mock_services.base import MockService


class WeatherService(MockService):
    def __init__(self):
        super().__init__(
            name="WeatherService",
            latency_range=(0.1, 0.5),
            failure_rate=0.05,
            timeout=1.5,
            data_file="data/mock/weather.json",
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {"time": "afternoon"}
        返回下午时段的天气
        """
        weather = random.choice(self.data)
        return {"items": [weather]}