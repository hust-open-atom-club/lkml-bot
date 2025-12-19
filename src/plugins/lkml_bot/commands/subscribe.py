"""订阅子系统命令模块"""

import re
from typing import Optional

import httpx
from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.service import LKMLService
from ..config import get_config
from ..shared import extract_command, get_user_info_or_finish, register_command

# Discord 相关常量
DISCORD_EMBED_DESCRIPTION_MAX = 4096  # Discord Embed description 最大长度

lkml_service = LKMLService()


def _format_names_multiline(names: list[str], per_line: int = 5) -> str:
    """将名称列表格式化为每行固定数量的字符串。

    Args:
        names: 名称列表
        per_line: 每行的名称数量

    Returns:
        多行字符串，每行最多包含 per_line 个名称，使用逗号分隔。
    """
    if not names:
        return "无"

    chunks: list[str] = []
    for i in range(0, len(names), per_line):
        chunk = ", ".join(names[i : i + per_line])
        chunks.append(chunk)
    return "\n".join(chunks)


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

        # 如果没有参数，显示帮助信息
        if len(parts) == 0:
            await SubscribeCmd.finish(
                "subscribe: 缺少参数\n"
                "用法: @机器人 /subscribe|/sub <subsystem...> | list | search <keyword>\n"
                "示例:\n"
                "  /subscribe list - 查看当前订阅列表\n"
                "  /subscribe search net - 搜索包含 'net' 的子系统\n"
                "  /subscribe netdev dri-devel - 批量订阅多个子系统"
            )
            return

        # 检查第一个参数是否是已知的子命令
        first_arg = parts[1].strip().lower()

        logger.info(f"First argument: {first_arg}")

        if first_arg == "list":
            await _handle_subscribe_list(event)
            return

        if first_arg == "search":
            if len(parts) < 3:
                await SubscribeCmd.finish(
                    "subscribe search: 缺少搜索关键词\n"
                    "用法: @机器人 /subscribe search <keyword>"
                )
                return
            keyword = " ".join(parts[2:]).strip()
            logger.info(f"Keyword: {keyword}")
            await _handle_subscribe_search(keyword, event)
            return

        # 如果不是子命令，则将所有参数视为子系统名称进行批量订阅
        # 获取用户信息
        user_id, user_name = await get_user_info_or_finish(event, SubscribeCmd)
        await _handle_subscribe_batch(parts, user_id, user_name)
    except FinishedException:  # pylint: disable=try-except-raise
        # FinishedException 由 matcher.finish() 抛出，需要重新抛出以终止处理
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error("Unexpected error in handle_subscribe: %s", e, exc_info=True)
        await SubscribeCmd.finish(f"❌ 处理命令时发生错误: {str(e)}")


async def _handle_subscribe_list(event: Optional[Event] = None) -> None:
    """处理订阅列表查询逻辑。

    Args:
        event: 事件对象
    """
    try:
        config = get_config()
        supported = config.get_supported_subsystems()
        subscribed = await lkml_service.get_subscribed_subsystems()
        subscribed_set = set(subscribed)

        await _send_discord_embed_list(subscribed, subscribed_set, supported, event)
    except FinishedException:
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error("Error in list subcommands: %s", e, exc_info=True)
        await SubscribeCmd.finish(f"❌ 列表查询时发生错误: {str(e)}")


async def _send_subscribed_embed(
    channel_id: str, headers: dict, subscribed: list[str]
) -> None:
    """发送已订阅列表的 Embed

    Args:
        channel_id: Discord 频道 ID
        headers: HTTP 请求头
        subscribed: 已订阅的子系统列表
    """
    if subscribed:
        subscribed_sorted = sorted(subscribed)
        subscribed_text = _format_names_multiline(subscribed_sorted)
        # Discord Embed description 最大长度限制
        if len(subscribed_text) > DISCORD_EMBED_DESCRIPTION_MAX:
            subscribed_text = (
                subscribed_text[: DISCORD_EMBED_DESCRIPTION_MAX - 50] + "..."
            )
    else:
        subscribed_text = "无"

    embed = {
        "title": f"✅ 已订阅 ({len(subscribed)})",
        "description": subscribed_text,
        "color": 0x5865F2,  # Discord 蓝色
        "footer": {"text": "LKML Bot"},
    }

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            json={"embeds": [embed]},
            headers=headers,
            timeout=30.0,
        )


async def _send_discord_embed_list(
    subscribed: list[str],
    subscribed_set: set[str],
    supported: list[str],
    event: Optional[Event] = None,
) -> None:
    """使用 Discord Embed 格式发送订阅列表

    Args:
        subscribed: 已订阅的子系统列表
        subscribed_set: 已订阅的子系统集合
        supported: 所有可订阅的子系统列表
        event: 事件对象
    """
    try:
        config = get_config()
        if not config.discord_bot_token or not config.platform_channel_id:
            await SubscribeCmd.finish("❌ Discord 配置未设置")
            return

        channel_id = config.platform_channel_id
        if event and hasattr(event, "channel_id"):
            channel_id = str(event.channel_id)

        headers = {
            "Authorization": f"Bot {config.discord_bot_token}",
            "Content-Type": "application/json",
        }

        # 发送已订阅列表
        await _send_subscribed_embed(channel_id, headers, subscribed)

        # 发送可订阅列表（不分页，每行固定数量）
        unsubscribed = sorted(
            [name for name in supported if name not in subscribed_set]
        )
        unsubscribed_text = _format_names_multiline(unsubscribed)

        # Discord Embed description 最大长度限制
        if len(unsubscribed_text) > DISCORD_EMBED_DESCRIPTION_MAX:
            unsubscribed_text = (
                unsubscribed_text[: DISCORD_EMBED_DESCRIPTION_MAX - 50] + "..."
            )

        unsubscribed_embed = {
            "title": f"📦 可订阅的子系统 ({len(unsubscribed)})",
            "description": unsubscribed_text,
            "color": 0x3498DB,  # 蓝色
            "footer": {"text": "LKML Bot"},
        }

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                json={"embeds": [unsubscribed_embed]},
                headers=headers,
                timeout=30.0,
            )

        await SubscribeCmd.finish()

    except FinishedException:
        # 正常结束流程，向上抛出让 NoneBot 处理
        raise
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error sending Discord embed list: {e}", exc_info=True)
        await SubscribeCmd.finish(f"❌ 发送订阅列表时发生错误: {str(e)}")


