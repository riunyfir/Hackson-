"""Agent 间消息协议定义。所有字段必须完整定义，不可省略。"""
from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


# ============================================================
# 枚举类型
# ============================================================

ServiceType = Literal["restaurant", "activity", "weather", "flower", "messenger"]
SearchStatus = Literal["full", "partial", "failed"]
SceneType = Literal["family", "friends", "couple", "solo"]


# ============================================================
# Planner Agent 消息
# ============================================================

class ParsedIntent(BaseModel):
    """Planner 解析用户输入后的结构化意图"""
    scene: SceneType = Field(description="场景类型")
    people_count: int = Field(description="参与人数")
    duration_hours: int = Field(description="期望时长（小时）")
    max_distance_km: int = Field(description="最大距离（公里），默认10")
    start_time: str = Field(description="出发时间，如 '14:00'")
    constraints: list[str] = Field(default_factory=list, description="特殊约束，如 'child_age_5' 'diet_light' 'indoor_preferred'")
    budget_level: Literal["low", "medium", "high"] = Field(default="medium")


class SearchQuery(BaseModel):
    """单条搜索请求"""
    service: ServiceType
    params: dict = Field(description="搜索参数，如 {'tags': ['kid_friendly'], 'distance_km': 10}")
    fallback_tags: list[str] = Field(default_factory=list, description="降级标签")


class SearchRequest(BaseModel):
    """Planner → Searcher：搜索请求"""
    task_id: str = Field(description="任务唯一标识")
    queries: list[SearchQuery] = Field(description="并发搜索项，通常 4-5 条")
    preference_weights: dict = Field(default_factory=dict, description="偏好权重，如 {'kid_friendly': 1.5, 'spicy': 0.3}")


# ============================================================
# Searcher Agent 消息
# ============================================================

class ServiceCandidate(BaseModel):
    """单个候选结果"""
    id: str = Field(description="唯一标识")
    name: str = Field(description="名称")
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    price_level: Literal["low", "medium", "high"] = "medium"
    price_amount: float = Field(default=0.0, description="人均价格（元）")
    distance_km: float = Field(default=0.0)
    availability: bool = Field(default=True)
    available_slots: list[str] = Field(default_factory=list, description="可用时段")
    location: str = Field(default="")
    extra: dict = Field(default_factory=dict, description="服务特定字段")


class ServiceResult(BaseModel):
    """单个服务的搜索结果"""
    service: ServiceType
    candidates: list[ServiceCandidate] = Field(default_factory=list)
    status: Literal["success", "timeout", "failed"]
    fallback_used: bool = Field(default=False)
    error_message: str = Field(default="")


class SearchResult(BaseModel):
    """Searcher → Planner：搜索结果"""
    task_id: str
    results: list[ServiceResult] = Field(default_factory=list)
    overall_status: SearchStatus


# ============================================================
# Planner Agent → 用户（方案展示）
# ============================================================

class TimelineSlot(BaseModel):
    """时间线上的一个环节"""
    time_range: str = Field(description="如 '14:00-15:30'")
    activity_name: str
    location: str
    action_type: Literal["activity", "dining", "shopping", "transport", "other"]
    action_required: bool = Field(default=False, description="是否需要预订/购票")
    notes: str = Field(default="")


class Plan(BaseModel):
    """单个可选方案"""
    plan_id: str = Field(description="方案唯一标识")
    title: str = Field(description="方案标题，如 '亲子轻食半日游'")
    summary: str = Field(description="一句话摘要")
    timeline: list[TimelineSlot]
    total_budget: str = Field(description="预估总花费描述")
    highlights: list[str] = Field(default_factory=list, description="亮点")
    risk_notes: list[str] = Field(default_factory=list, description="风险提示")


class PlanSet(BaseModel):
    """Planner 展示给用户的方案集合（2-3 个）"""
    plans: list[Plan]
    recommendation: str = Field(description="推荐理由")


# ============================================================
# Executor Agent 消息
# ============================================================

class BookingAction(BaseModel):
    """单个执行动作"""
    action_id: str
    service: ServiceType
    action_type: Literal["reserve", "order", "send_message"]
    target_name: str = Field(description="餐厅名/活动名/收件人")
    payload: dict = Field(description="预订/下单参数")
    fallback_target: str = Field(default="")
    fallback_payload: dict = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    """Planner → Executor：执行计划"""
    plan_id: str
    summary: str = Field(description="自然语言摘要")
    timeline: list[TimelineSlot]
    bookings: list[BookingAction]
    final_message: str = Field(description="发给小张/老婆的消息文本")


class ExecutionResult(BaseModel):
    """Executor → Orchestrator：执行结果"""
    plan_id: str
    success_count: int
    failed_count: int
    results: list[dict] = Field(description="每项操作的执行状态")
    final_message: str
    status: Literal["all_success", "partial_success", "all_failed"]


# ============================================================
# Memory Agent 消息
# ============================================================

class PreferenceRecord(BaseModel):
    """单次偏好记录"""
    scenario_tags: list[str] = Field(description="场景标签")
    chosen_restaurant_tags: list[str] = Field(default_factory=list)
    chosen_activity_tags: list[str] = Field(default_factory=list)
    rejected_items: list[str] = Field(default_factory=list, description="用户拒绝的项目名")
    budget_level: str = Field(default="medium")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class PreferenceQueryResult(BaseModel):
    """Memory Agent → Planner：偏好查询结果"""
    matched: bool = Field(default=False, description="是否匹配到历史偏好")
    weights: dict = Field(default_factory=dict, description="标签权重")
    preferred_tags: list[str] = Field(default_factory=list)
    rejected_tags: list[str] = Field(default_factory=list)
    last_scenario: Optional[PreferenceRecord] = None
