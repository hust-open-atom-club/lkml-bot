"""启动监控命令模块"""

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.scheduler import get_scheduler
from lkml.service import LKMLService
from ..shared import (
    check_admin,
    extract_command,
    get_user_info_or_finish,
    register_command,
)

lkml_service = LKMLService()

# 仅当消息 @ 到机器人，并且以 "/start-monitor" 开头时处理
# 优先级设为 50，高于 help (40)，确保优先匹配
StartMonitorCmd = on_message(rule=to_me(), priority=50, block=False)


@StartMonitorCmd.handle()
async def handle_start_monitor(event: Event, message: Message = EventMessage()):
    """处理启动监控命令"""
    try:
        # 获取消息纯文本
        text = message.extract_plain_text().strip()
        logger.info(f"Start monitor command handler triggered, text: '{text}'")

        # 检查命令匹配
        command_text = extract_command(text, "/start-monitor")
        if command_text is None:
            logger.debug(
                f"Text does not match '/start-monitor', returning. Text: '{text}'"
            )
            return

        # 检查权限
        if not check_admin(event):
            await StartMonitorCmd.finish("❌ 权限不足：此命令仅限管理员使用")
            return

        # 获取用户信息
        user_id, user_name = await get_user_info_or_finish(event, StartMonitorCmd)

        # 调用服务启动监控
        try:
            scheduler = get_scheduler()
            success = await lkml_service.start_monitoring(
                operator_id=str(user_id),
                operator_name=str(user_name),
                scheduler=scheduler,
            )

            if success:
                await StartMonitorCmd.finish("✅ 成功启动邮件列表监控！")
            else:
                await StartMonitorCmd.finish("❌ 启动监控失败。监控可能已经在运行中。")
        except FinishedException:  # pylint: disable=try-except-raise
            # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error(f"Error in start_monitoring: {e}", exc_info=True)
            await StartMonitorCmd.finish(f"❌ 启动监控时发生错误: {str(e)}")
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Unexpected error in handle_start_monitor: {e}", exc_info=True)
        await StartMonitorCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


# 在导入时注册命令元信息（管理员命令）
register_command(
    name="start-monitor",
    usage="/start-monitor",
    description="启动邮件列表监控",
    admin_only=True,
)
