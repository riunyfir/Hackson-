"""Planner Agent：意图解析 + 方案整合（v2.0 升级版）。
新增：位置收集、两阶段 LLM 生成、后处理校验、完整方案描述。
"""
import json
import re
import math
from datetime import datetime
from langchain_openai import ChatOpenAI
from models.messages import (
    ParsedIntent, SearchRequest, SearchQuery, SearchResult,
    Plan, PlanSet, TimelineSlot, ExecutionPlan, BookingAction,
    WeatherContext, BudgetItem, ContingencyPlan, SlotDetail,
    ServiceCandidate, ServiceResult, SceneType,
)
from models.messages import PreferenceQueryResult
from utils.logger import planner_logger

# 地球曲率系数，用于Haversine距离计算
EARTH_RADIUS_M = 6371000


class PlannerAgent:
    def __init__(self, llm: ChatOpenAI, memory_agent):
        self.llm = llm
        self.memory_agent = memory_agent

    # ================================================================
    # 意图解析
    # ================================================================

    async def parse_intent(self, user_input: str, answers: dict | None = None) -> ParsedIntent:
        """调用 LLM 解析用户输入，综合结构化回答做意图识别。"""
        answers_section = ""
        if answers:
            parts = []
            if answers.get("scene"): parts.append(f"- 场景：{answers['scene']}")
            if answers.get("time_raw"): parts.append(f"- 时间描述：{answers['time_raw']}")
            if answers.get("atmosphere"): parts.append(f"- 氛围偏好：{answers['atmosphere']}")
            if answers.get("food_preference"): parts.append(f"- 饮食偏好：{answers['food_preference']}")
            if answers.get("budget_level"): parts.append(f"- 预算：{answers['budget_level']}")
            if answers.get("max_distance_km"): parts.append(f"- 最远距离：{answers['max_distance_km']}km")
            if answers.get("extra_notes"): parts.append(f"- 特殊需求：{answers['extra_notes']}")
            if parts:
                answers_section = "用户结构化回答：\n" + "\n".join(parts) + "\n\n"

        prompt = f"""你是一个活动规划意图解析器。请综合分析下面的用户结构化回答和原始输入，提取最终意图（纯 JSON，不要 markdown 代码块）。

决策原则：
- 如果结构化回答提供了明确的偏好（场景、预算、氛围等），应优先采纳
- 如果原始输入中有更具体的信息（如精确地点、时间），则以原始输入为准
- 结构化回答中的"随意"类选项视为未提供，不覆盖原始输入推断
- 氛围偏好应映射为对应的约束标签（安静→quiet, 网红打卡→网红打卡标签追加到需求字段）

分析要点：
- 位置：用户是否提到了具体地点/区域/坐标？
- 场景：是谁一起出行？亲子/朋友/情侣/单人
- 需求：用户想做什么类型的活动？吃什么类型的餐厅？
- 预算：用户有没有提到预算范围或价格敏感信号
- 约束：有没有带孩子、室内偏好、饮食限制、氛围要求等

输出格式：
{{
    "scene": "family" / "friends" / "couple" / "solo",
    "people_count": 数字,
    "duration_hours": 数字（默认4）,
    "max_distance_km": 数字（默认10）,
    "start_time": "HH:MM"（默认"14:00"）,
    "constraints": ["child_age_5", "diet_light", ...],
    "budget_level": "low" / "medium" / "high",
    "user_location": "如果提到了具体地点则提取，否则置空",
    "user_address": "同 user_location"
}}
约束标签规则：
- 提到孩子年龄 → "child_age_N"
- 提到减肥/轻食 → "diet_light"
- 提到室内/下雨 → "indoor_preferred"
- 提到省钱/便宜 → "budget_low"
- 提到庆祝/纪念日 → "celebration"
- 提到户外/运动 → "outdoor_activity"
- 提到安静/私密 → "quiet"
- 提到辣/火锅/川菜/湘菜/烧烤 → "spicy_food"
- 提到网红打卡 → "instagrammable"

{answers_section}用户原始输入：{user_input}"""

        response = await self.llm.ainvoke(prompt)
        text = response.content.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            planner_logger.warning("LLM JSON 解析失败，使用默认值")
            data = {}

        intent = ParsedIntent(
            scene=data.get("scene", "family"),
            people_count=data.get("people_count", 3),
            duration_hours=data.get("duration_hours", 4),
            max_distance_km=data.get("max_distance_km", 10),
            start_time=data.get("start_time", "14:00"),
            constraints=data.get("constraints", []),
            budget_level=data.get("budget_level", "medium"),
            user_location=data.get("user_location", ""),
            user_address=data.get("user_address", ""),
        )

        # 结构化回答中的明确值直接覆盖 LLM 输出（用户显式回答优先）
        if answers:
            if answers.get("max_distance_km") is not None:
                intent.max_distance_km = answers["max_distance_km"]

        return intent

    # ================================================================
    # 位置收集（新增）
    # ================================================================

    async def collect_location(
        self, intent: ParsedIntent, 
        get_user_input,   # async callable → str
    ) -> ParsedIntent:
        """
        如果 intent 中没有位置信息，交互式收集用户位置。
        支持直接输入坐标或地名（走高德地理编码）。
        不再有任何硬编码默认位置——必须由用户提供。
        """
        if intent.user_location:
            return intent

        while True:
            print("\n📍 请告诉我您的大概位置（支持坐标如 '116.443,39.921' 或地名如 '房山良乡'）：")
            raw = await get_user_input(None)
            if not raw or not raw.strip():
                print("   需要提供位置才能继续搜索，请重试")
                continue

            raw = raw.strip()

            # 尝试解析坐标
            from utils.geo import parse_coordinates, geocode
            coords = parse_coordinates(raw)
            if coords:
                lon, lat = coords
                intent.user_location = f"{lon},{lat}"
                try:
                    from utils.geo import reverse_geocode
                    intent.user_address = await reverse_geocode(intent.user_location)
                except Exception:
                    intent.user_address = raw
                print(f"   已定位: {intent.user_address}")
                return intent

            # 非坐标 → 地理编码
            try:
                loc, addr = await geocode(raw)
                intent.user_location = loc
                intent.user_address = addr
                print(f"   已定位: {addr}")
                return intent
            except Exception as e:
                planner_logger.warning(f"地理编码失败: {e}")
                print(f"   地理编码失败，请尝试其他地名或直接输入坐标")

    # ================================================================
    # 偏好收集（新增）
    # ================================================================

    async def ask_preferences(
        self,
        get_user_input,   # async callable → str
    ) -> dict:
        """
        在意图解析前，通过结构化提问收集用户偏好。
        问题顺序：场景 → 时间 → 氛围 → 饮食 → 预算 → 距离 → 特殊需求。
        返回 answers dict，供 parse_intent 综合用户原始输入做意图识别。
        """
        answers = {}

        # Q2: 和谁一起
        print("\n❓ 和谁一起？(1=亲子 / 2=朋友 / 3=情侣 / 4=单人，回车跳过)")
        raw = await get_user_input(None)
        scene_map = {"1": "family", "2": "friends", "3": "couple", "4": "solo"}
        if raw and raw.strip() in scene_map:
            answers["scene"] = scene_map[raw.strip()]

        # Q3: 时间
        print("\n❓ 什么时间出发？玩多久？（如'下午2点，3小时'，回车默认14:00开始4小时）")
        raw = await get_user_input(None)
        if raw and raw.strip():
            answers["time_raw"] = raw.strip()

        # Q4: 氛围
        print("\n❓ 偏好什么氛围？（1=热闹 / 2=安静私密 / 3=网红打卡 / 4=地道老店 / 5=随意，回车跳过）")
        raw = await get_user_input(None)
        atmosphere_map = {"1": "热闹", "2": "安静私密", "3": "网红打卡", "4": "地道老店"}
        if raw and raw.strip() in atmosphere_map:
            answers["atmosphere"] = atmosphere_map[raw.strip()]
        elif raw and raw.strip() == "5":
            answers["atmosphere"] = "随意"

        # Q5: 忌口或特别想吃
        print("\n❓ 有什么忌口或特别想吃的？（如'不吃辣'、'就想吃火锅'，回车跳过）")
        raw = await get_user_input(None)
        if raw and raw.strip():
            answers["food_preference"] = raw.strip()

        # Q6: 预算
        print("\n❓ 预算范围？（1=实惠 / 2=中等 / 3=不设限，回车默认中等）")
        raw = await get_user_input(None)
        budget_map = {"1": "low", "2": "medium", "3": "high"}
        if raw and raw.strip() in budget_map:
            answers["budget_level"] = budget_map[raw.strip()]

        # Q7: 最远接受距离
        print("\n❓ 最远接受距离？（直接输入数字如5/10/15，回车默认10km）")
        raw = await get_user_input(None)
        if raw and raw.strip():
            try:
                answers["max_distance_km"] = int(raw.strip())
            except ValueError:
                pass

        # Q8: 其他特殊需求
        print("\n❓ 还有别的特殊需求吗？（如'带3岁孩子'、'需要停车位'，回车跳过）")
        raw = await get_user_input(None)
        if raw and raw.strip():
            answers["extra_notes"] = raw.strip()

        return answers

    # ================================================================
    # 阶段1：意图解析 + 搜索请求
    # ================================================================

    async def stage1_plan_search(self, intent: ParsedIntent) -> tuple[ParsedIntent, SearchRequest]:
        """阶段1：查询偏好 + 生成搜索请求（intent 已由外部完成解析和位置收集）"""
        preferences = await self.memory_agent.query(intent)

        location = intent.user_location  # collect_location 已确保不为空

        queries = [
            SearchQuery(
                service="restaurant",
                params={
                    "tags": self._get_restaurant_tags(intent, preferences),
                    "distance_km": intent.max_distance_km,
                    "people_count": intent.people_count,
                    "action": "search",
                    "location": location,
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
                    "action": "search",
                    "location": location,
                },
                fallback_tags=["park", "mall"],
            ),
            SearchQuery(
                service="weather",
                params={"location": location, "time": "afternoon"},
                fallback_tags=[],
            ),
        ]

        if "celebration" in intent.constraints:
            queries.append(SearchQuery(
                service="flower",
                params={"occasion": "celebration", "action": "search"},
                fallback_tags=["bouquet"],
            ))

        request = SearchRequest(
            task_id=f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            queries=queries,
            preference_weights=preferences.weights,
        )

        planner_logger.info(
            f"意图解析: scene={intent.scene}, {intent.people_count}人, "
            f"{intent.duration_hours}h, 位置={intent.user_address or '默认'}, 约束={intent.constraints}"
        )
        return intent, request

    # ================================================================
    # 标签生成
    # ================================================================

    def _get_restaurant_tags(self, intent: ParsedIntent, pref: PreferenceQueryResult) -> list[str]:
        tags = []
        if intent.scene == "family":
            tags.extend(["亲子", "家庭", "儿童"])
            if any("child_age" in c for c in intent.constraints):
                tags.append("儿童餐")
        elif intent.scene == "friends":
            tags.extend(["聚会", "火锅", "烧烤", "大桌"])
        elif intent.scene == "couple":
            tags.extend(["约会", "浪漫", "氛围", "西餐", "日料"])
        elif intent.scene == "solo":
            tags.extend(["简餐", "一人食", "小吃"])

        # 预算映射为搜索关键词
        if intent.budget_level == "low":
            tags.append("实惠")
        elif intent.budget_level == "high":
            tags.extend(["高档", "精致餐饮"])

        if "diet_light" in intent.constraints:
            tags.append("轻食")
        if "indoor_preferred" in intent.constraints:
            tags.append("室内")
        if "quiet" in intent.constraints:
            tags.append("安静")
        if "spicy_food" in intent.constraints:
            tags.extend(["火锅", "川菜", "湘菜"])
        if pref.preferred_tags:
            tags.extend(pref.preferred_tags)
        tags = [t for t in tags if t not in pref.rejected_tags]
        return tags

    def _get_activity_tags(self, intent: ParsedIntent, pref: PreferenceQueryResult) -> list[str]:
        tags = []
        if intent.scene == "family":
            tags.extend(["亲子乐园", "儿童乐园", "家庭娱乐"])
        elif intent.scene == "friends":
            tags.extend(["展览", "密室逃脱", "桌游", "KTV", "运动"])
        elif intent.scene == "couple":
            tags.extend(["约会", "电影院", "咖啡馆", "公园", "展览", "演出"])
        elif intent.scene == "solo":
            tags.extend(["书店", "咖啡馆", "展览", "博物馆"])

        # 预算影响
        if intent.budget_level == "low":
            tags.append("免费")
        elif intent.budget_level == "high":
            tags.append("高端")

        if "indoor_preferred" in intent.constraints:
            tags = [t for t in tags if t not in ("公园", "户外")]
            tags.append("室内")
        if "outdoor_activity" in intent.constraints:
            tags.append("户外")

        if pref.preferred_tags:
            tags.extend(pref.preferred_tags)
        tags = [t for t in tags if t not in pref.rejected_tags]
        return tags

    # ================================================================
    # 阶段2a：搜索结果摘要 → LLM 生成结构化骨架
    # ================================================================

    async def stage2_generate_plans(
        self, intent: ParsedIntent, search_result: SearchResult
    ) -> PlanSet:
        """阶段2：根据搜索结果生成可选方案（两阶段 + 后处理校验）"""
        if search_result.overall_status == "failed":
            return self._generate_fallback_plan_set(intent)

        search_summary = self._summarize_results(search_result, intent)
        prompt = self._build_plan_prompt(intent, search_summary)

        response = await self.llm.ainvoke(prompt)
        text = response.content.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            planner_logger.warning("方案生成 JSON 解析失败，使用降级方案")
            return self._generate_fallback_plan_set(intent)

        plans = self._parse_plans(data, intent)
        if not plans:
            return self._generate_fallback_plan_set(intent)

        # 阶段2b：后处理校验
        for plan in plans:
            self._validate_and_fix_budget(plan)
            self._validate_timeline_duration(plan, intent.duration_hours)
            self._ensure_details_present(plan, intent)

        return PlanSet(
            plans=plans,
            recommendation=data.get("recommendation", "推荐方案1"),
            user_address=intent.user_address,
        )

    # ================================================================
    # 阶段2 辅助：构建 prompt
    # ================================================================

    def _build_plan_prompt(self, intent: ParsedIntent, search_summary: dict) -> str:
        """构建完整的方案生成 prompt（含所有新字段要求）。"""
        now = datetime.now()
        current_time_str = now.strftime("%Y年%m月%d日 %H:%M")
        return f"""你是一个活动规划师。请根据以下信息生成 2-3 个下午活动方案。

当前时间：{current_time_str}
用户意图：{intent.model_dump_json()}
搜索结果：{json.dumps(search_summary, ensure_ascii=False)}

【关键规则 - 必须严格遵守】
1. activity_name 和 location 必须使用搜索结果中真实的 name 和 full_address，严禁编造"某XX"等占位名称。
2. 距离约束：每个 timeline slot 的 distance_from_user 不得超过 {intent.max_distance_km}km。在满足此约束的前提下，根据用户的场景、预算、偏好标签综合选择最合适的 POI，不必机械地选最近的。如果所有候选都超过限制，选择最合适的并标注"距离较远"。
3. 区域约束：推荐地点必须在搜索结果覆盖范围内，不得推荐搜索结果中不存在的区域。
4. weather_context 的四个字段（condition/temperature/advice/impact）必须从搜索结果 weather.extra 中逐字复制，不得修改或编造。
5. candidates 备选也必须使用搜索结果中的真实 name。

每个方案必须包含以下完整字段（纯 JSON，不要 markdown 代码块）：

{{
  "plans": [
    {{
      "plan_id": "plan_1",
      "title": "方案标题（简洁有吸引力）",
      "summary": "2-3句方案概述",
      "scenario_match": "场景适配度说明，如'完全满足亲子需求，室内为主，节奏轻松'",
      "style_tags": ["亲子","室内","轻松"],
      "weather_context": {{"condition": "从 weather.extra.condition 逐字复制", "temperature": "从 weather.extra.temperature 逐字复制", "advice": "从 weather.extra.advice 逐字复制", "impact": "从 weather.extra.impact 逐字复制"}},
      "timeline": [
        {{
          "time_range": "14:00-15:30",
          "activity_name": "搜索结果中真实的 name",
          "location": "搜索结果中真实的 full_address",
          "action_type": "activity" / "dining" / "shopping" / "transport" / "other",
          "action_required": true/false,
          "notes": "简短备注",
          "detail": {{
            "reason": "为什么推荐这个（结合用户约束）",
            "candidates": ["搜索结果中真实的备选name1", "搜索结果中真实的备选name2"],
            "transport": "环节间交通，如'步行8分钟(600m)'",
            "transport_from_user": "从用户位置到此地的交通，如'地铁15分钟'",
            "distance_from_user": "距用户距离，如'1.2km'",
            "prep_note": "出发前准备提示",
            "contingency": {{"trigger": "触发条件", "fallback_name": "搜索结果中真实的备选name", "fallback_location": "真实备选地址", "note": "说明"}}
          }}
        }}
      ],
      "budget_items": [
        {{"name": "门票", "category": "activity", "unit_price": 80, "quantity": {intent.people_count}, "subtotal": {80 * intent.people_count}, "note": "成人票×2+儿童票×1"}}
      ],
      "total_budget": 0,
      "highlights": ["亮点1", "亮点2"],
      "risk_notes": ["风险1", "风险2"],
      "contingency_overall": "整体应急预案说明"
    }}
  ],
  "recommendation": "推荐理由"
}}

注意：
1. activity_name 和 location 必须来自搜索结果，严禁编造"某手工DIY工作室""某甜品店"等占位名
2. weather_context 从 weather.extra 逐字复制，不能为空
3. budget_items 的 unit_price × quantity 应等于 subtotal
4. 总时长不超过 {intent.duration_hours} 小时
"""

    # ================================================================
    # 阶段2 解析
    # ================================================================

    def _parse_plans(self, data: dict, intent: ParsedIntent) -> list[Plan]:
        """将 LLM JSON 解析为 Plan 对象列表。"""
        plans = []
        for p in data.get("plans", []):
            # 解析天气
            wc = p.get("weather_context", {})
            weather_context = WeatherContext(
                condition=wc.get("condition", ""),
                temperature=wc.get("temperature", ""),
                advice=wc.get("advice", ""),
                impact=wc.get("impact", ""),
            )

            # 解析时间线
            timeline = []
            for slot in p.get("timeline", []):
                detail = None
                if slot.get("detail"):
                    d = slot["detail"]
                    cont = None
                    if d.get("contingency"):
                        c = d["contingency"]
                        cont = ContingencyPlan(
                            trigger=c.get("trigger", ""),
                            fallback_name=c.get("fallback_name", ""),
                            fallback_location=c.get("fallback_location", ""),
                            note=c.get("note", ""),
                        )
                    detail = SlotDetail(
                        reason=d.get("reason", ""),
                        candidates=d.get("candidates", []),
                        transport=d.get("transport", ""),
                        transport_from_user=d.get("transport_from_user", ""),
                        distance_from_user=d.get("distance_from_user", ""),
                        prep_note=d.get("prep_note", ""),
                        contingency=cont,
                    )

                timeline.append(TimelineSlot(
                    time_range=slot.get("time_range", "14:00-16:00"),
                    activity_name=slot.get("activity_name", ""),
                    location=slot.get("location", ""),
                    action_type=slot.get("action_type", "activity"),
                    action_required=slot.get("action_required", False),
                    notes=slot.get("notes", ""),
                    detail=detail,
                ))

            # 解析预算项
            budget_items = []
            for bi in p.get("budget_items", []):
                budget_items.append(BudgetItem(
                    name=bi.get("name", ""),
                    category=bi.get("category", "activity"),
                    unit_price=float(bi.get("unit_price", 0)),
                    quantity=int(bi.get("quantity", 1)),
                    subtotal=float(bi.get("subtotal", 0)),
                    note=bi.get("note", ""),
                ))

            plans.append(Plan(
                plan_id=p.get("plan_id", f"plan_{len(plans)+1}"),
                title=p.get("title", "方案"),
                summary=p.get("summary", ""),
                scenario_match=p.get("scenario_match", ""),
                style_tags=p.get("style_tags", []),
                weather_context=weather_context,
                timeline=timeline,
                budget_items=budget_items,
                total_budget=float(p.get("total_budget", 0)),
                highlights=p.get("highlights", []),
                risk_notes=p.get("risk_notes", []),
                contingency_overall=p.get("contingency_overall", ""),
            ))

        return plans

    # ================================================================
    # 阶段2b：后处理校验
    # ================================================================

    def _validate_and_fix_budget(self, plan: Plan):
        """校验预算项 subtotal 一致性，自动修正并计算总额。"""
        total = 0.0
        for item in plan.budget_items:
            expected = item.unit_price * item.quantity
            if abs(item.subtotal - expected) > 0.01:
                planner_logger.warning(
                    f"预算不一致: {item.name} subtotal={item.subtotal} != {item.unit_price}×{item.quantity}={expected}, 自动修正"
                )
                item.subtotal = expected
            total += item.subtotal
        plan.total_budget = round(total, 2)

    def _validate_timeline_duration(self, plan: Plan, max_hours: int):
        """校验时间线总时长不超过最大时长。"""
        if not plan.timeline or len(plan.timeline) < 2:
            return
        try:
            start = _parse_time(plan.timeline[0].time_range.split("-")[0])
            end = _parse_time(plan.timeline[-1].time_range.split("-")[1])
            duration_h = (end - start) / 60.0
            if duration_h > max_hours:
                planner_logger.warning(
                    f"时间线总长 {duration_h:.1f}h 超过限制 {max_hours}h: {plan.plan_id}"
                )
        except Exception:
            pass

    def _ensure_details_present(self, plan: Plan, intent: ParsedIntent):
        """为缺少 detail 的 slot 生成合理的默认 detail。"""
        for slot in plan.timeline:
            if slot.detail is None:
                # 从搜索摘要中无法直接匹配，使用占位值
                slot.detail = SlotDetail(
                    reason=f"根据您的{intent.scene}场景推荐",
                    transport="信息待补充",
                    transport_from_user="信息待补充",
                    distance_from_user="信息待补充",
                )

    # ================================================================
    # 搜索结果摘要（扩展版，含完整地址和天气详情）
    # ================================================================

    def _summarize_results(self, search_result: SearchResult, intent: ParsedIntent) -> dict:
        """提取搜索结果核心信息供 LLM 使用（含完整地址、天气详情、用户位置）。"""
        summary = {"user_location": intent.user_location, "user_address": intent.user_address}
        for sr in search_result.results:
            service_name = sr.service
            if service_name == "weather":
                if sr.candidates:
                    extra = sr.candidates[0].extra
                    summary["weather"] = {
                        "condition": extra.get("condition", ""),
                        "temperature": extra.get("temperature", ""),
                        "advice": extra.get("advice", ""),
                        "impact": extra.get("impact", ""),
                        "description": sr.candidates[0].description,
                    }
                else:
                    summary["weather"] = {"condition": "未知", "temperature": "", "advice": "请自行查看天气", "impact": ""}
            else:
                summary[service_name] = []
                # 按距离升序排列，优先展示最近的 POI
                sorted_candidates = sorted(sr.candidates, key=lambda c: c.distance_km or 999)
                for c in sorted_candidates[:5]:
                    summary[service_name].append({
                        "id": c.id,
                        "name": c.name,
                        "tags": c.tags,
                        "price_amount": c.price_amount,
                        "distance_km": c.distance_km,
                        "location": c.location,
                        "full_address": c.full_address or c.location,
                        "latitude": c.latitude,
                        "longitude": c.longitude,
                        "availability": c.availability,
                        "tel": c.extra.get("tel", ""),
                        "rating": c.extra.get("rating", ""),
                    })
        return summary

    # ================================================================
    # 降级方案
    # ================================================================

    def _generate_fallback_plan_set(self, intent: ParsedIntent) -> PlanSet:
        """当搜索失败时，生成纯文本建议方案。"""
        plans = [
            Plan(
                plan_id="fallback_1",
                title="轻松半日游 (备选)",
                summary="搜索服务暂时不可用，为您推荐以下建议方案",
                scenario_match="通用建议方案",
                weather_context=WeatherContext(condition="未知", temperature="", advice="请自行查看天气"),
                timeline=[
                    TimelineSlot(
                        time_range=f"{intent.start_time}-{self._add_hours(intent.start_time, 2)}",
                        activity_name="附近公园 / 商场",
                        location="半径 5km 内",
                        action_type="activity",
                        action_required=False,
                        notes="建议自行前往",
                        detail=SlotDetail(reason="通用娱乐选择", transport="信息暂缺"),
                    ),
                    TimelineSlot(
                        time_range=f"{self._add_hours(intent.start_time, 2)}-{self._add_hours(intent.start_time, intent.duration_hours)}",
                        activity_name="附近餐厅",
                        location="半径 5km 内",
                        action_type="dining",
                        action_required=False,
                        notes="建议提前电话确认",
                        detail=SlotDetail(reason="通用餐饮选择", transport="信息暂缺"),
                    ),
                ],
                total_budget=300.0,
                highlights=["无需预订，灵活安排"],
                risk_notes=["搜索服务暂时不可用，方案为默认推荐"],
            )
        ]
        return PlanSet(plans=plans, recommendation="建议方案1，搜索恢复后可重新规划", user_address=intent.user_address)

    @staticmethod
    def _add_hours(time_str: str, hours: int) -> str:
        parts = time_str.split(":")
        h = int(parts[0]) + hours
        return f"{h:02d}:{parts[1]}"

    # ================================================================
    # 执行计划生成
    # ================================================================

    async def create_execution_plan(self, chosen_plan: Plan) -> ExecutionPlan:
        """将用户选中的 Plan 转化为可执行的 ExecutionPlan。"""
        bookings = []
        action_counter = 0
        candidate_data = []

        for slot in chosen_plan.timeline:
            if slot.action_required:
                action_counter += 1
                if slot.action_type == "activity":
                    booking = BookingAction(
                        action_id=f"act_{action_counter}",
                        service="activity",
                        action_type="order",
                        target_name=slot.activity_name,
                        payload={
                            "action": "order",
                            "activity_name": slot.activity_name,
                            "people_count": 3,
                            "time": slot.time_range.split("-")[0],
                        },
                        fallback_target="亲子烘焙工坊",
                        fallback_payload={
                            "action": "order",
                            "activity_name": "亲子烘焙工坊",
                            "people_count": 3,
                        },
                    )
                elif slot.action_type == "dining":
                    booking = BookingAction(
                        action_id=f"act_{action_counter}",
                        service="restaurant",
                        action_type="reserve",
                        target_name=slot.activity_name,
                        payload={
                            "action": "reserve",
                            "restaurant_name": slot.activity_name,
                            "people_count": 3,
                            "time": slot.time_range.split("-")[0],
                        },
                        fallback_target="小鹿亲子餐厅",
                        fallback_payload={
                            "action": "reserve",
                            "restaurant_name": "小鹿亲子餐厅",
                            "people_count": 3,
                            "time": slot.time_range.split("-")[0],
                        },
                    )
                else:
                    booking = BookingAction(
                        action_id=f"act_{action_counter}",
                        service="activity",
                        action_type="order",
                        target_name=slot.activity_name,
                        payload={},
                    )
                bookings.append(booking)
                candidate_data.append(f"{slot.time_range} {slot.activity_name} ({slot.location})")

        activities_text = " → ".join(candidate_data) if candidate_data else "下午出去玩"
        final_message = f"搞定了，下午{chosen_plan.title}，安排如下：{activities_text}，都订好了，你看看行不？"

        return ExecutionPlan(
            plan_id=chosen_plan.plan_id,
            summary=chosen_plan.summary,
            timeline=chosen_plan.timeline,
            bookings=bookings,
            final_message=final_message,
        )


# ================================================================
# 工具函数
# ================================================================

def _parse_time(time_str: str) -> int:
    """'HH:MM' → 距零点分钟数"""
    h, m = time_str.strip().split(":")
    return int(h) * 60 + int(m)