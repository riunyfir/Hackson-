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
BudgetCategory = Literal["activity", "dining", "transport", "other"]


# ============================================================
# Planner Agent 消息
# ============================================================

class ParsedIntent(BaseModel):
    """Planner 解析用户输入后的结构化意图"""
    scene: SceneType = Field(description="场景类型")
    people_count: int = Field(description="参与人数")
    duration_hours: int = Field(description="期望时长（小时）", default=4)
    max_distance_km: int = Field(description="最大距离（公里）", default=10)
    start_time: str = Field(description="出发时间，如 '14:00'")
    constraints: list[str] = Field(default_factory=list, description="如 'child_age_5' 'indoor_preferred'")
    budget_level: Literal["low", "medium", "high"] = Field(default="medium")
    user_location: str = Field(default="", description="用户坐标，如 '116.443239,39.921469'")
    user_address: str = Field(default="", description="用户可读地址")


class SearchQuery(BaseModel):
    """单条搜索请求"""
    service: ServiceType
    params: dict = Field(default_factory=dict)
    fallback_tags: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Planner → Searcher：搜索请求"""
    task_id: str
    queries: list[SearchQuery] = Field(default_factory=list)
    preference_weights: dict = Field(default_factory=dict)


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
    price_amount: float = Field(default=0.0)
    distance_km: float = Field(default=0.0)
    availability: bool = Field(default=True)
    available_slots: list[str] = Field(default_factory=list)
    location: str = Field(default="")
    full_address: str = Field(default="", description="高德返回的完整地址")
    latitude: float = Field(default=0.0)
    longitude: float = Field(default=0.0)
    extra: dict = Field(default_factory=dict)


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
# 方案描述子模型（新增）
# ============================================================

class WeatherContext(BaseModel):
    """天气上下文"""
    condition: str = Field(default="", description="如 '晴' / '多云' / '小雨'")
    temperature: str = Field(default="", description="如 '18°C ~ 24°C'")
    advice: str = Field(default="", description="如 '建议带伞' / '适合户外活动'")
    impact: str = Field(default="", description="天气对方案的影响说明")


class BudgetItem(BaseModel):
    """单个预算项"""
    name: str = Field(description="项目名，如 '亲子乐园门票'")
    category: BudgetCategory = Field(default="activity")
    unit_price: float = Field(default=0.0)
    quantity: int = Field(default=1)
    subtotal: float = Field(default=0.0)
    note: str = Field(default="", description="如 '成人80元×2 + 儿童40元×1'")


class ContingencyPlan(BaseModel):
    """应急预案"""
    trigger: str = Field(default="", description="触发条件，如 '目标餐厅满座'")
    fallback_name: str = Field(default="")
    fallback_location: str = Field(default="")
    note: str = Field(default="")


class SlotDetail(BaseModel):
    """TimelineSlot 的详细描述"""
    reason: str = Field(default="", description="推荐理由")
    candidates: list[str] = Field(default_factory=list, description="其他候选名称")
    transport: str = Field(default="", description="环节间交通，如 '步行8分钟(600m)'")
    transport_from_user: str = Field(default="", description="从用户位置出发的交通")
    distance_from_user: str = Field(default="", description="距用户距离，如 '600m'")
    prep_note: str = Field(default="")
    contingency: Optional[ContingencyPlan] = None


# ============================================================
# Planner Agent → 用户（方案展示）
# ============================================================

class TimelineSlot(BaseModel):
    """时间线上的一个环节"""
    time_range: str = Field(description="如 '14:00-15:30'")
    activity_name: str
    location: str = Field(default="", description="完整地址")
    action_type: Literal["activity", "dining", "shopping", "transport", "other"]
    action_required: bool = Field(default=False)
    notes: str = Field(default="")
    detail: Optional[SlotDetail] = None


class Plan(BaseModel):
    """单个可选方案"""
    plan_id: str
    title: str
    summary: str = Field(default="", description="2-3 句概述")
    scenario_match: str = Field(default="", description="场景适配度说明")
    style_tags: list[str] = Field(default_factory=list)
    weather_context: WeatherContext = Field(default_factory=WeatherContext)
    timeline: list[TimelineSlot] = Field(default_factory=list)
    budget_items: list[BudgetItem] = Field(default_factory=list)
    total_budget: float = Field(default=0.0, description="代码自动计算")
    highlights: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    contingency_overall: str = Field(default="")


class PlanSet(BaseModel):
    """Planner 展示给用户的方案集合（2-3 个）"""
    plans: list[Plan] = Field(default_factory=list)
    recommendation: str = Field(default="")
    user_address: str = Field(default="")


# ============================================================
# Executor Agent 消息
# ============================================================

class BookingAction(BaseModel):
    """单个执行动作"""
    action_id: str
    service: ServiceType
    action_type: Literal["reserve", "order", "send_message"]
    target_name: str
    payload: dict = Field(default_factory=dict)
    fallback_target: str = Field(default="")
    fallback_payload: dict = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    """Planner → Executor：执行计划"""
    plan_id: str
    summary: str
    timeline: list[TimelineSlot] = Field(default_factory=list)
    bookings: list[BookingAction] = Field(default_factory=list)
    final_message: str = Field(default="")


class ExecutionResult(BaseModel):
    """Executor → Orchestrator：执行结果"""
    plan_id: str
    success_count: int = 0
    failed_count: int = 0
    results: list[dict] = Field(default_factory=list)
    final_message: str = Field(default="")
    status: Literal["all_success", "partial_success", "all_failed"]


# ============================================================
# Memory Agent 消息
# ============================================================

class PreferenceRecord(BaseModel):
    """单次偏好记录"""
    scenario_tags: list[str] = Field(default_factory=list)
    chosen_restaurant_tags: list[str] = Field(default_factory=list)
    chosen_activity_tags: list[str] = Field(default_factory=list)
    rejected_items: list[str] = Field(default_factory=list)
    budget_level: str = Field(default="medium")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class PreferenceQueryResult(BaseModel):
    """Memory Agent → Planner：偏好查询结果"""
    matched: bool = Field(default=False)
    weights: dict = Field(default_factory=dict)
    preferred_tags: list[str] = Field(default_factory=list)
    rejected_tags: list[str] = Field(default_factory=list)
    last_scenario: Optional[PreferenceRecord] = None