"""停止监控命令模块"""

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

# 仅当消息 @ 到机器人，并且以 "/stop-monitor" 开头时处理
# 优先级设为 50，高于 help (40)，确保优先匹配
StopMonitorCmd = on_message(rule=to_me(), priority=50, block=False)


@StopMonitorCmd.handle()
async def handle_stop_monitor(event: Event, message: Message = EventMessage()):
    """处理停止监控命令"""
    try:
        # 获取消息纯文本
        text = message.extract_plain_text().strip()
        logger.info(f"Stop monitor command handler triggered, text: '{text}'")

        # 检查命令匹配
        command_text = extract_command(text, "/stop-monitor")
        if command_text is None:
            logger.debug(
                f"Text does not match '/stop-monitor', returning. Text: '{text}'"
            )
            return

        # 检查权限
        if not check_admin(event):
            await StopMonitorCmd.finish("❌ 权限不足：此命令仅限管理员使用")
            return

        # 获取用户信息
        user_id, user_name = await get_user_info_or_finish(event, StopMonitorCmd)

        # 调用服务停止监控
        try:
            scheduler = get_scheduler()
            success = await lkml_service.stop_monitoring(
                operator_id=str(user_id),
                operator_name=str(user_name),
                scheduler=scheduler,
            )

            if success:
                await StopMonitorCmd.finish("✅ 成功停止邮件列表监控！")
            else:
                await StopMonitorCmd.finish("❌ 停止监控失败。监控可能已经停止。")
        except FinishedException:  # pylint: disable=try-except-raise
            # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error(f"Error in stop_monitoring: {e}", exc_info=True)
            await StopMonitorCmd.finish(f"❌ 停止监控时发生错误: {str(e)}")
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Unexpected error in handle_stop_monitor: {e}", exc_info=True)
        await StopMonitorCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


# 在导入时注册命令元信息（管理员命令）
register_command(
    name="stop-monitor",
    usage="/stop-monitor",
    description="停止邮件列表监控",
    admin_only=True,
)
