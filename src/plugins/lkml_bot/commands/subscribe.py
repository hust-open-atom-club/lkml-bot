"""订阅子系统命令模块"""

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.service import LKMLService
from ..config import get_config
from ..shared import extract_command, get_user_info_or_finish, register_command

lkml_service = LKMLService()

# 仅当消息 @ 到机器人，并且以 "/subscribe" 开头时处理
# 优先级设为 50，高于 help (40)，确保优先匹配
SubscribeCmd = on_message(rule=to_me(), priority=50, block=False)


@SubscribeCmd.handle()
async def handle_subscribe(event: Event, message: Message = EventMessage()):
    """处理订阅命令

    Args:
        event: 事件对象
        message: 消息对象
    """
    try:
        # 获取消息纯文本（Discord 适配器会自动去除 mention）
        text = message.extract_plain_text().strip()
        logger.info(f"Subscribe command handler triggered, text: '{text}'")

        # 检查命令匹配
        command_text = extract_command(text, "/subscribe")
        if command_text is None:
            logger.debug(f"Text does not match '/subscribe', returning. Text: '{text}'")
            return

        # 解析命令参数
        parts = command_text.split()
        if len(parts) < 2:
            await SubscribeCmd.finish(
                "subscribe: 缺少 <subsystem>\n用法: @机器人 /subscribe <subsystem>"
            )
            return

        subsystem = parts[1].strip()
        logger.info(f"Processing subscribe request for subsystem: {subsystem}")

        if not subsystem:
            await SubscribeCmd.finish("subscribe: 子系统名称不能为空")
            return

        # 获取用户信息
        user_id, user_name = await get_user_info_or_finish(event, SubscribeCmd)

        # 调用服务进行订阅
        try:
            success = await lkml_service.subscribe_subsystem(
                operator_id=str(user_id),
                operator_name=str(user_name),
                subsystem_name=subsystem,
            )

            if success:
                await SubscribeCmd.finish(f"✅ 已订阅子系统: {subsystem}")
                return

            # 订阅失败，检查原因
            config = get_config()
            supported = config.get_supported_subsystems()
            if subsystem not in supported:
                await SubscribeCmd.finish(
                    f"❌ 不支持的子系统: {subsystem}\n"
                    f"支持的子系统: {', '.join(supported)}"
                )
            else:
                await SubscribeCmd.finish("❌ 订阅失败，请稍后重试")
        except FinishedException:  # pylint: disable=try-except-raise
            # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error(f"Error in subscribe_subsystem: {e}", exc_info=True)
            await SubscribeCmd.finish(f"❌ 订阅时发生错误: {str(e)}")
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Unexpected error in handle_subscribe: {e}", exc_info=True)
        await SubscribeCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


# 在导入时注册命令元信息（非管理员命令）
register_command(
    name="subscribe",
    usage="/subscribe <subsystem>",
    description="订阅一个子系统的邮件列表",
    admin_only=False,
)
