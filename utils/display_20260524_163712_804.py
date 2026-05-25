"""CLI 美化输出模块，基于 rich。"""
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
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
            action_icon = "[bold]需预订[/bold]" if slot.action_required else ""
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

    console.print(f"[bold green]推荐:[/bold green] {plan_set.recommendation}")


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
