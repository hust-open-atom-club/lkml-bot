"""订阅子系统命令模块"""

from nonebot import on_message
import re
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
        logger.info("Subscribe command handler triggered, text: '%s'", text)

        command_text = extract_command(text, "/subscribe") or extract_command(
            text, "/sub"
        )
        if command_text is None:
            logger.debug(
                "Text does not match '/subscribe' or '/sub', returning. Text: '%s'",
                text,
            )
            return

        parts = command_text.split()
        if len(parts) < 2:
            await SubscribeCmd.finish(
                "subscribe: 缺少参数\n用法: @机器人 /subscribe|/sub <subsystem...>\n子命令: available | subscribed"
            )
            return

        action = parts[1].strip().lower()
        logger.info("Processing subscribe request, action: %s", action)

        # 获取用户信息
        user_id, user_name = await get_user_info_or_finish(event, SubscribeCmd)

        if action == "list":
            await _handle_subscribe_list()
            return

        await _handle_subscribe_batch(action, parts, user_id, user_name)
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error("Unexpected error in handle_subscribe: %s", e, exc_info=True)
        await SubscribeCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


async def _handle_subscribe_list() -> None:
    """处理订阅列表查询逻辑。"""
    try:
        config = get_config()
        supported = config.get_supported_subsystems()
        subscribed = await lkml_service.get_subscribed_subsystems()
        await SubscribeCmd.finish(
            "可订阅的子系统: "
            + ", ".join(supported)
            + "\n"
            + "已订阅的子系统: "
            + ", ".join(subscribed)
        )
    except FinishedException:
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error("Error in list subcommands: %s", e, exc_info=True)
        await SubscribeCmd.finish(f"❌ 列表查询时发生错误: {str(e)}")


async def _handle_subscribe_batch(
    _action: str, parts: list[str], user_id: str, user_name: str
) -> None:
    """处理批量订阅逻辑。"""
    raw_args = " ".join(parts[1:])
    targets = [x.strip() for x in re.split(r"[,\s]+", raw_args) if x.strip()]
    if not targets:
        await SubscribeCmd.finish("subscribe: 子系统名称不能为空")
        return

    logger.info("Processing batch subscribe for subsystems: %s", targets)

    try:
        config = get_config()
        supported = set(config.get_supported_subsystems())
        prev_subscribed = set(await lkml_service.get_subscribed_subsystems())

        result_lines = await _subscribe_targets(
            targets, supported, prev_subscribed, user_id, user_name
        )
        await SubscribeCmd.finish("\n".join(result_lines))
    except FinishedException:
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error("Error in batch subscribe: %s", e, exc_info=True)
        await SubscribeCmd.finish(f"❌ 订阅时发生错误: {str(e)}")


async def _subscribe_targets(
    targets: list[str],
    supported: set[str],
    prev_subscribed: set[str],
    user_id: str,
    user_name: str,
) -> list[str]:
    """执行具体的订阅循环并返回结果行。"""
    newly_subscribed: list[str] = []
    already_subscribed: list[str] = []
    unsupported: list[str] = []
    failed: list[str] = []

    for name in sorted(set(targets)):
        if name not in supported:
            unsupported.append(name)
            continue
        try:
            ok = await lkml_service.subscribe_subsystem(
                operator_id=str(user_id),
                operator_name=str(user_name),
                subsystem_name=name,
            )
            if not ok:
                failed.append(name)
            elif name in prev_subscribed:
                already_subscribed.append(name)
            else:
                newly_subscribed.append(name)
        except FinishedException:
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error("Error subscribing %s: %s", name, e, exc_info=True)
            failed.append(name)

    lines: list[str] = ["subscribe: 批量订阅结果"]
    if newly_subscribed:
        lines.append("✅ 新订阅: " + ", ".join(newly_subscribed))
    if already_subscribed:
        lines.append("ℹ️ 已订阅: " + ", ".join(already_subscribed))
    if unsupported:
        lines.append("❌ 不支持: " + ", ".join(unsupported))
    if failed:
        lines.append("⚠️ 失败: " + ", ".join(failed))

    return lines


# 在导入时注册命令元信息（非管理员命令）
register_command(
    name="subscribe",
    usage="/(subscribe | sub) <subsystem...> | list",
    description="订阅子系统；查询可订阅/已订阅列表",
    admin_only=False,
)
