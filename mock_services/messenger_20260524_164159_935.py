"""消息发送 Mock 服务。"""
from datetime import datetime
from mock_services.base import MockService


class MessengerService(MockService):
    def __init__(self):
        super().__init__(
            name="MessengerService",
            latency_range=(0.05, 0.2),
            failure_rate=0.02,
            timeout=1.0,
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {
            "recipient": "小张",
            "message": "搞定了，下午2点出发..."
        }
        """
        return {
            "status": "sent",
            "recipient": params.get("recipient", ""),
            "message": params.get("message", ""),
            "sent_at": datetime.now().isoformat(),
        }

    async def send(self, message: str, recipient: str = "小张") -> dict:
        """便捷发送方法"""
        return await self.call({"recipient": recipient, "message": message})