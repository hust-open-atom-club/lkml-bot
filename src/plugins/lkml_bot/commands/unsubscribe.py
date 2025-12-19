"""取消订阅子系统命令模块"""

import re

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.service import LKMLService
from ..shared import extract_command, get_user_info_or_finish, register_command

lkml_service = LKMLService()


# 仅当消息 @ 到机器人，并且以 "/unsubscribe" 或 "/unsub" 开头时处理
UnsubscribeCmd = on_message(rule=to_me(), priority=50, block=False)


@UnsubscribeCmd.handle()
async def handle_unsubscribe(event: Event, message: Message = EventMessage()):
    """处理取消订阅命令（支持 /unsubscribe 和 /unsub，支持批量取消）"""
    try:
        text = message.extract_plain_text().strip()

        # 检查命令匹配：同时支持 /unsubscribe 和 /unsub
        command_text = extract_command(text, "/unsubscribe") or extract_command(
            text, "/unsub"
        )
        if command_text is None:
            logger.debug(
                "Text does not match '/unsubscribe' or '/unsub', returning. "
                f"Text: '{text}'"
            )
            return

        # 解析命令参数
        parts = command_text.split()
        if len(parts) == 0:
            await UnsubscribeCmd.finish(
                "unsubscribe: 缺少参数\n"
                "用法: @机器人 (unsubscribe | unsub) <subsystem...>\n"
                "示例:\n"
                "  /unsub linux-kernel\n"
                "  /unsub linux-kernel netdev dri-devel"
            )
            return

        # 支持批量：用空格或逗号分隔多个子系统名称
        # 第一个 token 是命令本身（/unsubscribe 或 /unsub），需要排除
        raw_args = " ".join(parts[1:])
        targets = [x.strip() for x in re.split(r"[,\s]+", raw_args) if x.strip()]
        if not targets:
            await UnsubscribeCmd.finish("unsubscribe: 子系统名称不能为空")
            return

        await _batch_unsubscribe(targets, event)
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Unexpected error in handle_unsubscribe: {e}", exc_info=True)
        await UnsubscribeCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


async def _batch_unsubscribe(targets: list[str], event: Event) -> None:
    """执行批量取消订阅逻辑并发送结果。"""
    # 获取用户信息
    user_id, user_name = await get_user_info_or_finish(event, UnsubscribeCmd)

    removed: list[str] = []
    failed: list[str] = []

    for name in sorted(set(targets)):
        try:
            ok = await lkml_service.unsubscribe_subsystem(
                operator_id=str(user_id),
                operator_name=str(user_name),
                subsystem_name=name,
            )
            if ok:
                removed.append(name)
            else:
                failed.append(name)
        except FinishedException:  # pylint: disable=try-except-raise
            raise
        except (ValueError, RuntimeError, AttributeError) as e:
            logger.error("Error unsubscribing %s: %s", name, e, exc_info=True)
            failed.append(name)

    # 根据结果构造反馈
    if len(targets) == 1:
        # 单个目标时，保持原来的简洁提示
        name = targets[0]
        if name in removed:
            await UnsubscribeCmd.finish(f"✅ 已取消订阅子系统: {name}")
        else:
            await UnsubscribeCmd.finish("❌ 取消订阅失败，子系统可能不存在或未订阅")
        return

    lines: list[str] = ["unsubscribe: 批量取消订阅结果"]
    if removed:
        lines.append("✅ 已取消: " + ", ".join(removed))
    if failed:
        lines.append("⚠️ 失败: " + ", ".join(failed))

    await UnsubscribeCmd.finish("\n".join(lines))


# 在导入时注册命令元信息（非管理员命令）
register_command(
    name="unsubscribe",
    usage="/(unsubscribe | unsub) <subsystem...>",
    description="取消订阅一个或多个子系统的邮件列表",
    admin_only=False,
)
