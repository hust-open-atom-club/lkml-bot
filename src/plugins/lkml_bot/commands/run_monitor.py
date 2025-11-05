"""立即执行监控命令模块"""

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.scheduler import get_scheduler
from ..shared import (
    check_admin,
    extract_command,
    get_user_info_or_finish,
    register_command,
)

# 仅当消息 @ 到机器人，并且以 "/run-monitor" 开头时处理
# 优先级设为 50，高于 help (40)，确保优先匹配
RunMonitorCmd = on_message(rule=to_me(), priority=50, block=False)


@RunMonitorCmd.handle()
async def handle_run_monitor(event: Event, message: Message = EventMessage()):
    """处理立即执行监控命令"""
    try:
        # 获取消息纯文本
        text = message.extract_plain_text().strip()
        logger.info(f"Run monitor command handler triggered, text: '{text}'")

        # 检查命令匹配
        command_text = extract_command(text, "/run-monitor")
        if command_text is None:
            logger.debug(
                f"Text does not match '/run-monitor', returning. Text: '{text}'"
            )
            return

        # 检查权限
        if not check_admin(event):
            await RunMonitorCmd.finish("❌ 权限不足：此命令仅限管理员使用")
            return

        # 获取用户信息
        _user_id, user_name = await get_user_info_or_finish(event, RunMonitorCmd)

        # 立即执行监控任务
        try:
            scheduler = get_scheduler()
            logger.info(f"Operator {user_name} triggered run-once monitoring")

            # 运行一次监控任务
            monitoring_result = await scheduler.run_once()

            # 构建响应消息
            stats = monitoring_result.statistics
            lines = [
                "✅ 监控任务执行完成！",
                f"处理了 {stats.processed_subsystems}/"
                f"{stats.total_subsystems} 个子系统",
            ]

            if stats.total_new_count > 0:
                lines.append(f"发现 {stats.total_new_count} 条新邮件")

            if stats.total_reply_count > 0:
                lines.append(f"发现 {stats.total_reply_count} 条回复")

            if stats.total_new_count == 0 and stats.total_reply_count == 0:
                lines.append("没有发现新的邮件更新")

            await RunMonitorCmd.finish("\n".join(lines))

        except FinishedException:  # pylint: disable=try-except-raise
            # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error(f"Error in run_once monitoring: {e}", exc_info=True)
            await RunMonitorCmd.finish(f"❌ 执行监控任务时发生错误: {str(e)}")
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Unexpected error in handle_run_monitor: {e}", exc_info=True)
        await RunMonitorCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


# 在导入时注册命令元信息（管理员命令）
register_command(
    name="run-monitor",
    usage="/run-monitor",
    description="立即执行一次邮件列表监控任务",
    admin_only=True,
)
