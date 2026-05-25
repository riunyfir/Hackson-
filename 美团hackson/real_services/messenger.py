"""钉钉机器人 Webhook 消息推送服务。"""
from real_services.base import RealService
from datetime import datetime
import httpx
import asyncio

DINGTALK_WEBHOOK = (
    "https://oapi.dingtalk.com/robot/send"
    "?access_token=29e488ab6077ff3b205193d6b34bd64dde28a17f4a96ed0de8d0de7c67986f89"
)

# 钉钉速率限制：每分钟最多 20 条
_last_send_time = 0


class RealMessengerService(RealService):
    """钉钉群机器人消息推送"""

    def __init__(self):
        super().__init__(name="MessengerService", timeout=5.0)

    def _build_params(self, params: dict) -> tuple[str, dict, dict]:
        return DINGTALK_WEBHOOK, {}, {"Content-Type": "application/json"}

    async def call(self, params: dict, timeout: float | None = None) -> dict:
        """钉钉使用 POST + JSON body，覆盖基类"""
        effective_timeout = timeout or self.timeout

        message = params.get("message", "")
        recipient = params.get("recipient", "")

        # 构建 Markdown 消息体
        title = f"活动规划结果"
        text = f"## {title}\n\n{message}\n\n---\n*发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*"

        body = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text,
            },
        }

        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            try:
                response = await client.post(
                    DINGTALK_WEBHOOK,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
                errcode = data.get("errcode", -1)
                if errcode != 0:
                    return {
                        "status": "failed",
                        "error": data.get("errmsg", "Unknown DingTalk error"),
                        "recipient": recipient,
                        "message": message[:100],
                        "sent_at": datetime.now().isoformat(),
                    }
                return {
                    "status": "sent",
                    "recipient": recipient,
                    "message": message[:100],
                    "sent_at": datetime.now().isoformat(),
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "error": str(e),
                    "recipient": recipient,
                    "message": message[:100],
                    "sent_at": datetime.now().isoformat(),
                }

    def _parse_response(self, raw_data: dict, original_params: dict) -> dict:
        return raw_data

    async def send(self, message: str, recipient: str = "小张") -> dict:
        """便捷发送方法"""
        return await self.call({"recipient": recipient, "message": message})