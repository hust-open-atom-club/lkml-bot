"""取消订阅子系统命令模块"""

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.service import LKMLService
from ..shared import extract_command, get_user_info_or_finish, register_command

lkml_service = LKMLService()


# 仅当消息 @ 到机器人，并且以 "/unsubscribe" 开头时处理
UnsubscribeCmd = on_message(rule=to_me(), priority=50, block=False)


@UnsubscribeCmd.handle()
async def handle_unsubscribe(event: Event, message: Message = EventMessage()):
    """处理取消订阅命令"""
    try:
        text = message.extract_plain_text().strip()

        # 检查命令匹配
        command_text = extract_command(text, "/unsubscribe")
        if command_text is None:
            logger.debug(
                f"Text does not match '/unsubscribe', returning. Text: '{text}'"
            )
            return

        # 解析命令参数
        parts = command_text.split()
        if len(parts) < 2:
            await UnsubscribeCmd.finish(
                "unsubscribe: 缺少 <subsystem>\n用法: @机器人 /unsubscribe <subsystem>"
            )
            return

        subsystem = parts[1].strip()

        if not subsystem:
            await UnsubscribeCmd.finish("unsubscribe: 子系统名称不能为空")
            return

        # 获取用户信息
        user_id, user_name = await get_user_info_or_finish(event, UnsubscribeCmd)

        # 调用服务进行退订
        try:
            success = await lkml_service.unsubscribe_subsystem(
                operator_id=str(user_id),
                operator_name=str(user_name),
                subsystem_name=subsystem,
            )

            if success:
                await UnsubscribeCmd.finish(f"✅ 已取消订阅子系统: {subsystem}")
            else:
                await UnsubscribeCmd.finish("❌ 取消订阅失败，子系统可能不存在或未订阅")
        except FinishedException:  # pylint: disable=try-except-raise
            # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error(f"Error in unsubscribe_subsystem: {e}", exc_info=True)
            await UnsubscribeCmd.finish(f"❌ 取消订阅时发生错误: {str(e)}")
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Unexpected error in handle_unsubscribe: {e}", exc_info=True)
        await UnsubscribeCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


# 在导入时注册命令元信息（非管理员命令）
register_command(
    name="unsubscribe",
    usage="/unsubscribe <subsystem>",
    description="取消订阅一个子系统的邮件列表",
    admin_only=False,
)
