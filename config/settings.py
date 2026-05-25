"""全局配置，从 .env 读取。"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """全局配置，从 .env 读取"""

    # LLM 配置
    openai_api_key: str = Field(default="sk-demo-key", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    llm_model: str = Field(default="gpt-4o", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.7)

    # Mock 服务配置
    mock_failure_rate: float = Field(default=0.15)
    mock_min_latency: float = Field(default=0.2)
    mock_max_latency: float = Field(default=1.0)
    mock_timeout: float = Field(default=2.0)

    # 数据路径
    data_dir: str = Field(default="data")
    preferences_path: str = Field(default="data/runtime/preferences.json")

    # 日志
    log_level: str = Field(default="INFO")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
