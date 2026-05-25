#!/usr/bin/env python3
"""美团Hackson主入口：支持交互模式和演示模式（v2.0）。
新增：位置收集交互步骤。
"""
import asyncio
import sys
import argparse
from typing import Optional

from langchain_openai import ChatOpenAI
from config.settings import settings
from utils.logger import setup_global_logger, main_logger
from utils.display import print_header, print_intent, print_plan_set, print_execution_result
# 混合真实 API + Mock 服务
from real_services.restaurant import RealRestaurantService
from real_services.weather import RealWeatherService
from real_services.activity import RealActivityService
from real_services.messenger import RealMessengerService
from mock_services.flower import FlowerService
from agents.planner import PlannerAgent
from agents.searcher import SearcherAgent
from agents.executor import ExecutorAgent
from agents.memory import MemoryAgent


class DemoInputProvider:
    """演示模式的输入提供器"""
    def __init__(self, demo_type: str):
        self.demo_type = demo_type
        self.step = 0
        self.demo_inputs = {
            "family": [
                "朝阳大悦城",  # Q1: 位置
                "1",            # Q2: 亲子
                "",             # Q3: 时间（默认14:00）
                "4",            # Q4: 氛围（地道老店）
                "",             # Q5: 饮食偏好（跳过）
                "2",            # Q6: 预算（中等）
                "",             # Q7: 距离（默认10km）
                "带5岁孩子",    # Q8: 特殊需求
                "1",            # 选择方案1
                "确认",         # 确认执行
            ],
            "friends": [
                "三里屯",       # Q1: 位置
                "2",            # Q2: 朋友
                "",             # Q3: 时间（默认14:00）
                "1",            # Q4: 氛围（热闹）
                "",             # Q5: 饮食偏好（跳过）
                "3",            # Q6: 预算（高）
                "",             # Q7: 距离（默认10km）
                "",             # Q8: 特殊需求（跳过）
                "1",            # 选择方案1
                "确认",         # 确认执行
            ],
        }

    async def __call__(self, plan=None) -> str:
        """模拟用户输入"""
        if self.step >= len(self.demo_inputs[self.demo_type]):
            return "exit"
        user_input = self.demo_inputs[self.demo_type][self.step]
        self.step += 1
        if plan is None:
            print(f"[Demo] 用户输入: {user_input}")
        return user_input


class InteractiveInputProvider:
    """交互模式的输入提供器"""
    async def __call__(self, plan=None) -> str:
        """从标准输入读取用户反馈"""
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            return line.strip()
        except (KeyboardInterrupt, EOFError):
            return "退出"


async def main_loop(demo: Optional[str] = None):
    """主循环：初始化所有组件并执行完整流程"""
    # 1. 初始化
    print_header("美团Hackson - 智能活动规划系统")
    main_logger.info("系统初始化...")

    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.2,
    )

    services = {
        "restaurant": RealRestaurantService(),
        "activity": RealActivityService(),
        "weather": RealWeatherService(),
        "flower": FlowerService(),
    }
    messenger = RealMessengerService()

    memory_agent = MemoryAgent()
    planner = PlannerAgent(llm, memory_agent)
    searcher = SearcherAgent(services)
    executor = ExecutorAgent(services, messenger, llm)

    # 2. 输入模式
    if demo:
        main_logger.info(f"演示模式: {demo}")
        input_provider = DemoInputProvider(demo)
        # 演示模式下自然语言输入仅做辅助，结构化回答（Q2-Q8）提供完整信息
        user_input = f"周末下午"
        main_logger.info(f"用户输入（演示）: {user_input}")
    else:
        print("\n请描述您的活动需求（例如：'下午想带孩子出去玩，找个地方吃饭'）:")
        input_provider = InteractiveInputProvider()
        user_input = await input_provider(None)

    if not user_input or user_input.lower() in ["退出", "exit", "quit"]:
        main_logger.info("用户退出")
        return

    # 3. 位置收集（Q1 - 在意图解析前先获取位置）
    main_logger.info("位置收集...")
    from models.messages import ParsedIntent
    empty_intent = ParsedIntent(
        scene="family",
        people_count=3,
        duration_hours=4,
        max_distance_km=10,
        start_time="14:00",
    )
    intent_with_location = await planner.collect_location(empty_intent, input_provider)

    # 4. 偏好收集（Q2-Q8 - 结构化提问）
    main_logger.info("偏好收集...")
    answers = await planner.ask_preferences(input_provider)

    # 5. 意图解析（LLM 综合原始输入 + 结构化回答）
    main_logger.info("意图解析...")
    intent = await planner.parse_intent(user_input, answers)
    # 合并步骤3收集到的位置信息
    intent.user_location = intent_with_location.user_location
    intent.user_address = intent_with_location.user_address

    print_intent(intent)

    # 5. 阶段1：搜索
    main_logger.info("搜索...")
    _, search_request = await planner.stage1_plan_search(intent)
    search_result = await searcher.search(search_request)
    main_logger.info(f"搜索结果: {search_result.overall_status}")

    # 6. 阶段2：方案生成
    main_logger.info("方案生成...")
    plan_set = await planner.stage2_generate_plans(intent, search_result)
    print_plan_set(plan_set)

    # 用户选择方案
    if demo:
        chosen_plan = plan_set.plans[0]
        main_logger.info(f"演示模式自动选择方案: {chosen_plan.plan_id}")
    else:
        print("\n请选择方案编号 (1, 2, 3) 或输入'取消': ")
        choice_input = await input_provider(None)
        if choice_input.lower() in ["取消", "cancel", "退出", "exit"]:
            main_logger.info("用户取消选择")
            return
        try:
            idx = int(choice_input.strip()) - 1
            if 0 <= idx < len(plan_set.plans):
                chosen_plan = plan_set.plans[idx]
            else:
                chosen_plan = plan_set.plans[0]
        except ValueError:
            chosen_plan = plan_set.plans[0]

    # 7. 转化为执行计划
    execution_plan = await planner.create_execution_plan(chosen_plan)

    # 8. 阶段3：确认循环 + 执行
    main_logger.info("确认与执行...")
    execution_result = await executor.run(execution_plan, input_provider)

    # 9. 记录偏好
    await memory_agent.record(
        execution_plan,
        scenario_tags=[intent.scene] + intent.constraints,
        rejected_items=[],
    )

    # 10. 输出结果
    print_execution_result(execution_result)

    main_logger.info("流程完成")


def main():
    parser = argparse.ArgumentParser(description="美团Hackson智能活动规划系统")
    parser.add_argument(
        "--demo",
        choices=["family", "friends"],
        help="运行演示模式（family: 亲子场景, friends: 朋友聚会）",
    )
    args = parser.parse_args()

    setup_global_logger()

    try:
        asyncio.run(main_loop(args.demo))
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
    except Exception as e:
        main_logger.error(f"系统错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()