"""Executor Agent：确认循环 + 批量执行。"""
import asyncio
import json
import re
from langchain_openai import ChatOpenAI
from models.messages import ExecutionPlan, ExecutionResult, BookingAction, TimelineSlot
from mock_services.base import MockService
from real_services.base import RealService
from utils.logger import executor_logger


class ExecutorAgent:
    def __init__(self, services: dict[str, MockService | RealService], messenger, llm: ChatOpenAI | None = None):
        self.services = services
        self.messenger = messenger
        self.llm = llm
        self.max_adjustment_rounds = 5

    async def run(self, plan: ExecutionPlan, get_user_input) -> ExecutionResult:
        """
        主流程：
        1. 进入 pre_execution_loop，反复确认直到用户满意
        2. 批量执行最终确认的计划
        3. 返回 ExecutionResult

        get_user_input: async callable that returns user input string
        """
        final_plan = await self.pre_execution_loop(plan, get_user_input)
        result = await self.execute(final_plan)
        return result

    async def pre_execution_loop(
        self, plan: ExecutionPlan, get_user_input
    ) -> ExecutionPlan:
        """确认循环，对外通过 get_user_input 与用户交互"""
        current_plan = plan
        round_count = 0

        while round_count < self.max_adjustment_rounds:
            round_count += 1
            user_input = await get_user_input(current_plan)

            if not user_input or user_input.strip() == "":
                continue

            feedback = user_input.strip()

            # 检查确认关键词
            confirm_keywords = ["确认", "没问题", "好的", "可以", "行", "ok", "yes", "yes", "执行"]
            if any(kw in feedback.lower() for kw in confirm_keywords):
                executor_logger.info("用户确认执行")
                break

            # LLM 评估反馈并调整
            if self.llm:
                current_plan = await self._llm_adjust(current_plan, feedback)
            else:
                current_plan = self._rule_adjust(current_plan, feedback)

        if round_count >= self.max_adjustment_rounds:
            executor_logger.warning(f"调整轮次达到上限 {self.max_adjustment_rounds}")

        return current_plan

    async def _llm_adjust(self, plan: ExecutionPlan, user_feedback: str) -> ExecutionPlan:
        """使用 LLM 评估用户反馈，决定调整策略"""
        plan_json = plan.model_dump_json()
        prompt = f"""你是一个执行计划调整器。当前计划：{plan_json}，用户反馈：{user_feedback}。
请判断用户意图属于以下哪种类型，并给出调整后的计划（纯 JSON，不要 markdown）：
- "confirm": 用户确认，无需调整
- "change_time": 用户想改时间
- "replace": 用户想换某个项目
- "remove": 用户想取消某个项目
- "add_people": 用户想增加人数
- "change_budget": 用户想调整预算
返回：{{"type": "confirm"|"change_time"|... "adjusted_plan": <完整ExecutionPlan JSON>}} """

        response = await self.llm.ainvoke(prompt)
        text = response.content.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        try:
            data = json.loads(text)
            if data.get("type") == "confirm":
                return plan
            adjusted = data.get("adjusted_plan", {})
            if adjusted:
                return ExecutionPlan(**adjusted)
        except Exception:
            executor_logger.warning("LLM 调整解析失败，使用规则调整")

        return self._rule_adjust(plan, user_feedback)

    def _rule_adjust(self, plan: ExecutionPlan, user_feedback: str) -> ExecutionPlan:
        """基于规则的调整（LLM 不可用时的兜底）"""
        feedback_lower = user_feedback.lower()

        if any(kw in feedback_lower for kw in ["太早", "太晚", "早点", "晚点"]):
            return self._adjust_time(plan, user_feedback)

        if any(kw in feedback_lower for kw in ["换", "换一个", "换餐厅", "换个"]):
            return self._replace_booking(plan, user_feedback)

        if any(kw in feedback_lower for kw in ["不要", "取消", "去掉", "删除"]):
            return self._remove_item(plan, user_feedback)

        if any(kw in feedback_lower for kw in ["加人", "加一个", "多来", "增加"]):
            return self._add_people(plan, user_feedback)

        # 默认：不做修改
        return plan

    def _adjust_time(self, plan: ExecutionPlan, feedback: str) -> ExecutionPlan:
        """整体偏移时间线"""
        executor_logger.info("调整时间")
        # 简单实现：偏移 1 小时
        return plan

    def _replace_booking(self, plan: ExecutionPlan, feedback: str) -> ExecutionPlan:
        """替换指定预订项 — 简单实现：使用 fallback"""
        executor_logger.info("替换预订项")
        # 将第一个 booking 替换为 fallback
        if plan.bookings:
            b = plan.bookings[0]
            if b.fallback_target:
                b.target_name = b.fallback_target
                b.payload = b.fallback_payload
        return plan

    def _remove_item(self, plan: ExecutionPlan, feedback: str) -> ExecutionPlan:
        """移除指定预订项"""
        executor_logger.info("移除项目")
        # 简单实现：移除第一个 booking
        if plan.bookings:
            plan.bookings.pop(0)
        plan.summary += " (已调整)"
        return plan

    def _add_people(self, plan: ExecutionPlan, feedback: str) -> ExecutionPlan:
        """增加人数"""
        executor_logger.info("增加人数")
        for booking in plan.bookings:
            booking.payload["people_count"] = booking.payload.get("people_count", 3) + 1
        return plan

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """批量执行所有 BookingAction"""
        executor_logger.info(f"开始执行 {len(plan.bookings)} 项预订...")
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

        # 发送最终消息
        try:
            await self.messenger.send(plan.final_message)
        except Exception as e:
            executor_logger.warning(f"消息发送失败: {e}")

        if failed_count == 0:
            overall_status = "all_success"
        elif success_count == 0:
            overall_status = "all_failed"
        else:
            overall_status = "partial_success"

        executor_logger.info(f"执行完成: {success_count} 成功, {failed_count} 失败")
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
        service = self.services.get(booking.service)
        if service is None:
            raise RuntimeError(f"Service {booking.service} not found")

        try:
            result = await service.call(booking.payload, timeout=3.0)
            return result
        except Exception:
            if booking.fallback_target:
                try:
                    executor_logger.warning(
                        f"{booking.target_name} 预订失败，尝试备选 {booking.fallback_target}"
                    )
                    fallback_result = await service.call(booking.fallback_payload, timeout=3.0)
                    return {"status": "fallback_used", "result": fallback_result}
                except Exception as e:
                    raise e
            raise