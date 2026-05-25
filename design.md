# 本地场景短时活动规划与执行 Agent — 详细设计文档

> 本文档面向 AI 代码生成器（Claude/GPT），设计详细程度为 **可直接生成完整可运行代码**。

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [消息协议定义](#3-消息协议定义)
4. [Agent 详细设计](#4-agent-详细设计)
5. [Mock Service 详细设计](#5-mock-service-详细设计)
6. [Mock 数据集设计](#6-mock-数据集设计)
7. [配置与工具模块](#7-配置与工具模块)
8. [异常处理策略](#8-异常处理策略)
9. [项目目录结构](#9-项目目录结构)
10. [开发 Issue 拆解](#10-开发-issue-拆解)
11. [实现顺序与依赖关系](#11-实现顺序与依赖关系)
12. [CLI 交互流程示例](#12-cli-交互流程示例)

---

## 1. 项目概述

### 1.1 业务场景

周六上午 9 点，小明给美团发消息：

> "今天下午是空的，想和老婆孩子 / 朋友出去玩几个小时，别离家太远，帮我安排一下。"

美团应在几分钟内：

- 规划「下午 4-6 小时」综合方案（去哪玩 → 玩完去哪吃 → 额外活动）
- 查到适合群体需求的餐厅及空位情况
- 安排吃饭前后的活动
- 用户确认后一键完成下单 / 预约 / 配送
- 生成可分享的计划消息

### 1.2 技术目标

构建一个 **Multi-Agent 短时活动规划与执行系统**，接受自然语言输入，通过 4 个协作 Agent 完成搜索 → 规划 → 确认 → 执行的全流程。

### 1.3 交付物

| 交付物 | 说明 |
|--------|------|
| 完整 Tool 实现代码 | Python 项目，含 Mock API 调用 |
| 设计文档 | 即本文档 |
| CLI Demo | 命令行交互，`make demo` 一键跑通预设场景 |

### 1.4 技术栈

| 层面 | 选型 | 版本 |
|------|------|------|
| 语言 | Python | 3.11+ |
| Agent 框架 | LangChain（仅 Tool 封装，不用 AgentExecutor） | langchain >= 0.3.0, langchain-core >= 0.3.0 |
| LLM 接口 | langchain-openai（兼容接口，可配置任意端点） | langchain-openai >= 0.2.0 |
| 数据模型 | Pydantic v2 | pydantic >= 2.0 |
| 异步 | asyncio（标准库） + asyncio.gather | — |
| 配置 | python-dotenv + pydantic-settings | — |
| CLI 输出美化 | rich | >= 13.0 |
| 测试 | pytest + pytest-asyncio | — |

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                   CLI 入口 (main.py)                      │
│  输入缓冲区足够大，容纳完整自然语言需求                      │
│  如："今天下午想带老婆和5岁孩子出去玩4小时，别离家太远"      │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Orchestrator（编排器）                                    │
│  - 串起执行流程：Planner → Searcher → Planner → Executor   │
│  - 在 Planner 和 Executor 阶段挂起等待用户输入               │
│  - 管理全局上下文，在 Agent 间透传                           │
└──────┬──────────┬──────────┬──────────┬──────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
┌───────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Planner  │ │ Searcher │ │ Executor │ │ Memory   │
│   Agent   │ │  Agent   │ │  Agent   │ │  Agent   │
│           │ │          │ │          │ │          │
│ 意图解析  │ │ 并发搜索 │ │ Pre-exec │ │ 偏好记忆 │
│ 方案整合  │ │ 结果排序 │ │ 确认循环 │ │ 持久化   │
│ 用户确认  │ │ 降级处理 │ │ 批量执行 │ │ 检索推荐 │
└───────────┘ └────┬─────┘ └──────────┘ └────┬─────┘
                   │                          │
                   ▼                          │
    ┌──────────────────────────────┐          │
    │     Mock Service Layer       │          │
    │  ┌────────┐ ┌──────┐ ┌────┐ │          │
    │  │ 餐厅   │ │ 活动 │ │天气│ │          │
    │  │ 搜索   │ │ 搜索 │ │查询│ │          │
    │  │ +订座  │ │ +购票│ │    │ │          │
    │  └────────┘ └──────┘ └────┘ │          │
    │  ┌────────┐ ┌──────────────┐ │          │
    │  │ 鲜花   │ │  消息发送     │ │          │
    │  │ 配送   │ │              │ │          │
    │  └────────┘ └──────────────┘ │          │
    └──────────────────────────────┘          │
                                              │
                                    ┌─────────────────┐
                                    │ 偏好存储        │
                                    │ (JSON 文件)     │
                                    │ data/runtime/   │
                                    │ preferences.json│
                                    └─────────────────┘
```

### 2.1 关键设计约束

1. **Agent 间无共享状态**：所有通信通过 Pydantic 消息模型，Orchestrator 负责透传
2. **Orchestrator 无业务逻辑**：只做调度和用户交互，不参与规划/搜索/执行决策
3. **用户确认中断点**：Planner 展示方案后、Executor 执行前，两次挂起等待用户输入
4. **Executor 的 Pre-execution Loop**：用户可反复提修改意见，Executor 评估反思后调整，直到用户确认才执行
5. **Memory Agent 被动调用**：Planner 开始时查询偏好、Executor 完成后记录偏好

---

## 3. 消息协议定义

文件：`models/messages.py`

所有 Agent 间通信使用 Pydantic BaseModel，确保类型安全。

### 3.1 完整代码定义

```python
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
```

---

## 4. Agent 详细设计

### 4.1 Planner Agent

文件：`agents/planner.py`

#### 4.1.1 职责

1. 解析用户自然语言输入，提取场景类型、人数、时长、约束
2. 查询 Memory Agent 获取历史偏好
3. 生成 SearchRequest 发送给 Searcher
4. 接收 SearchResult，整合为 2-3 个可选方案
5. 展示方案，等待用户选择
6. 用户选择后，生成 ExecutionPlan 交给 Executor

#### 4.1.2 核心方法签名

```python
class PlannerAgent:
    def __init__(self, llm, memory_agent: "MemoryAgent"):
        """
        llm: langchain 的 ChatOpenAI 实例
        memory_agent: MemoryAgent 实例，用于偏好查询
        """

    async def parse_intent(self, user_input: str) -> ParsedIntent:
        """
        调用 LLM 解析用户输入，返回结构化意图。
        Prompt 模板：
        '''你是一个活动规划意图解析器。根据用户输入提取以下信息（JSON 格式）：
        {{
            "scene": "family" / "friends" / "couple" / "solo",
            "people_count": 数字,
            "duration_hours": 数字（默认4）,
            "max_distance_km": 数字（默认10）,
            "start_time": "HH:MM"（默认"14:00"）,
            "constraints": ["child_age_5", "diet_light", ...],
            "budget_level": "low" / "medium" / "high"
        }}
        约束标签规则：
        - 提到孩子年龄 → "child_age_N"
        - 提到减肥/轻食 → "diet_light"
        - 提到室内/下雨 → "indoor_preferred"
        - 提到省钱/便宜 → "budget_low"
        - 提到庆祝/纪念日 → "celebration"
        用户输入：{user_input}'''
        """

    async def generate_plan_set(
        self, intent: ParsedIntent, search_result: SearchResult, preferences: PreferenceQueryResult
    ) -> PlanSet:
        """
        调用 LLM 根据搜索结果和偏好生成 2-3 个可选方案。
        生成规则：
        - 方案1：最匹配偏好的方案（权重最高）
        - 方案2：备选方案（替换部分活动/餐厅）
        - 方案3（可选）：极端天气/夜间特殊方案

        每个 Plan 必须包含：
        - plan_id: 唯一标识
        - title: 方案标题
        - summary: 一句话摘要
        - timeline: 按时间顺序排列的 TimelineSlot 列表，总时长 ≤ intent.duration_hours
        - total_budget: 总花费（活动+餐饮+配送）
        - highlights: 亮点列表
        - risk_notes: 风险提示

        Prompt 模板：
        '''你是一个活动规划师。用户意图：{intent}，搜索结果：{search_result}，历史偏好：{preferences}。
        请生成 2-3 个下午活动方案，每个方案包含时间线、预估花费和风险提示。JSON 输出格式：
        {{ "plans": [ ... ], "recommendation": "推荐理由" }}'''
        """

    async def create_execution_plan(self, chosen_plan: Plan) -> ExecutionPlan:
        """
        将用户选中的 Plan 转化为可执行的 ExecutionPlan。
        对每个 action_required=True 的 TimelineSlot 生成 BookingAction：
        - activity → BookingAction(service="activity", action_type="order")
        - dining → BookingAction(service="restaurant", action_type="reserve")
        对鲜花/蛋糕配送，如果 intent.constraints 包含 "celebration"，添加：
        - BookingAction(service="flower", action_type="order")
        生成 final_message：发给小张/老婆的分享消息文本。
        """

    async def run(self, user_input: str) -> tuple[PlanSet, ExecutionPlan | None]:
        """
        主流程：
        1. parse_intent(user_input)
        2. 查询 memory_agent
        3. 生成 SearchRequest
        4. 返回 (None, search_request) → Orchestrator 调用 Searcher
        5. Orchestrator 将 search_result 传入后，调用 generate_plan_set
        6. 展示 PlanSet → 等待用户选择
        7. 用户选择后调用 create_execution_plan → 返回 ExecutionPlan
        注意：步骤 4-5 由 Orchestrator 协调，Planner 本身分两次调用完成。
        """
```

#### 4.1.3 Planner 第一次调用：生成 SearchRequest

```python
async def stage1_plan_search(self, user_input: str) -> tuple[ParsedIntent, SearchRequest]:
    """阶段1：解析意图 + 查询偏好 + 生成搜索请求"""
    intent = await self.parse_intent(user_input)
    preferences = await self.memory_agent.query(intent)

    queries = [
        SearchQuery(
            service="restaurant",
            params={
                "tags": self._get_restaurant_tags(intent, preferences),
                "distance_km": intent.max_distance_km,
                "people_count": intent.people_count,
            },
            fallback_tags=["casual_dining"],
        ),
        SearchQuery(
            service="activity",
            params={
                "tags": self._get_activity_tags(intent, preferences),
                "distance_km": intent.max_distance_km,
                "duration_hours": intent.duration_hours // 2,
                "people_count": intent.people_count,
            },
            fallback_tags=["park", "mall"],
        ),
        SearchQuery(
            service="weather",
            params={"time": "afternoon"},
            fallback_tags=[],
        ),
    ]

    # 如果有庆祝标签，添加鲜花搜索
    if "celebration" in intent.constraints:
        queries.append(SearchQuery(
            service="flower",
            params={"occasion": "celebration"},
            fallback_tags=["bouquet"],
        ))

    request = SearchRequest(
        task_id=f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        queries=queries,
        preference_weights=preferences.weights,
    )

    return intent, request

def _get_restaurant_tags(self, intent: ParsedIntent, pref: PreferenceQueryResult) -> list[str]:
    """根据场景和偏好生成餐厅搜索标签"""
    tags = []
    if intent.scene == "family":
        tags.extend(["kid_friendly", "family_style"])
        if "child_age_5" in intent.constraints:
            tags.append("kids_menu")
    elif intent.scene == "friends":
        tags.extend(["group_dining", "social"])

    if "diet_light" in intent.constraints:
        tags.append("healthy")
    if pref.preferred_tags:
        tags.extend(pref.preferred_tags)
    # 排除被拒绝的标签
    tags = [t for t in tags if t not in pref.rejected_tags]
    return tags

def _get_activity_tags(self, intent: ParsedIntent, pref: PreferenceQueryResult) -> list[str]:
    """根据场景和偏好生成活动搜索标签"""
    tags = []
    if intent.scene == "family":
        tags.extend(["kids_playground", "family_friendly"])
    elif intent.scene == "friends":
        tags.extend(["exhibition", "interactive", "group_activity"])

    # 天气影响
    if "indoor_preferred" in intent.constraints:
        tags = [t for t in tags if "outdoor" not in t]
        tags.append("indoor")

    if pref.preferred_tags:
        tags.extend(pref.preferred_tags)
    tags = [t for t in tags if t not in pref.rejected_tags]
    return tags
```

#### 4.1.4 Planner 第二次调用：整合方案

```python
async def stage2_generate_plans(
    self, intent: ParsedIntent, search_result: SearchResult
) -> PlanSet:
    """阶段2：根据搜索结果生成可选方案"""
    # 如果全部失败，生成降级方案
    if search_result.overall_status == "failed":
        return self._generate_fallback_plan_set(intent)

    # 使用 LLM 生成方案
    plan_set = await self.generate_plan_set(intent, search_result, ...)

    # 后处理：确保时间不冲突、距离不超
    plan_set = self._validate_plan_set(plan_set, intent)
    return plan_set

def _validate_plan_set(self, plan_set: PlanSet, intent: ParsedIntent) -> PlanSet:
    """校验方案集的合理性"""
    for plan in plan_set.plans:
        # 检查总时长
        total_minutes = sum(self._parse_time_range(slot.time_range) for slot in plan.timeline)
        if total_minutes > intent.duration_hours * 60 * 1.1:  # 允许 10% 弹性
            plan.risk_notes.append("时间可能较紧张")
    return plan_set

def _generate_fallback_plan_set(self, intent: ParsedIntent) -> PlanSet:
    """当全部搜索失败时，生成纯文本建议方案"""
    # 使用预置 fallback 数据
    ...
```

---

### 4.2 Searcher Agent

文件：`agents/searcher.py`

#### 4.2.1 职责

1. 接收 SearchRequest，并发调用 5 个 Mock Service
2. 处理各服务的超时/失败，执行降级
3. 按偏好权重对结果排序
4. 返回 SearchResult

#### 4.2.2 核心实现

```python
class SearcherAgent:
    def __init__(self):
        """
        初始化所有 Mock Service 实例：
        self.services = {
            "restaurant": RestaurantService(),
            "activity": ActivityService(),
            "weather": WeatherService(),
            "flower": FlowerService(),
            "messenger": MessengerService(),
        }
        """

    async def search(self, request: SearchRequest) -> SearchResult:
        """
        主入口：并发执行所有搜索
        """
        tasks = []
        for query in request.queries:
            service = self.services[query.service]
            tasks.append(self._search_with_fallback(
                service, query, request.preference_weights
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        service_results = []
        for i, result in enumerate(results):
            query = request.queries[i]
            if isinstance(result, Exception):
                service_results.append(ServiceResult(
                    service=query.service,
                    candidates=[],
                    status="failed",
                    error_message=str(result),
                ))
            else:
                service_results.append(result)

        # 判断整体状态
        success_count = sum(1 for r in service_results if r.status == "success")
        if success_count == len(service_results):
            overall = "full"
        elif success_count == 0:
            overall = "failed"
        else:
            overall = "partial"

        return SearchResult(
            task_id=request.task_id,
            results=service_results,
            overall_status=overall,
        )

    async def _search_with_fallback(
        self, service: "MockService", query: SearchQuery, weights: dict
    ) -> ServiceResult:
        """
        调用单个服务，带降级逻辑：
        1. 尝试主搜索（query.params）
        2. 失败或超时 → 尝试 fallback_tags
        3. 仍失败 → 返回 status="failed"
        """
        try:
            result = await service.call(query.params, timeout=2.0)
            candidates = self._parse_and_rank(result, weights)
            return ServiceResult(
                service=query.service,
                candidates=candidates,
                status="success",
            )
        except TimeoutError:
            # 尝试降级
            if query.fallback_tags:
                try:
                    fallback_params = {**query.params, "tags": query.fallback_tags}
                    result = await service.call(fallback_params, timeout=2.0)
                    candidates = self._parse_and_rank(result, weights)
                    return ServiceResult(
                        service=query.service,
                        candidates=candidates,
                        status="success",
                        fallback_used=True,
                    )
                except Exception:
                    pass
            return ServiceResult(
                service=query.service,
                candidates=[],
                status="timeout",
                error_message="Service timeout",
            )
        except Exception as e:
            return ServiceResult(
                service=query.service,
                candidates=[],
                status="failed",
                error_message=str(e),
            )

    def _parse_and_rank(self, raw_result: dict, weights: dict) -> list[ServiceCandidate]:
        """
        将原始结果解析为 ServiceCandidate 列表，按偏好权重排序。
        排序公式：score = sum(tag_weight for tag in candidate.tags if tag in weights)
        权重缺失的标签默认 weight=1.0
        """
        candidates = [ServiceCandidate(**item) for item in raw_result.get("items", [])]
        for c in candidates:
            c.score = sum(weights.get(t, 1.0) for t in c.tags)
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[:5]  # 最多返回 5 个候选
```

---

### 4.3 Executor Agent

文件：`agents/executor.py`

#### 4.3.1 职责

1. 接收 ExecutionPlan，展示执行计划给用户
2. **Pre-execution Loop**：反复接受用户反馈，评估调整，直到用户确认
3. 批量执行所有 BookingAction
4. 处理执行中的失败和降级
5. 返回 ExecutionResult

#### 4.3.2 Pre-execution Loop 详细流程

```
Executor 收到 ExecutionPlan
        │
        ▼
┌─────────────────────────────────────┐
│  展示执行计划（格式化的清单）         │
│  等待用户反馈                        │
└─────────────────────────────────────┘
        │
        ├── 用户确认（"确认"/"没问题"）──→ 退出循环，进入执行阶段
        │
        └── 用户提意见（"太早了"/"换个餐厅"/"不要鲜花"）──→
                │
                ▼
        ┌─────────────────────────────────────┐
        │  Executor 评估反思：                  │
        │  1. 解析用户意见类型（时间/地点/项目） │
        │  2. 判断是否可本地调整                │
        │     - 可调整：直接修改 ExecutionPlan   │
        │     - 需重新搜索：标记，准备新搜索请求  │
        │  3. 生成调整后的执行计划               │
        └─────────────────────────────────────┘
                │
                ▼
        展示调整后的计划 → 等待用户反馈（循环）
```

#### 4.3.3 核心方法签名

```python
class ExecutorAgent:
    def __init__(self, services: dict[str, "MockService"], messenger: "MessengerService"):
        self.services = services
        self.messenger = messenger
        self.max_adjustment_rounds = 5  # 最多调整 5 轮

    async def run(self, plan: ExecutionPlan) -> ExecutionResult:
        """
        主流程：
        1. 进入 pre_execution_loop，反复确认直到用户满意
        2. 批量执行最终确认的计划
        3. 返回 ExecutionResult
        """

    async def pre_execution_loop(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        确认循环，对外通过 Orchestrator 与用户交互。
        每轮返回 (adjusted_plan, needs_user_input, user_prompt)。

        用户意见分类处理：
        ┌──────────────────┬──────────────────────────┐
        │ 用户意见          │ 处理方式                   │
        ├──────────────────┼──────────────────────────┤
        │ "太早了/太晚了"    │ 整体偏移时间线              │
        │ "换个餐厅"        │ 替换 restaurant 的 Booking │
        │ "不想去XX活动"    │ 移除对应 Booking，补空缺    │
        │ "不要鲜花了"      │ 移除配送 Booking            │
        │ "多加一个人"      │ 更新 people_count，          │
        │                    │ 重新检查餐厅容量            │
        │ "换个便宜点的"    │ 过滤 high price_level 选项  │
        │ "确认"/"没问题"   │ 退出循环，返回最终 plan      │
        └──────────────────┴──────────────────────────┘
        """
        round_count = 0
        while round_count < self.max_adjustment_rounds:
            # 展示当前计划 → 等待用户输入
            # 解析用户意见 → 调整计划
            # 如果用户确认 → break
            round_count += 1
        return plan

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """
        批量执行所有 BookingAction。
        并发执行，对单个失败标记错误但不阻断其他项。
        """

    def adjust_time(self, plan: ExecutionPlan, new_start_time: str) -> ExecutionPlan:
        """偏移所有时间线 slot 到新起始时间"""

    def replace_booking(self, plan: ExecutionPlan, action_id: str, new_target: str) -> ExecutionPlan:
        """替换指定预订项"""

    def remove_booking(self, plan: ExecutionPlan, action_id: str) -> ExecutionPlan:
        """移除指定预订项"""

    def reflect_and_adjust(self, plan: ExecutionPlan, user_feedback: str) -> tuple[ExecutionPlan, str]:
        """
        使用 LLM 评估用户反馈，决定调整策略。
        返回 (adjusted_plan, explanation)。

        Prompt 模板：
        '''你是一个执行计划调整器。当前计划：{plan}，用户反馈：{user_feedback}。
        请判断用户意图属于以下哪种类型，并给出调整后的计划（JSON）：
        - "confirm": 用户确认，无需调整
        - "change_time": 用户想改时间，调整为 {new_start_time}
        - "replace": 用户想换某个项目，替换为备选
        - "remove": 用户想取消某个项目
        - "add_people": 用户想增加人数
        - "change_budget": 用户想调整预算
        返回：{{"type": "confirm"|"change_time"|... "adjusted_plan": ...}} '''
        """
```

#### 4.3.4 执行阶段详细实现

```python
async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
    """批量执行所有预订动作"""
    tasks = []
    for booking in plan.bookings:
        tasks.append(self._execute_booking(booking))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = 0
    failed_count = 0
    detailed_results = []

    for i, result in enumerate(results):
        booking = plan.bookings[i]
        if isinstance(result, Exception):
            failed_count += 1
            detailed_results.append({
                "action_id": booking.action_id,
                "service": booking.service,
                "target": booking.target_name,
                "status": "failed",
                "error": str(result),
            })
        else:
            success_count += 1
            detailed_results.append({
                "action_id": booking.action_id,
                "service": booking.service,
                "target": booking.target_name,
                "status": "success",
                "confirmation": result,
            })

    # 发送最终消息（始终执行，无论预订是否全部成功）
    await self.messenger.send(plan.final_message)

    if failed_count == 0:
        overall_status = "all_success"
    elif success_count == 0:
        overall_status = "all_failed"
    else:
        overall_status = "partial_success"

    return ExecutionResult(
        plan_id=plan.plan_id,
        success_count=success_count,
        failed_count=failed_count,
        results=detailed_results,
        final_message=plan.final_message,
        status=overall_status,
    )

async def _execute_booking(self, booking: BookingAction) -> dict:
    """执行单个预订"""
    service = self.services[booking.service]

    try:
        result = await service.call(booking.payload, timeout=3.0)
        return result
    except Exception:
        # 尝试 fallback
        if booking.fallback_target:
            try:
                fallback_result = await service.call(booking.fallback_payload, timeout=3.0)
                return {"status": "fallback_used", "result": fallback_result}
            except Exception as e:
                raise e
        raise
```

---

### 4.4 Memory Agent

文件：`agents/memory.py`

#### 4.4.1 职责

1. 查询历史偏好（Planner 阶段开始前）
2. 记录本次选择（Executor 完成后）
3. 本地 JSON 持久化，无外部依赖

#### 4.4.2 核心实现

```python
class MemoryAgent:
    def __init__(self, storage_path: str = "data/runtime/preferences.json"):
        self.storage_path = storage_path
        self._ensure_storage()

    def _ensure_storage(self):
        """确保存储文件存在，不存在则创建空文件"""
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text('{"records": []}', encoding="utf-8")

    async def query(self, intent: ParsedIntent) -> PreferenceQueryResult:
        """
        根据意图查询匹配的历史偏好。
        匹配逻辑：
        1. 读取所有历史记录
        2. 按场景标签匹配（scene 相同）
        3. 按参与人数匹配（±2 人范围内）
        4. 如果匹配到，聚合标签权重：
           - 选择的标签 +1.0
           - 拒绝的标签归零
        """
        try:
            data = json.loads(Path(self.storage_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            # 文件损坏或不存在 → 降级为空偏好
            return PreferenceQueryResult(matched=False)

        records = [PreferenceRecord(**r) for r in data.get("records", [])]

        # 匹配规则
        matched = []
        for r in records:
            if intent.scene in r.scenario_tags:
                matched.append(r)

        if not matched:
            return PreferenceQueryResult(matched=False)

        # 聚合权重
        weights = {}
        preferred = set()
        rejected = set()
        for r in matched[-5:]:  # 最近 5 条
            for tag in r.chosen_restaurant_tags + r.chosen_activity_tags:
                weights[tag] = weights.get(tag, 1.0) + 0.5
                preferred.add(tag)
            for item in r.rejected_items:
                rejected.add(item)

        return PreferenceQueryResult(
            matched=True,
            weights=weights,
            preferred_tags=list(preferred),
            rejected_tags=list(rejected),
            last_scenario=matched[-1] if matched else None,
        )

    async def record(self, plan: ExecutionPlan, rejected_items: list[str] | None = None):
        """
        记录本次选择：
        - 从 ExecutionPlan 提取选择的餐厅标签、活动标签
        - 从 rejected_items 提取拒绝的项目
        - 追加到 JSON 文件，保留最近 50 条
        """
        # 提取标签
        restaurant_tags = []
        activity_tags = []
        for booking in plan.bookings:
            if booking.service == "restaurant":
                # 从 payload 中提取 tags
                restaurant_tags.extend(booking.payload.get("tags", []))
            elif booking.service == "activity":
                activity_tags.extend(booking.payload.get("tags", []))

        record = PreferenceRecord(
            scenario_tags=[],  # 由 Planner 传入的场景标签
            chosen_restaurant_tags=restaurant_tags,
            chosen_activity_tags=activity_tags,
            rejected_items=rejected_items or [],
            budget_level="medium",
        )

        # 读写文件（线程安全通过 asyncio.to_thread）
        data = json.loads(Path(self.storage_path).read_text(encoding="utf-8"))
        data["records"].append(record.model_dump())
        # 保留最近 50 条
        data["records"] = data["records"][-50:]
        Path(self.storage_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

---

## 5. Mock Service 详细设计

### 5.1 基类

文件：`mock_services/base.py`

```python
import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any


class ServiceTimeoutError(Exception):
    """服务超时异常"""
    pass


class ServiceUnavailableError(Exception):
    """服务不可用异常"""
    pass


class MockService(ABC):
    """所有 Mock 服务的基类"""

    def __init__(
        self,
        name: str,
        latency_range: tuple[float, float] = (0.2, 1.0),
        failure_rate: float = 0.15,
        timeout: float = 2.0,
        data_file: str | None = None,
    ):
        self.name = name
        self.latency_min, self.latency_max = latency_range
        self.failure_rate = failure_rate
        self.timeout = timeout
        self.data: list[dict] = []
        if data_file:
            self._load_data(data_file)

    def _load_data(self, filepath: str):
        """从 JSON 文件加载预置数据集"""
        import json
        with open(filepath, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    async def call(self, params: dict, timeout: float | None = None) -> dict:
        """
        模拟 API 调用：
        1. 随机延迟 latency_min ~ latency_max
        2. 如果延迟 > timeout → 抛出 ServiceTimeoutError
        3. 概率 failure_rate → 抛出 ServiceUnavailableError
        4. 否则 → 调用子类 _handle(params)
        """
        effective_timeout = timeout or self.timeout
        latency = random.uniform(self.latency_min, self.latency_max)

        if latency > effective_timeout:
            await asyncio.sleep(effective_timeout)
            raise ServiceTimeoutError(f"{self.name} timeout after {effective_timeout}s")
        else:
            await asyncio.sleep(latency)

        if random.random() < self.failure_rate:
            raise ServiceUnavailableError(f"{self.name} temporarily unavailable")

        return self._handle(params)

    @abstractmethod
    def _handle(self, params: dict) -> dict:
        """
        子类实现：实际业务逻辑。
        返回格式：{"items": [{"id": "...", "name": "...", ...}]}
        """
        pass

    def _filter_by_tags(self, items: list[dict], tags: list[str]) -> list[dict]:
        """按标签过滤，匹配越多排序越靠前"""
        scored = []
        for item in items:
            item_tags = item.get("tags", [])
            score = sum(1 for t in tags if t in item_tags)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def _filter_by_distance(self, items: list[dict], max_km: float) -> list[dict]:
        """按距离过滤"""
        return [item for item in items if item.get("distance_km", 0) <= max_km]

    def _filter_by_people(self, items: list[dict], people_count: int) -> list[dict]:
        """按容纳人数过滤"""
        return [item for item in items if item.get("max_people", 999) >= people_count]
```

### 5.2 餐厅搜索 + 订座服务

文件：`mock_services/restaurant.py`

```python
class RestaurantService(MockService):
    def __init__(self):
        super().__init__(
            name="RestaurantService",
            latency_range=(0.3, 1.0),
            failure_rate=0.12,
            timeout=2.0,
            data_file="data/mock/restaurants.json",
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {
            "tags": ["kid_friendly", "healthy"],
            "distance_km": 10.0,
            "people_count": 3,
            "time": "18:00",           # 可选
            "action": "search" | "reserve"
        }
        """
        action = params.get("action", "search")

        if action == "search":
            items = self._filter_by_tags(self.data, params.get("tags", []))
            items = self._filter_by_distance(items, params.get("distance_km", 10))
            items = self._filter_by_people(items, params.get("people_count", 1))

            # 模拟实时空位状态（随机）
            for item in items:
                item["availability"] = random.random() > 0.2  # 80% 有空位
                if item["availability"]:
                    item["available_slots"] = ["17:30", "18:00", "18:30", "19:00"]

            return {"items": items[:5]}

        elif action == "reserve":
            # 模拟订座：90% 成功率
            if random.random() < 0.1:
                raise ServiceUnavailableError("No table available for this time")
            return {
                "status": "reserved",
                "restaurant": params.get("restaurant_name", ""),
                "time": params.get("time", ""),
                "people": params.get("people_count", 0),
                "confirmation_code": f"RSV-{random.randint(10000, 99999)}",
            }
```

### 5.3 活动搜索 + 购票服务

文件：`mock_services/activity.py`

```python
class ActivityService(MockService):
    def __init__(self):
        super().__init__(
            name="ActivityService",
            latency_range=(0.3, 1.2),
            failure_rate=0.12,
            timeout=2.0,
            data_file="data/mock/activities.json",
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {
            "tags": ["kids_playground", "indoor"],
            "distance_km": 10.0,
            "people_count": 3,
            "duration_hours": 2,
            "action": "search" | "order"
        }
        """
        action = params.get("action", "search")

        if action == "search":
            items = self._filter_by_tags(self.data, params.get("tags", []))
            items = self._filter_by_distance(items, params.get("distance_km", 10))

            # 剩余票数模拟
            for item in items:
                item["remaining_tickets"] = random.randint(0, 50)
                item["availability"] = item["remaining_tickets"] >= params.get("people_count", 1)

            return {"items": items[:5]}

        elif action == "order":
            if random.random() < 0.1:
                raise ServiceUnavailableError("Tickets sold out")
            return {
                "status": "ordered",
                "activity": params.get("activity_name", ""),
                "tickets": params.get("people_count", 0),
                "total_price": params.get("people_count", 0) * random.randint(30, 150),
                "order_id": f"ORD-{random.randint(10000, 99999)}",
            }
```

### 5.4 天气查询服务

文件：`mock_services/weather.py`

```python
class WeatherService(MockService):
    def __init__(self):
        super().__init__(
            name="WeatherService",
            latency_range=(0.1, 0.5),
            failure_rate=0.05,       # 天气服务较稳定
            timeout=1.5,
            data_file="data/mock/weather.json",
        )

    def _handle(self, params: dict) -> dict:
        """
        params: {"time": "afternoon"}
        返回下午时段的天气
        """
        # 从数据集随机选一条天气
        weather = random.choice(self.data)
        return {"items": [weather]}
```

### 5.5 鲜花配送服务

文件：`mock_services/flower.py`

```python
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
            "action": "search" | "order"
        }
        """
        action = params.get("action", "search")

        if action == "search":
            items = [item for item in self.data if params.get("occasion") in item.get("tags", [])]
            return {"items": items[:3]}

        elif action == "order":
            # 检查配送时段是否可用
            delivery_time = params.get("delivery_time", "")
            if delivery_time and random.random() < 0.15:
                # 该时段不可用，返回最近可用时段
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
```

### 5.6 消息发送服务

文件：`mock_services/messenger.py`

```python
class MessengerService(MockService):
    def __init__(self):
        super().__init__(
            name="MessengerService",
            latency_range=(0.05, 0.2),
            failure_rate=0.02,       # 消息服务极少失败
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
```

---

## 6. Mock 数据集设计

### 6.1 餐厅数据

文件：`data/mock/restaurants.json`

```json
[
  {
    "id": "r001",
    "name": "小鹿亲子餐厅",
    "description": "设有儿童游乐区，提供儿童套餐，环境温馨",
    "tags": ["kid_friendly", "family_style", "kids_menu", "casual_dining"],
    "price_level": "medium",
    "price_amount": 80.0,
    "distance_km": 3.5,
    "max_people": 10,
    "location": "朝阳区大望路88号",
    "cuisine": "中西融合"
  },
  {
    "id": "r002",
    "name": "轻食主义",
    "description": "主打低卡健康餐，所有菜品标注卡路里",
    "tags": ["healthy", "diet_light", "casual_dining", "organic"],
    "price_level": "medium",
    "price_amount": 65.0,
    "distance_km": 2.8,
    "max_people": 8,
    "location": "朝阳区光华路15号",
    "cuisine": "轻食沙拉"
  },
  {
    "id": "r003",
    "name": "聚点烤吧",
    "description": "适合朋友聚餐的烧烤店，氛围热闹，有包间",
    "tags": ["group_dining", "social", "bbq", "casual_dining"],
    "price_level": "medium",
    "price_amount": 90.0,
    "distance_km": 4.2,
    "max_people": 12,
    "location": "海淀区中关村大街22号",
    "cuisine": "烧烤"
  },
  {
    "id": "r004",
    "name": "绿野仙踪素食馆",
    "description": "精致素食餐厅，环境安静雅致",
    "tags": ["healthy", "diet_light", "vegetarian", "organic"],
    "price_level": "high",
    "price_amount": 120.0,
    "distance_km": 5.0,
    "max_people": 6,
    "location": "东城区鼓楼东大街3号",
    "cuisine": "素食"
  },
  {
    "id": "r005",
    "name": "火锅英雄",
    "description": "网红火锅店，多种锅底，适合大规模聚餐",
    "tags": ["group_dining", "social", "spicy_food", "popular"],
    "price_level": "medium",
    "price_amount": 100.0,
    "distance_km": 1.5,
    "max_people": 20,
    "location": "朝阳区三里屯路11号",
    "cuisine": "火锅"
  },
  {
    "id": "r006",
    "name": "小熊乐园主题餐厅",
    "description": "卡通主题餐厅，提供儿童表演和互动游戏",
    "tags": ["kid_friendly", "family_style", "kids_menu", "entertainment"],
    "price_level": "high",
    "price_amount": 130.0,
    "distance_km": 7.0,
    "max_people": 8,
    "location": "丰台区方庄路6号",
    "cuisine": "西餐"
  },
  {
    "id": "r007",
    "name": "香满楼川菜",
    "description": "正宗川菜，麻辣鲜香，适合嗜辣人群",
    "tags": ["spicy_food", "group_dining", "casual_dining"],
    "price_level": "low",
    "price_amount": 55.0,
    "distance_km": 2.0,
    "max_people": 10,
    "location": "朝阳区望京街5号",
    "cuisine": "川菜"
  },
  {
    "id": "r008",
    "name": "海风日料",
    "description": "新鲜刺身和寿司，环境安静适合家庭",
    "tags": ["kid_friendly", "healthy", "family_style", "japanese"],
    "price_level": "high",
    "price_amount": 150.0,
    "distance_km": 6.0,
    "max_people": 6,
    "location": "西城区金融街1号",
    "cuisine": "日料"
  }
]
```

### 6.2 活动数据

文件：`data/mock/activities.json`

```json
[
  {
    "id": "a001",
    "name": "贝乐堡儿童乐园",
    "description": "大型室内儿童乐园，滑梯、海洋球、攀爬架，适合3-10岁",
    "tags": ["kids_playground", "indoor", "family_friendly", "kids"],
    "price_level": "medium",
    "price_amount": 120.0,
    "distance_km": 3.0,
    "duration_hours": 2.5,
    "location": "朝阳区青年路10号",
    "max_people": 100
  },
  {
    "id": "a002",
    "name": "朝阳公园",
    "description": "市区大型公园，可划船、野餐、放风筝",
    "tags": ["park", "outdoor", "family_friendly", "free"],
    "price_level": "low",
    "price_amount": 0.0,
    "distance_km": 2.0,
    "duration_hours": 2.0,
    "location": "朝阳区朝阳公园南路1号",
    "max_people": 999
  },
  {
    "id": "a003",
    "name": "当代艺术馆 -「未来城市」展览",
    "description": "沉浸式数字艺术展，适合拍照打卡，展期最后一周",
    "tags": ["exhibition", "indoor", "interactive", "art", "instagrammable"],
    "price_level": "medium",
    "price_amount": 88.0,
    "distance_km": 5.5,
    "duration_hours": 1.5,
    "location": "朝阳区798艺术区",
    "max_people": 200
  },
  {
    "id": "a004",
    "name": "南锣鼓巷 Citywalk",
    "description": "老北京胡同漫步，沿途小吃、文创小店",
    "tags": ["citywalk", "outdoor", "food_street", "shopping", "free"],
    "price_level": "low",
    "price_amount": 0.0,
    "distance_km": 4.0,
    "duration_hours": 2.0,
    "location": "东城区南锣鼓巷",
    "max_people": 999
  },
  {
    "id": "a005",
    "name": "密室逃脱 - 古堡迷踪",
    "description": "4-6人合作解谜，恐怖主题，时长90分钟",
    "tags": ["interactive", "indoor", "group_activity", "escape_room"],
    "price_level": "medium",
    "price_amount": 98.0,
    "distance_km": 2.5,
    "duration_hours": 2.0,
    "location": "海淀区五道口15号",
    "max_people": 6
  },
  {
    "id": "a006",
    "name": "亲子烘焙工坊",
    "description": "家长和孩子一起做蛋糕，成品可带走，时长2小时",
    "tags": ["kids", "family_friendly", "indoor", "diy", "cooking"],
    "price_level": "medium",
    "price_amount": 150.0,
    "distance_km": 1.8,
    "duration_hours": 2.0,
    "location": "朝阳区双井路3号",
    "max_people": 20
  },
  {
    "id": "a007",
    "name": "水立方嬉水乐园",
    "description": "室内水上乐园，造浪池、水滑梯，亲子友好",
    "tags": ["kids_playground", "indoor", "family_friendly", "water"],
    "price_level": "high",
    "price_amount": 180.0,
    "distance_km": 8.0,
    "duration_hours": 3.0,
    "location": "朝阳区天辰东路11号",
    "max_people": 300
  },
  {
    "id": "a008",
    "name": "剧本杀 - 大唐风云",
    "description": "沉浸式古风剧本杀，6人起开，时长3小时",
    "tags": ["interactive", "indoor", "group_activity", "roleplay"],
    "price_level": "high",
    "price_amount": 168.0,
    "distance_km": 3.5,
    "duration_hours": 3.0,
    "location": "朝阳区望京SOHO",
    "max_people": 8
  }
]
```

### 6.3 天气数据

文件：`data/mock/weather.json`

```json
[
  {
    "id": "w001",
    "condition": "晴天",
    "temperature": 26.0,
    "humidity": 45,
    "wind": "微风",
    "outdoor_suitable": true,
    "tags": ["sunny", "outdoor_ok"],
    "description": "晴朗，气温26°C，适合户外活动"
  },
  {
    "id": "w002",
    "condition": "多云",
    "temperature": 22.0,
    "humidity": 55,
    "wind": "3级",
    "outdoor_suitable": true,
    "tags": ["cloudy", "outdoor_ok"],
    "description": "多云，气温22°C，适合户外活动"
  },
  {
    "id": "w003",
    "condition": "小雨",
    "temperature": 18.0,
    "humidity": 80,
    "wind": "2级",
    "outdoor_suitable": false,
    "tags": ["rain", "indoor_preferred"],
    "description": "小雨，气温18°C，建议选择室内活动"
  },
  {
    "id": "w004",
    "condition": "雷阵雨",
    "temperature": 20.0,
    "humidity": 85,
    "wind": "4级",
    "outdoor_suitable": false,
    "tags": ["storm", "indoor_only"],
    "description": "雷阵雨，气温20°C，强烈建议室内活动"
  }
]
```

### 6.4 鲜花数据

文件：`data/mock/flowers.json`

```json
[
  {
    "id": "f001",
    "name": "浪漫玫瑰 bouquet",
    "description": "11支红玫瑰，搭配满天星",
    "tags": ["celebration", "romance", "anniversary"],
    "price_level": "medium",
    "price_amount": 199.0,
    "delivery_time": "2小时内送达"
  },
  {
    "id": "f002",
    "name": "温馨康乃馨花篮",
    "description": "粉色康乃馨花篮，适合家庭庆祝",
    "tags": ["celebration", "family", "birthday"],
    "price_level": "medium",
    "price_amount": 168.0,
    "delivery_time": "2小时内送达"
  },
  {
    "id": "f003",
    "name": "精致蛋糕组合",
    "description": "6寸鲜奶蛋糕+手写祝福卡",
    "tags": ["celebration", "birthday", "party"],
    "price_level": "medium",
    "price_amount": 238.0,
    "delivery_time": "3小时内送达"
  }
]
```

### 6.5 偏好存储结构（运行时生成）

文件：`data/runtime/preferences.json`（初始为空）

```json
{
  "records": []
}
```

---

## 7. 配置与工具模块

### 7.1 配置

文件：`config/settings.py`

```python
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 7.2 日志模块

文件：`utils/logger.py`

```python
import logging
import sys
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


# 为每个 Agent 创建独立 logger
planner_logger = setup_logger("Planner")
searcher_logger = setup_logger("Searcher")
executor_logger = setup_logger("Executor")
memory_logger = setup_logger("Memory")
orchestrator_logger = setup_logger("Orchestrator")
```

### 7.3 CLI 美化输出

文件：`utils/display.py`

```python
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.text import Text
from rich import box

console = Console()


def print_agent_header(agent_name: str, action: str):
    """打印 Agent 操作头部"""
    console.print(Panel(
        f"[bold cyan]{agent_name}[/bold cyan] → {action}",
        border_style="cyan",
        box=box.ROUNDED,
    ))


def print_plan_set(plan_set):
    """打印方案集"""
    for i, plan in enumerate(plan_set.plans, 1):
        table = Table(title=f"方案 {i}: {plan.title}", box=box.ROUNDED)
        table.add_column("时间", style="cyan")
        table.add_column("活动", style="white")
        table.add_column("地点", style="green")
        table.add_column("备注", style="yellow")

        for slot in plan.timeline:
            action_icon = "🔖" if slot.action_required else ""
            table.add_row(
                slot.time_range,
                slot.activity_name,
                slot.location,
                f"{action_icon} {slot.notes}".strip(),
            )

        console.print(table)
        console.print(f"[bold]预估花费:[/bold] {plan.total_budget}")
        if plan.highlights:
            console.print(f"[bold]亮点:[/bold] {', '.join(plan.highlights)}")
        if plan.risk_notes:
            console.print(f"[bold yellow]提示:[/bold yellow] {', '.join(plan.risk_notes)}")
        console.print()

    console.print(f"[bold green]💡 推荐:[/bold green] {plan_set.recommendation}")


def print_execution_plan(plan):
    """打印执行计划（带 booking 清单）"""
    console.print(Panel(f"[bold]执行计划[/bold]\n{plan.summary}", border_style="magenta"))

    table = Table(title="预订清单", box=box.ROUNDED)
    table.add_column("#", style="dim")
    table.add_column("服务", style="cyan")
    table.add_column("项目", style="white")
    table.add_column("操作", style="yellow")
    table.add_column("备选", style="dim")

    for i, booking in enumerate(plan.bookings, 1):
        table.add_row(
            str(i),
            booking.service,
            booking.target_name,
            booking.action_type,
            booking.fallback_target or "-",
        )

    console.print(table)


def print_execution_result(result):
    """打印执行结果"""
    success_style = "green" if result.status == "all_success" else "yellow"
    console.print(Panel(
        f"[bold {success_style}]执行完成[/bold {success_style}]\n"
        f"成功: {result.success_count} | 失败: {result.failed_count}",
        border_style=success_style,
    ))

    if result.final_message:
        console.print(f"\n[bold]📨 已发送消息:[/bold]\n{result.final_message}")
```

---

## 8. 异常处理策略

### 8.1 完整异常处理表

| 阶段 | 异常场景 | 触发条件 | 处理方式 | 用户可见 |
|------|---------|---------|---------|---------|
| **搜索** | 单个服务超时 | >2s 无响应 | 标记 failed，使用 fallback_tags 重试 | "餐厅搜索超时，已使用备选推荐" |
| **搜索** | 全部服务失败 | 5 个服务均失败 | 返回 `overall_status=failed`，Planner 生成纯文本方案 | "暂时无法获取信息，为您推荐以下备选方案" |
| **搜索** | 餐厅无空位 | `availability=false` | 自动替换为备选餐厅（同标签），最多 3 次 | "首选餐厅已满，已为您更换 XX 餐厅" |
| **搜索** | 价格超出预算 | 价格 > 用户历史均价 2x | 标记 `price_alert`，排序降权 | "以下选项价格较高，已标注" |
| **搜索** | 天气不适宜户外 | `outdoor_suitable=false` | 自动过滤户外活动，标注原因 | "今天有雨，已调整为室内活动" |
| **搜索** | 活动票不足 | `remaining_tickets < people_count` | 标记不可用，不进入候选 | 不展示（内部过滤） |
| **搜索** | 距离无匹配 | 所有候选距离 > max_distance | 提示用户放宽距离 | "10km 内无合适选项，是否放宽到 15km？" |
| **规划** | 用户拒绝全部方案 | 连续拒绝 3 次 | 询问调整约束（距离/时长/预算） | "您希望优先调整哪个条件？" |
| **规划** | 方案时间冲突 | 活动 + 餐饮 + 交通 > 可用时长 | 压缩单个 activity 时长或移除一项 | "原方案时间紧张，已优化安排" |
| **规划** | LLM 返回格式异常 | JSON 解析失败 | 重试 1 次，仍失败则用规则模板生成 | "正在重新规划..." |
| **确认** | 用户要求改时间 | "太早了/太晚了" | Executor 整体偏移时间线 | "已调整到 XX:XX 出发" |
| **确认** | 用户要求换餐厅 | "不想吃这个" | 调用 Searcher 重新搜索，保持其他项不变 | "正在搜索其他餐厅..." |
| **确认** | 用户要求取消某项 | "不要鲜花了" | 从计划中移除该项，重新生成消息 | "已移除鲜花配送" |
| **确认** | 用户要求增加人数 | "朋友多来 2 人" | 检查餐厅容量，不足则重新搜索 | "正在查询 6 人桌位..." |
| **确认** | 用户要求降预算 | "换个便宜的" | 过滤 high price_level，替换为 medium/low | "已调整为经济方案" |
| **确认** | 用户要求换活动类型 | "不想去游乐园" | 移除该 Booking，补入下一个活动推荐 | "已将游乐园替换为 XX" |
| **确认** | 调整轮次超限 | 超过 5 轮 | 强制确认当前计划或放弃 | "已调整多次，是否确认当前方案？" |
| **执行** | 预订失败（已满） | API 返回 no_table | 尝试 fallback，仍失败则标记 | "餐厅 A 预订失败，备选 B 预订成功" |
| **执行** | 支付失败 | API 返回 payment_error | 暂停支付类操作，完成免费预订 | "支付失败，免费预订已完成" |
| **执行** | 配送时段不可用 | 鲜花返回 time_unavailable | 自动调整到最近可用时段 | "鲜花配送时间调整为 16:30" |
| **执行** | 部分成功 | N 项中 M 项失败 | 展示清单，询问是否重试 | "3 项成功 2 项失败，是否重试？" |
| **执行** | 全部执行失败 | 所有 booking 失败 | 提示错误原因，建议手动操作 | "预订全部失败，已输出方案供手动操作" |
| **记忆** | 偏好文件损坏 | JSON 解析失败 | 降级为空记忆，重建文件 | 无提示（内部处理） |
| **记忆** | 存储空间不足 | 写入磁盘满 | 丢弃最旧 10 条记录后重试 | 无提示（内部处理） |
| **系统** | 网络/进程异常 | 所有 API 不可达 | 捕获异常，保存进度到 temp 文件 | "系统异常，已保存进度" |
| **系统** | LLM 调用失败 | API Key 无效/额度不足 | 优雅退出，提示需检查配置 | "LLM 调用失败，请检查 API Key" |

### 8.2 四级降级策略

```
Level 1（服务级）: 单个服务失败
  → 使用预置 fallback 数据 + 标记 fallback_used

Level 2（方案级）: 多个服务失败
  → 减少活动数量，保证核心体验：1 餐 + 1 活动

Level 3（交互级）: 用户参与调整
  → 放宽距离/时长/预算约束，让用户引导重新搜索

Level 4（最终级）: 全部失败
  → 输出纯文本建议（无预订），引导用户手动操作
```

---

## 9. 项目目录结构

```
D:\美团hackson\
│
├── main.py                          # CLI 入口 + Orchestrator 调度器
├── Makefile                         # 一键命令
├── requirements.txt                 # 依赖清单
├── .env.example                     # 配置模板
├── .gitignore
├── README.md
│
├── agents/
│   ├── __init__.py
│   ├── planner.py                   # Planner Agent
│   ├── searcher.py                  # Searcher Agent
│   ├── executor.py                  # Executor Agent
│   └── memory.py                    # Memory Agent
│
├── mock_services/
│   ├── __init__.py
│   ├── base.py                      # MockService 基类
│   ├── restaurant.py                # 餐厅搜索 + 订座
│   ├── activity.py                  # 活动搜索 + 购票
│   ├── weather.py                   # 天气查询
│   ├── flower.py                    # 鲜花配送
│   └── messenger.py                 # 消息发送
│
├── models/
│   ├── __init__.py
│   └── messages.py                  # Pydantic 消息协议
│
├── config/
│   ├── __init__.py
│   └── settings.py                  # pydantic-settings 配置
│
├── data/
│   ├── mock/
│   │   ├── restaurants.json         # 餐厅预置数据
│   │   ├── activities.json          # 活动预置数据
│   │   ├── weather.json             # 天气预置数据
│   │   └── flowers.json             # 鲜花预置数据
│   └── runtime/
│       └── .gitkeep                 # 运行时数据目录
│
├── utils/
│   ├── __init__.py
│   ├── logger.py                    # 日志模块
│   ├── display.py                   # CLI 美化输出（rich）
│   └── retry.py                     # 重试装饰器
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # pytest fixtures
│   ├── test_mock_services.py        # Mock 服务单测
│   ├── test_planner.py              # Planner 单测
│   ├── test_searcher.py             # Searcher 单测
│   ├── test_executor.py             # Executor 单测
│   ├── test_memory.py               # Memory 单测
│   └── test_integration.py          # 端到端集成测试
│
└── docs/
    └── design.md                    # 本设计文档
```

---

## 10. 开发 Issue 拆解

### 阶段 0：基础设施（3 个 Issue，可并行）

| Issue ID | 标题 | 产出物 | 关键实现要求 |
|----------|------|--------|------------|
| **#1** | 项目骨架搭建 | 目录结构、Makefile、requirements.txt、.env.example、.gitignore | Makefile 包含 install/run/test/demo 四个目标 |
| **#2** | 消息协议定义 | `models/messages.py` | 完整 Pydantic 模型，需包含本文档 §3 全部定义 |
| **#3** | 配置与工具模块 | `config/settings.py`、`utils/logger.py`、`utils/display.py`、`utils/retry.py` | retry.py 实现 `@retry(max_attempts=2, backoff=1.0)` 异步装饰器 |

### 阶段 1：Mock 服务层（5 个 Issue，#4 先做，#5-#8 可并行）

| Issue ID | 标题 | 产出物 | 关键实现要求 |
|----------|------|--------|------------|
| **#4** | Mock Service 基类 | `mock_services/base.py` | 实现 §5.1 全部逻辑：延迟、超时、失败率、过滤方法 |
| **#5** | 餐厅搜索 + 订座 | `mock_services/restaurant.py` | search 和 reserve 两种 action，含空位模拟 |
| **#6** | 活动搜索 + 购票 | `mock_services/activity.py` | search 和 order 两种 action，含余票模拟 |
| **#7** | 天气查询 | `mock_services/weather.py` | 单 action，返回随机天气 |
| **#8** | 鲜花配送 + 消息发送 | `mock_services/flower.py`、`mock_services/messenger.py` | 配送时段检查、消息发送 |

### 阶段 2：Agent 实现（4 个 Issue，严格串行）

| Issue ID | 标题 | 产出物 | 关键实现要求 |
|----------|------|--------|------------|
| **#9** | Planner Agent | `agents/planner.py` | 两阶段方法：stage1_plan_search + stage2_generate_plans，含 LLM prompt 模板 |
| **#10** | Searcher Agent | `agents/searcher.py` | asyncio.gather 并发、降级、权重排序 |
| **#11** | Executor Agent + Pre-execution Loop | `agents/executor.py` | 确认循环（≤5 轮）、LLM 评估反思、批量执行 |
| **#12** | Memory Agent | `agents/memory.py` | JSON 读写、标签聚合、保留最近 50 条 |

### 阶段 3：集成与交付（4 个 Issue，#13 先做，#14-#16 可并行）

| Issue ID | 标题 | 产出物 | 关键实现要求 |
|----------|------|--------|------------|
| **#13** | Orchestrator + CLI 入口 | `main.py` | 串行调度 4 个 Agent，用户交互，`make demo` 预设场景 |
| **#14** | 单元测试 | `tests/test_*.py` | 每个 Agent 和 Service 至少 3 个测试用例 |
| **#15** | 集成测试 | `tests/test_integration.py` | 小明家庭场景 + 朋友场景，asyncio 端到端 |
| **#16** | README + 演示 | README.md | 安装说明、使用示例、架构图、常见问题 |

**总计 16 个 Issue，预估单人 5-7 日。**

---

## 11. 实现顺序与依赖关系

```
阶段 0（并行）
#1 #2 #3
  ↘  ↓  ↙
阶段 1
#4（基类，必须先做）
  ↓
#5 #6 #7 #8（并行）
  ↘  ↓  ↙
阶段 2（严格串行）
#9 (Planner)
  ↓
#10 (Searcher)
  ↓
#11 (Executor)
  ↓
#12 (Memory)
  ↓
阶段 3
#13 (Orchestrator + CLI)
  ↓
#14 #15（并行）
  ↓
#16 (README + demo)
```

### 11.1 main.py Orchestrator 伪代码

```python
async def main():
    # 初始化
    settings = Settings()
    llm = ChatOpenAI(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )

    services = {
        "restaurant": RestaurantService(),
        "activity": ActivityService(),
        "weather": WeatherService(),
        "flower": FlowerService(),
        "messenger": MessengerService(),
    }

    memory_agent = MemoryAgent()
    planner = PlannerAgent(llm, memory_agent)
    searcher = SearcherAgent(services)
    executor = ExecutorAgent(services, services["messenger"])

    # 读取用户输入
    console.print("[bold]🎯 请输入你的活动需求:[/bold]")
    user_input = console.input("> ")

    # ====== 阶段 1: Planner 解析 + 生成搜索请求 ======
    print_agent_header("Planner", "正在分析你的需求...")
    intent, search_request = await planner.stage1_plan_search(user_input)
    console.print(f"识别到场景: {intent.scene}, {intent.people_count}人, {intent.duration_hours}小时")

    # ====== 阶段 2: Searcher 并发搜索 ======
    print_agent_header("Searcher", "正在搜索餐厅、活动、天气...")
    search_result = await searcher.search(search_request)
    console.print(f"搜索完成: {search_result.overall_status}")

    # ====== 阶段 3: Planner 整合方案 ======
    print_agent_header("Planner", "正在为你规划方案...")
    plan_set = await planner.stage2_generate_plans(intent, search_result)
    print_plan_set(plan_set)

    # 用户选择方案
    choice = console.input("\n请选择一个方案 (输入编号) [1/2/3]: ")
    chosen_plan = plan_set.plans[int(choice) - 1]

    # 生成执行计划
    execution_plan = await planner.create_execution_plan(chosen_plan)

    # ====== 阶段 4: Executor 确认循环 + 执行 ======
    print_agent_header("Executor", "准备执行，请确认以下计划...")
    final_plan = await executor.pre_execution_loop(execution_plan)

    print_agent_header("Executor", "正在执行预订...")
    result = await executor.execute(final_plan)
    print_execution_result(result)

    # ====== 阶段 5: Memory 记录偏好 ======
    print_agent_header("Memory", "正在记录你的偏好...")
    rejected = []  # 从确认循环中收集
    await memory_agent.record(final_plan, rejected_items=rejected, intent=intent)
    console.print("[green]✅ 偏好已记录，下次规划会更懂你！[/green]")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 12. CLI 交互流程示例

以下是以小明家庭场景为例的完整 CLI 交互流程：

```
$ make run

🎯 请输入你的活动需求:
> 今天下午想带老婆和5岁孩子出去玩4个小时，别离家太远，老婆在减肥

┌─ Planner ─→ 正在分析你的需求... ─────────────────┐
│ 识别到场景: family, 3人, 4小时, 10km内              │
│ 约束: child_age_5, diet_light                       │
│ 偏好匹配: 命中，上次选择了亲子餐厅+儿童乐园           │
└────────────────────────────────────────────────────┘

┌─ Searcher ─→ 正在搜索餐厅、活动、天气... ─────────┐
│ ✓ 餐厅搜索: 找到 3 家匹配餐厅                        │
│ ✓ 活动搜索: 找到 4 个亲子活动                        │
│ ⚠ 天气查询: 小雨，已标记 indoor_preferred            │
└────────────────────────────────────────────────────┘

┌─ Planner ─→ 正在为你规划方案... ──────────────────┐

方案 1: 亲子轻食半日游
┌──────────┬──────────────────┬──────────────────┬──────────┐
│ 时间     │ 活动             │ 地点             │ 备注     │
├──────────┼──────────────────┼──────────────────┼──────────┤
│ 14:00-16:00 │ 贝乐堡儿童乐园  │ 朝阳区青年路10号  │ 🔖 需购票 │
│ 16:30-18:00 │ 轻食主义        │ 朝阳区光华路15号  │ 🔖 需订座 │
└──────────┴──────────────────┴──────────────────┴──────────┘
预估花费: 活动120元/人 + 餐饮65元/人 = 约555元
亮点: 室内活动不受天气影响, 餐厅标注卡路里适合减肥
提示: 今天有小雨，已选择室内活动

方案 2: 烘焙体验+主题晚餐
... (省略)

💡 推荐: 方案1，乐园离餐厅仅10分钟车程，时间衔接最佳

请选择一个方案 (输入编号) [1/2]: 1

┌─ Executor ─→ 准备执行，请确认以下计划... ─────────┐
│                                                      │
│ 预订清单:                                            │
│ #1 [activity] 贝乐堡儿童乐园 → order (备选: 亲子烘焙) │
│ #2 [restaurant] 轻食主义 → reserve (备选: 小鹿亲子)   │
│                                                      │
│ 发送消息给老婆:                                       │
│ "搞定了，下午2点出发，先去贝乐堡玩2小时，然后去轻食主义│
│  吃饭，都订好了，你看看行不？"                         │
│                                                      │
│ 确认执行? 或提出修改意见:                             │
└────────────────────────────────────────────────────┘

> 能不能再加一个蛋糕送到餐厅，今天是结婚纪念日

┌─ Executor ─→ 评估反馈... ─────────────────────────┐
│ 识别到：添加庆祝物品                                  │
│ 已添加蛋糕配送至轻食主义，17:30 送达                  │
│ 更新后的预订清单:                                     │
│ #1 [activity] 贝乐堡儿童乐园 → order                  │
│ #2 [restaurant] 轻食主义 → reserve                    │
│ #3 [flower] 精致蛋糕组合 → order (配送至轻食主义)      │
└────────────────────────────────────────────────────┘

> 确认

┌─ Executor ─→ 正在执行预订... ─────────────────────┐
│ ✓ 贝乐堡儿童乐园: 购票成功，订单 ORD-38472            │
│ ✓ 轻食主义: 订座成功，确认 RSV-12839                 │
│ ✓ 精致蛋糕组合: 下单成功，17:30送达                   │
│                                                      │
│ 执行完成 ✅ 成功: 3 | 失败: 0                         │
│                                                      │
│ 📨 已发送消息:                                        │
│ "搞定了，下午2点出发，先去贝乐堡玩2小时，              │
│  然后去轻食主义吃饭，蛋糕已经订好了送到餐厅，          │
│  纪念日快乐！你看看行不？"                            │
└────────────────────────────────────────────────────┘

┌─ Memory ─→ 正在记录你的偏好... ───────────────────┐
│ ✅ 偏好已记录，下次规划会更懂你！                      │
└────────────────────────────────────────────────────┘
```

---

## 附录 A: requirements.txt

```
langchain>=0.3.0
langchain-core>=0.3.0
langchain-openai>=0.2.0
pydantic>=2.0
pydantic-settings>=2.0
python-dotenv>=1.0
rich>=13.0
pytest>=8.0
pytest-asyncio>=0.23
```

## 附录 B: Makefile

```makefile
.PHONY: install run test demo clean

install:
	pip install -r requirements.txt

run:
	python main.py

test:
	pytest tests/ -v --asyncio-mode=auto

demo:
	@echo "=== 场景1: 小明家庭场景 ==="
	@echo "今天下午想带老婆和5岁孩子出去玩4个小时，别离家太远，老婆在减肥" | python main.py --demo family
	@echo ""
	@echo "=== 场景2: 小明朋友场景 ==="
	@echo "今天下午想和3个朋友出去玩5小时，2男2女，找个有意思的地方" | python main.py --demo friends

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf data/runtime/preferences.json
```

## 附录 C: .env.example

```env
# LLM 配置
OPENAI_API_KEY=sk-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.7

# Mock 服务配置
MOCK_FAILURE_RATE=0.15
MOCK_MIN_LATENCY=0.2
MOCK_MAX_LATENCY=1.0
MOCK_TIMEOUT=2.0

# 日志
LOG_LEVEL=INFO
```