async def _handle_subscribe_search(keyword: str, event: Optional[Event] = None) -> None:
    """处理搜索子系统逻辑。

    Args:
        keyword: 搜索关键词
        event: 事件对象（用于获取 Discord 渠道 ID）
    """
    try:
        config = get_config()
        supported = config.get_supported_subsystems()
        logger.info(f"Supported subsystems: {supported}")
        subscribed = await lkml_service.get_subscribed_subsystems()
        subscribed_set = set(subscribed)

        # 模糊搜索：包含关键词的子系统（不区分大小写）
        keyword_lower = keyword.lower()
        matches = [name for name in supported if keyword_lower in name.lower()]

        if not matches:
            await SubscribeCmd.finish(
                f"🔍 搜索 '{keyword}': 未找到匹配的子系统\n"
                f"提示: 使用 /subscribe list 查看所有可订阅的子系统"
            )
            return

        # 按订阅状态和名称排序
        matches.sort(key=lambda x: (x not in subscribed_set, x.lower()))

        await _send_search_result(keyword, matches, subscribed_set, config, event)
    except FinishedException:
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error("Error in search subcommand: %s", e, exc_info=True)
        await SubscribeCmd.finish(f"❌ 搜索时发生错误: {str(e)}")


async def _handle_subscribe_batch(
    parts: list[str], user_id: str, user_name: str
) -> None:
    """处理批量订阅逻辑。

    Args:
        parts: 命令参数列表（parts[0] 是命令本身，需要排除）
        user_id: 用户ID
        user_name: 用户名称
    """
    # 将所有部分合并，支持逗号或空格分隔
    # parts[0] 是命令本身（/subscribe 或 /sub），需要排除
    raw_args = " ".join(parts[1:]) if len(parts) > 1 else ""
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


async def _send_search_result(
    keyword: str,
    matches: list[str],
    subscribed_set: set[str],
    config,
    event: Optional[Event] = None,
) -> None:
    """根据搜索结果发送 Discord Embed 或文本消息。

    拆分自 _handle_subscribe_search 以减少局部变量数量。
    """
    # 将匹配结果按订阅状态拆分
    subscribed_matches = [m for m in matches if m in subscribed_set]
    unsubscribed_matches = [m for m in matches if m not in subscribed_set]

    # 如果 Discord 配置不可用，退回到文本输出
    if not config.discord_bot_token or not config.platform_channel_id:
        lines = [f"🔍 搜索 '{keyword}' 的结果 ({len(matches)}):"]
        if subscribed_matches:
            subscribed_text = _format_names_multiline(sorted(subscribed_matches))
            lines.append(f"✅ 已订阅:\n{subscribed_text}")
        if unsubscribed_matches:
            unsubscribed_text = _format_names_multiline(sorted(unsubscribed_matches))
            lines.append(f"📦 未订阅:\n{unsubscribed_text}")
        await SubscribeCmd.finish("\n".join(lines))
        return

    # Discord 渠道 ID：优先使用事件中的 channel_id，其次使用配置
    channel_id = config.platform_channel_id
    if event and hasattr(event, "channel_id"):
        channel_id = str(event.channel_id)

    # 构造 Embed 内容，样式参考订阅列表（每行最多 5 个）
    subscribed_text = (
        _format_names_multiline(sorted(subscribed_matches))
        if subscribed_matches
        else "无"
    )
    unsubscribed_text = (
        _format_names_multiline(sorted(unsubscribed_matches))
        if unsubscribed_matches
        else "无"
    )

    description = (
        f"✅ 已订阅 ({len(subscribed_matches)}): {subscribed_text}\n\n"
        f"📦 未订阅 ({len(unsubscribed_matches)}): {unsubscribed_text}"
    )

    # 简单保护，避免超过 Discord Embed 的 description 限制
    if len(description) > DISCORD_EMBED_DESCRIPTION_MAX:
        description = description[: DISCORD_EMBED_DESCRIPTION_MAX - 50] + "..."

    embed = {
        "title": f"🔍 搜索 '{keyword}' 的结果 ({len(matches)})",
        "description": description,
        "color": 0x3498DB,  # 蓝色，与可订阅子系统列表一致
        "footer": {"text": "LKML Bot"},
    }

    headers = {
        "Authorization": f"Bot {config.discord_bot_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            json={"embeds": [embed]},
            headers=headers,
            timeout=30.0,
        )

    await SubscribeCmd.finish()


# 在导入时注册命令元信息（非管理员命令）
register_command(
    name="subscribe",
    usage="/(subscribe | sub) <subsystem...> | list | search <keyword>",
    description="订阅子系统；查看订阅列表；搜索子系统；批量订阅",
    admin_only=False,
)
