"""真实 API 服务基类。"""
import asyncio
from abc import ABC, abstractmethod
import httpx


class ServiceTimeoutError(Exception):
    """服务超时异常"""
    pass


class ServiceUnavailableError(Exception):
    """服务不可用异常"""
    pass


class RealService(ABC):
    """真实 HTTP API 服务基类"""

    def __init__(self, name: str, timeout: float = 5.0):
        self.name = name
        self.timeout = timeout

    async def call(self, params: dict, timeout: float | None = None) -> dict:
        """
        调用真实 API：
        1. 构造请求参数 → _build_params(params)
        2. 解析返回结果 → _parse_response(content)
        3. 返回统一格式 {"items": [...]}
        """
        effective_timeout = timeout or self.timeout
        url, req_params, headers = self._build_params(params)

        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            try:
                response = await client.get(url, params=req_params, headers=headers)
                response.raise_for_status()
                data = response.json()
                return self._parse_response(data, params)
            except httpx.TimeoutException:
                raise ServiceTimeoutError(f"{self.name} timeout after {effective_timeout}s")
            except httpx.HTTPStatusError as e:
                raise ServiceUnavailableError(f"{self.name} HTTP {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                raise ServiceUnavailableError(f"{self.name} error: {str(e)}")

    @abstractmethod
    def _build_params(self, params: dict) -> tuple[str, dict, dict]:
        """返回 (url, query_params, headers)"""
        pass

    @abstractmethod
    def _parse_response(self, raw_data: dict, original_params: dict) -> dict:
        """解析原始 API 返回，转为统一格式 {"items": [...]}"""
        pass