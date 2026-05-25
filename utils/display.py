"""CLI 美化输出模块，基于 rich。"""
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from models.messages import PlanSet, Plan, TimelineSlot, WeatherContext, BudgetItem, ContingencyPlan, SlotDetail

console = Console()


def print_header(title: str):
    """打印系统标题"""
    console.print(Panel(
        f"[bold cyan]{title}[/bold cyan]",
        border_style="cyan",
        box=box.DOUBLE,
        expand=False,
    ))


def print_intent(intent):
    """打印解析出的意图"""
    console.print(Panel(
        f"[bold green]解析意图[/bold green]\n"
        f"场景: {intent.scene}\n"
        f"人数: {intent.people_count}\n"
        f"约束: {', '.join(intent.constraints)}\n"
        f"位置: {intent.user_address or '未指定'}",
        border_style="green",
        box=box.SQUARE,
    ))


def print_agent_header(agent_name: str, action: str):
    """打印 Agent 操作头部"""
    console.print(Panel(
        f"[bold cyan]{agent_name}[/bold cyan] → {action}",
        border_style="cyan",
        box=box.ROUNDED,
    ))


def _print_weather(weather: WeatherContext):
    """渲染天气区块"""
    if not weather.condition:
        return
    console.print(Panel(
        f"[bold cyan]天气[/bold cyan]\n"
        f"🌤  {weather.condition} {weather.temperature}\n"
        f"💬  {weather.advice}\n"
        f"📝  {weather.impact}",
        border_style="cyan",
        box=box.ROUNDED,
    ))


def _print_timeline(plan: Plan):
    """渲染时间线区块"""
    for i, slot in enumerate(plan.timeline, 1):
        # 基础信息
        time_text = f"[bold cyan]{slot.time_range}[/bold cyan]"
        activity_text = f"[bold white]{slot.activity_name}[/bold white]"
        location_text = f"📍 {slot.location}"
        
        # 距离信息
        distance_text = ""
        if slot.detail and slot.detail.distance_from_user:
            distance_text = f"（距您 {slot.detail.distance_from_user}）"
        
        # 第一行
        console.print(f"{time_text}  {activity_text}  {location_text}{distance_text}")
        
        # 详情行
        if slot.detail:
            detail = slot.detail
            if detail.reason:
                console.print(f"   🏷 推荐理由：{detail.reason}")
            if detail.transport_from_user:
                console.print(f"   🚗 交通：{detail.transport_from_user}")
            if detail.transport:
                console.print(f"   🚗 环节间：{detail.transport}")
            if detail.candidates:
                console.print(f"   🔄 备选：{', '.join(detail.candidates)}")
            if detail.prep_note:
                console.print(f"   ⚠️ 提示：{detail.prep_note}")
            if detail.contingency:
                cont = detail.contingency
                console.print(f"   📋 预案：{cont.trigger} → {cont.fallback_name}（{cont.fallback_location}）")
        
        console.print()


def _print_transport_connections(plan: Plan):
    """渲染交通衔接区块"""
    if not plan.timeline or len(plan.timeline) < 2:
        return
    
    console.print(Panel(
        "[bold cyan]交通衔接[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
    ))
    
    # 用户位置到第一个地点
    first = plan.timeline[0]
    if first.detail and first.detail.transport_from_user:
        console.print(f"   📍 您的位置 → {first.activity_name}：{first.detail.transport_from_user}")
    
    # 地点间交通
    for i in range(len(plan.timeline) - 1):
        curr = plan.timeline[i]
        next_slot = plan.timeline[i + 1]
        if curr.detail and curr.detail.transport:
            console.print(f"   📍 {curr.activity_name} → {next_slot.activity_name}：{curr.detail.transport}")
    
    console.print()


def _print_budget_items(plan: Plan):
    """渲染预算明细区块"""
    if not plan.budget_items:
        return
    
    table = Table(title="预算明细", box=box.ROUNDED)
    table.add_column("项目", style="white")
    table.add_column("类别", style="dim")
    table.add_column("单价×数量", style="cyan")
    table.add_column("小计", style="green")
    table.add_column("备注", style="yellow")
    
    for item in plan.budget_items:
        unit_text = f"¥{item.unit_price}×{item.quantity}"
        subtotal_text = f"¥{item.subtotal}"
        table.add_row(
            item.name,
            item.category,
            unit_text,
            subtotal_text,
            item.note,
        )
    
    console.print(table)
    console.print(f"[bold green]合计：¥{plan.total_budget}[/bold green]\n")


def _print_highlights_risks(plan: Plan):
    """渲染亮点和风险区块"""
    if plan.highlights:
        console.print(Panel(
            "[bold cyan]亮点[/bold cyan]\n" + "\n".join(f"• {h}" for h in plan.highlights),
            border_style="cyan",
            box=box.ROUNDED,
        ))
    
    if plan.risk_notes:
        console.print(Panel(
            "[bold yellow]风险提示[/bold yellow]\n" + "\n".join(f"• {r}" for r in plan.risk_notes),
            border_style="yellow",
            box=box.ROUNDED,
        ))


def _print_contingency_overall(plan: Plan):
    """渲染整体预案区块"""
    if plan.contingency_overall:
        console.print(Panel(
            "[bold magenta]整体预案[/bold magenta]\n" + plan.contingency_overall,
            border_style="magenta",
            box=box.ROUNDED,
        ))


def print_plan_set(plan_set: PlanSet):
    """打印方案集（新版）"""
    for i, plan in enumerate(plan_set.plans, 1):
        # 方案标题区
        tags_text = ""
        if plan.style_tags:
            tags_text = f" [dim][{' '.join(plan.style_tags)}][/dim]"
        
        console.print(Panel(
            f"[bold cyan]方案 {i}: {plan.title}[/bold cyan]{tags_text}\n"
            f"[italic]\"{plan.scenario_match}\"[/italic]",
            border_style="cyan",
            box=box.DOUBLE,
        ))
        
        # 用户位置
        if plan_set.user_address:
            console.print(f"[dim]📍 基于您的位置：{plan_set.user_address}[/dim]\n")
        
        # 天气
        _print_weather(plan.weather_context)
        
        # 时间线区块
        console.print(Panel(
            "[bold cyan]时间线[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        ))
        _print_timeline(plan)
        
        # 交通衔接
        _print_transport_connections(plan)
        
        # 预算明细
        _print_budget_items(plan)
        
        # 亮点和风险
        _print_highlights_risks(plan)
        
        # 整体预案
        _print_contingency_overall(plan)
        
        console.print()  # 方案间空行
    
    # 推荐
    if plan_set.recommendation:
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
        console.print(f"\n[bold]已发送消息:[/bold]\n{result.final_message}")