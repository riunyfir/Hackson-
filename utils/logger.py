"""日志模块，使用 rich 格式化输出。"""
import logging
from rich.logging import RichHandler


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """创建带 rich 格式化的 logger"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_path=False,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    return logger


# 全局 logger
main_logger = setup_logger("Main")


def setup_global_logger(level: str = "INFO"):
    """初始化全局日志配置"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_time=True, show_path=False)],
    )


# 为每个 Agent 创建独立 logger
planner_logger = setup_logger("Planner")
searcher_logger = setup_logger("Searcher")
executor_logger = setup_logger("Executor")
memory_logger = setup_logger("Memory")
orchestrator_logger = setup_logger("Orchestrator")
