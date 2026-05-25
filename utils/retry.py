"""异步重试装饰器。"""
import asyncio
import functools
from typing import TypeVar, Callable, Any
from utils.logger import setup_logger

T = TypeVar("T")
retry_logger = setup_logger("Retry")


def retry(
    max_attempts: int = 2,
    backoff: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """
    异步重试装饰器。

    Args:
        max_attempts: 最大尝试次数（含首次）
        backoff: 退避时间（秒），每次重试乘以尝试次数
        exceptions: 需要重试的异常类型
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        wait_time = backoff * attempt
                        retry_logger.warning(
                            f"{func.__name__} 第 {attempt} 次失败: {e}，"
                            f"{wait_time:.1f}s 后重试..."
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        retry_logger.error(
                            f"{func.__name__} 重试 {max_attempts} 次后仍失败: {e}"
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
