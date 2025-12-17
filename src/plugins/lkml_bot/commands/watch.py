"""Watch PATCH 命令

允许用户通过命令关注特定的 PATCH，为其创建 Thread。
不需要 Interaction Endpoint，直接通过 Discord Bot 消息命令处理。
"""

from typing import Optional, Tuple

from nonebot import on_message
from nonebot.rule import to_me
from nonebot.adapters import Message, Event
from nonebot.adapters.discord import MessageCreateEvent
from nonebot.params import EventMessage
from nonebot.exception import FinishedException
from nonebot.log import logger

from lkml.feed.feed_message_classifier import parse_patch_subject
from lkml.service import (
    PatchCard,
    PatchThread,
    get_patch_card_service,
    get_thread_service,
)
from lkml.service.types import FeedMessage

from ..client.discord_client import check_thread_exists

from ..shared import (
    register_command,
    extract_command,
    get_user_info_or_finish,
    get_patch_card_sender,
    get_thread_sender,
)


# ========== 命令注册 ==========

register_command(
    name="watch",
    usage="/(watch | w) <message_id>",
    description="为指定的 PATCH 创建专属 Thread",
    admin_only=False,
)

# 创建 matcher - 需要 @ 提及机器人
# 优先级设为 50，高于 help (40)，确保优先处理
# block=False 允许其他命令处理，在内部用 finish() 阻止传播
WatchCmd = on_message(rule=to_me(), priority=50, block=False)


# ========== 主处理函数 ==========


@WatchCmd.handle()
async def handle_watch(_event: Event, message: Message = EventMessage()):
    """处理 watch PATCH 命令"""
    msg_text = message.extract_plain_text().strip()

    # 快速检查是否是 watch 命令
    if not (msg_text.startswith("/watch ") or msg_text.startswith("/w ")):
        return

    # 只处理 MessageCreateEvent
    if not isinstance(_event, MessageCreateEvent):
        logger.debug(f"[watch] Ignoring non-create event: {type(_event).__name__}")
        return

    logger.info(f"[watch] Received watch command: {msg_text}")

    try:
        # 1. 验证命令并获取参数
        message_id_header, user_info = await _validate_command(
            msg_text, _event, WatchCmd
        )
        if not message_id_header or not user_info:
            return

        _user_id, user_name = user_info

        # 2. 查找或创建 PATCH 卡片（如果是子 PATCH，会自动查找或创建 Cover Letter）
        patch_card = await _find_or_create_patch_card(message_id_header, WatchCmd)
        if not patch_card:
            return

        # 3. 检查现有 Thread
        existing_thread, should_recreate = await _check_existing_thread(patch_card)

        if existing_thread and not should_recreate:
            await _handle_existing_thread(existing_thread, patch_card, WatchCmd)
            return

        # 5. 创建新 Thread
        thread_id = await _create_new_thread(patch_card, WatchCmd)
        if not thread_id:
            return

        # 6. 发送成功消息
        logger.info(
            f"User {user_name} successfully watched PATCH: {patch_card.subject}, "
            f"Thread ID: {thread_id}"
        )
        success_msg = _build_success_message(patch_card, thread_id, should_recreate)
        await WatchCmd.finish(success_msg)

    except FinishedException:  # pylint: disable=try-except-raise
        raise
    except (ValueError, KeyError, AttributeError) as e:
        logger.error(f"Data error watching PATCH: {e}", exc_info=True)
        await WatchCmd.finish("❌ 关注失败，请联系管理员查看日志")


# ========== 命令验证 ==========


async def _validate_command(
    msg_text: str, event: Event, matcher
) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    """验证命令并提取参数

    Returns:
        (message_id_header, user_info) 元组，失败返回 (None, None)
    """
    # 匹配 /watch 或 /w
    cmd_text = extract_command(msg_text, "/watch") or extract_command(msg_text, "/w")
    if not cmd_text:
        logger.debug(f"[watch] Not a watch command, ignoring. Message: '{msg_text}'")
        return None, None

    logger.info(f"[watch] Processing command: {cmd_text}")

    # 获取用户信息
    user_info = await get_user_info_or_finish(event, matcher)
    if not user_info:
        return None, None

    user_id, user_name = user_info

    # 解析 message_id_header 参数
    message_id_header = _parse_message_id(cmd_text, matcher)
    if not message_id_header:
        return None, None

    logger.info(f"User {user_name} ({user_id}) watching PATCH: {message_id_header}")

    return message_id_header, user_info


def _parse_message_id(cmd_text: str, matcher) -> Optional[str]:
    """解析并清理 message_id_header 参数

    清理操作：
    - 去除前后空白
    - 去除换行符和制表符
    - 去除多余的空格
    """
    parts = cmd_text.split(maxsplit=1)
    if len(parts) < 2:
        matcher.finish(
            "❌ 缺少参数\n\n"
            "用法: /watch <message_id_header>\n"
            "message_id_header 可以从 PATCH 卡片中复制"
        )
        return None

    # 清理输入
    message_id = parts[1].strip()
    message_id = message_id.replace("\n", "").replace("\r", "").replace("\t", "")
    message_id = " ".join(message_id.split())

    logger.debug(f"[watch] Cleaned message_id_header: '{message_id}'")

    return message_id


# ========== PATCH 卡片处理 ==========


async def _find_or_create_cover_letter_from_id(
    cover_letter_message_id: str, matcher
) -> Optional[PatchCard]:
    """查找或创建 Cover Letter 的 patch_card

    Args:
        cover_letter_message_id: Cover Letter 的 message_id_header
        matcher: Matcher 对象

    Returns:
        Cover Letter 的 PatchCard，失败返回 None
    """
    # 先查找是否已存在 Cover Letter 的 patch_card
    async with get_patch_card_service() as service:
        cover_letter = await service.get_patch_card_with_series_data(
            cover_letter_message_id
        )
        if cover_letter:
            return cover_letter

    # Cover Letter 的 patch_card 不存在，需要从 feed_messages 查找并创建
    feed_message = await _find_feed_message(cover_letter_message_id, matcher)
    if not feed_message:
        return None

    patch_info = _validate_patch_message(feed_message, cover_letter_message_id, matcher)
    if not patch_info:
        return None

    return await _create_patch_card(feed_message, patch_info, matcher)


async def _find_or_create_patch_card(
    message_id_header: str, matcher
) -> Optional[PatchCard]:
    """查找或创建 PATCH 卡片

    流程：
    1. 从 patch_cards 查找
    2. 如果不存在，从 feed_messages 查找
    3. 如果是子 PATCH，使用 series_message_id 直接查找或创建 Cover Letter 的 patch_card
    4. 如果是 Cover Letter 或单 PATCH，直接创建

    Returns:
        Cover Letter 的 PatchCard 对象（包含 series_patches），失败返回 None
    """
    result = None

    # 1. 从 patch_cards 查找
    async with get_patch_card_service() as service:
        patch_card = await service.get_patch_card_with_series_data(message_id_header)

        # 如果找到的是子 PATCH（有 series_message_id 且不是 cover_letter），直接查找 Cover Letter
        if (
            patch_card
            and patch_card.series_message_id
            and not patch_card.is_cover_letter
        ):
            logger.info(
                f"Found sub-patch card, looking for Cover Letter: "
                f"{patch_card.series_message_id}"
            )
            result = await _find_or_create_cover_letter_from_id(
                patch_card.series_message_id, matcher
            )
        elif patch_card:
            result = patch_card

    if result:
        return result

    # 2. 从 feed_messages 查找
    feed_message = await _find_feed_message(message_id_header, matcher)
    if not feed_message:
        return None

    # 3. 验证是否是 PATCH
    patch_info = _validate_patch_message(feed_message, message_id_header, matcher)
    if not patch_info:
        return None

    # 4. 如果是子 PATCH（有 series_message_id 且不是 cover_letter），直接查找或创建 Cover Letter
    if (
        feed_message.series_message_id
        and not patch_info.is_cover_letter
        and patch_info.index
        and patch_info.index > 0
    ):
        logger.info(
            f"Found sub-patch in feed_messages, looking for Cover Letter: "
            f"{feed_message.series_message_id}"
        )
        result = await _find_or_create_cover_letter_from_id(
            feed_message.series_message_id, matcher
        )
        return result

    # 5. 如果是 Cover Letter 或单 PATCH，直接创建
    return await _create_patch_card(feed_message, patch_info, matcher)


async def _find_feed_message(message_id_header: str, matcher):
    """从 feed_messages 查找消息"""
    async with get_patch_card_service() as service:
        feed_message = await service.find_feed_message_by_id(message_id_header)

    if not feed_message:
        logger.warning(
            f"PATCH not found in feed_messages: '{message_id_header}' "
            f"(length: {len(message_id_header)})"
        )
        await matcher.finish(
            f"❌ 未找到 PATCH: `{message_id_header}`\n\n"
            f"查询长度: {len(message_id_header)} 字符\n"
            "请确保 message_id_header 正确，或者该 PATCH 已过期。"
        )
        return None

    return feed_message


def _validate_patch_message(feed_message, message_id_header: str, matcher):
    """验证消息是否是 PATCH"""
    # 检查 is_patch 标志
    if not feed_message.is_patch:
        matcher.finish(
            f"❌ 找到消息但非 PATCH: `{message_id_header}`\n\n"
            "请确保 message_id_header 对应的是一个 PATCH 邮件。"
        )
        return None

    # 解析 PATCH 信息
    patch_info = parse_patch_subject(feed_message.subject)
    if not patch_info or not patch_info.is_patch:
        matcher.finish(
            f"❌ 找到消息但非 PATCH: `{message_id_header}`\n\n"
            "请确保 message_id_header 对应的是一个 PATCH 邮件。"
        )
        return None

    return patch_info


async def _create_patch_card(feed_message, patch_info, matcher) -> Optional[PatchCard]:
    """创建 PATCH 卡片

    流程：
    1. 渲染并发送到
    2. 保存到数据库
    """
    try:
        from ..config import get_config

        config = get_config()

        # 1. 构建 PatchCard 数据
        temp_patch_card = _build_temp_patch_card(feed_message, patch_info, config)

        # 2. 使用统一的多平台发送器发送
        patch_card_sender = get_patch_card_sender()
        if not patch_card_sender:
            logger.error("PatchCard sender not initialized")
            await matcher.finish(
                f"❌ 创建 PATCH 订阅记录失败: `{feed_message.message_id_header}`\n\n"
                "系统配置错误，请联系管理员。"
            )
            return None

        platform_message_id, platform_channel_id = (
            await patch_card_sender.send_patch_card(temp_patch_card)
        )

        if not platform_message_id:
            logger.error(
                f"Failed to send PATCH card to Discord: {feed_message.message_id_header}"
            )
            await matcher.finish(
                f"❌ 创建 PATCH 订阅记录失败: `{feed_message.message_id_header}`\n\n"
                "发送到 Discord 失败，请联系管理员查看日志。"
            )
            return None

        # 3. 保存到数据库
        service_feed_message = _build_service_feed_message(feed_message, patch_info)

        async with get_patch_card_service() as service:
            patch_card = await service.create_patch_card(
                feed_message=service_feed_message,
                platform_message_id=platform_message_id,
                platform_channel_id=platform_channel_id or config.platform_channel_id,
                timeout_hours=24,
            )

        logger.info(
            f"Created PATCH card from FeedMessage: {feed_message.message_id_header}, "
            f"subject: {feed_message.subject[:50]}, "
            f"platform_message_id: {platform_message_id}"
        )

        return patch_card

    except (ValueError, KeyError, AttributeError) as e:
        logger.error(
            f"Failed to create PATCH card from FeedMessage: {e}", exc_info=True
        )
        await matcher.finish(
            f"❌ 创建 PATCH 订阅记录失败: `{feed_message.message_id_header}`\n\n"
            "请联系管理员查看日志。"
        )
        return None


def _build_temp_patch_card(feed_message, patch_info, config):
    """构建临时 PatchCard 用于渲染"""
    return PatchCard(
        message_id_header=feed_message.message_id_header,
        subsystem_name=feed_message.subsystem_name,
        platform_message_id="",
        platform_channel_id=config.platform_channel_id,
        subject=feed_message.subject,
        author=feed_message.author,
        url=feed_message.url,
        expires_at=feed_message.received_at,
        is_series_patch=feed_message.is_series_patch
        or (patch_info.total and patch_info.total > 1),
        series_message_id=feed_message.series_message_id,
        patch_version=patch_info.version,
        patch_index=patch_info.index,
        patch_total=patch_info.total,
        has_thread=False,
        is_cover_letter=patch_info.is_cover_letter,
        series_patches=[],
    )


def _build_service_feed_message(feed_message, patch_info):
    """构建 Service 层的 FeedMessage 对象"""
    return FeedMessage(
        message_id_header=feed_message.message_id_header,
        subsystem_name=feed_message.subsystem_name,
        subject=feed_message.subject,
        author=feed_message.author,
        author_email=feed_message.author_email,
        received_at=feed_message.received_at,
        url=feed_message.url,
        is_patch=feed_message.is_patch,
        is_series_patch=feed_message.is_series_patch
        or (patch_info.total and patch_info.total > 1),
        series_message_id=feed_message.series_message_id,
        patch_version=patch_info.version,
        patch_index=patch_info.index,
        patch_total=patch_info.total,
        is_cover_letter=patch_info.is_cover_letter,
    )


async def _get_cover_letter(patch_card: PatchCard) -> PatchCard:
    """如果是系列 PATCH，获取 Cover Letter"""
    if not patch_card.series_message_id:
        return patch_card

    async with get_patch_card_service() as service:
        cover_letter = await service.find_by_message_id_header(
            patch_card.series_message_id
        )
        if cover_letter:
            return cover_letter

    return patch_card


# ========== Thread 处理 ==========


async def _check_existing_thread(
    patch_card: PatchCard,
) -> Tuple[Optional[PatchThread], bool]:
    """检查现有 Thread 状态

    Returns:
        (existing_thread, should_recreate) 元组
        - existing_thread: 存在的 Thread，不存在返回 None
        - should_recreate: 是否需要重建
    """
    # 查找 Thread 记录
    async with get_thread_service() as service:
        existing_thread = await service.find_by_message_id_header(
            patch_card.message_id_header
        )

    if not existing_thread:
        return None, False

    # 检查是否标记为 inactive
    if not existing_thread.is_active:
        logger.info(
            f"Found inactive Thread for PATCH {patch_card.message_id_header}, "
            f"will recreate. Old Thread ID: {existing_thread.thread_id}"
        )
        async with get_thread_service() as service:
            await service.delete(existing_thread.thread_id)
        return None, True

    # 验证 Discord Thread 是否真的存在
    from ..config import get_config

    config = get_config()
    thread_exists = await check_thread_exists(config, existing_thread.thread_id)

    if thread_exists:
        logger.info(
            f"Thread {existing_thread.thread_id} exists in Discord "
            f"for PATCH {patch_card.message_id_header}"
        )
        return existing_thread, False

    # Thread 不存在，需要重建
    logger.warning(
        f"Thread {existing_thread.thread_id} marked as active but "
        f"doesn't exist in Discord, will recreate for PATCH {patch_card.message_id_header}"
    )

    async with get_thread_service() as service:
        await service.mark_as_inactive(existing_thread.thread_id)
        await service.delete(existing_thread.thread_id)

    return None, True


async def _handle_existing_thread(existing_thread, patch_card, matcher):
    """处理已存在的 Thread"""
    logger.info(f"Thread {existing_thread.thread_id} exists in Discord, returning link")

    # 标记 PatchCard 为已建立 Thread
    if not patch_card.has_thread:
        logger.info(
            f"Thread exists but PATCH {patch_card.message_id_header} "
            f"is not marked as has_thread, marking now"
        )
        async with get_patch_card_service() as service:
            await service.mark_as_has_thread(patch_card.message_id_header)

    await matcher.finish(
        f"✅ 此 Thread 已创建\n\n"
        f"Thread: <#{existing_thread.thread_id}>\n"
        f"主题: {patch_card.subject[:100]}"
    )


async def _create_new_thread(patch_card: PatchCard, matcher) -> Optional[str]:
    """创建新 Thread

    流程：
    1. 创建 Discord Thread
    2. 保存 Thread 记录
    3. 准备并渲染 Thread Overview
    4. 标记 PatchCard 为已建立 Thread

    Returns:
        Thread ID，失败返回 None
    """
    try:
        # 1. 准备 Thread Overview 数据
        async with get_thread_service() as service:
            overview_data = await service.prepare_thread_overview_data(
                patch_card.message_id_header
            )

        if not overview_data:
            logger.error(
                f"Failed to prepare thread overview data "
                f"for {patch_card.message_id_header}"
            )
            await matcher.finish(
                f"❌ 创建 Thread 失败: `{patch_card.message_id_header}`\n\n"
                "无法准备 Thread Overview 数据，请联系管理员查看日志。"
            )
            return None

        # 2. 使用统一的多平台 Thread 发送服务创建 Thread 并发送 Overview
        thread_sender = get_thread_sender()
        if not thread_sender:
            logger.error("Thread sender not initialized")
            await matcher.finish(
                f"❌ 创建 Thread 失败: `{patch_card.message_id_header}`\n\n"
                "系统配置错误，请联系管理员。"
            )
            return None

        thread_name = patch_card.subject[:100]
        thread_id, sub_patch_messages = (
            await thread_sender.create_thread_and_send_overview(
                thread_name, patch_card.platform_message_id, overview_data
            )
        )

        if not thread_id:
            await matcher.finish(
                "❌ 创建 Thread 失败\n\n"
                "可能的原因：\n"
                "- 网络连接问题\n"
                "- Discord API 错误\n"
                "- 权限不足\n"
                "- Thread 池已满\n\n"
                "请稍后重试，或联系管理员查看日志。"
            )
            return None

        logger.info(f"Created Discord Thread: {thread_name} (ID: {thread_id})")

        # 3. 保存 Thread 记录
        async with get_thread_service() as service:
            await service.create(patch_card.message_id_header, thread_id, thread_name)
            logger.info(
                f"Created Thread record: thread_id={thread_id}, "
                f"message_id_header={patch_card.message_id_header}, "
                f"name={thread_name}"
            )

            # 保存子 PATCH 消息映射
            if sub_patch_messages:
                await service.update_sub_patch_messages(thread_id, sub_patch_messages)
                logger.info(
                    f"Saved {len(sub_patch_messages)} sub-patch messages "
                    f"for thread {thread_id}"
                )

        # 4. 标记 PatchCard 为已建立 Thread
        async with get_patch_card_service() as service:
            await service.mark_as_has_thread(patch_card.message_id_header)
            logger.info(
                f"Marked patch card as has_thread: {patch_card.message_id_header}"
            )

        return thread_id

    except (
        RuntimeError,
        ValueError,
        AttributeError,
    ) as e:
        logger.error(f"Failed to create new thread: {e}", exc_info=True)
        await matcher.finish("❌ 创建 Thread 失败\n\n请联系管理员查看日志。")
        return None


# ========== 消息构建 ==========


def _build_success_message(
    patch_card: PatchCard, thread_id: str, is_recreate: bool
) -> str:
    """构建成功消息"""
    action = "重建" if is_recreate else "创建"

    msg_lines = [
        f"✅ Thread {action}成功\n",
        f"Thread: <#{thread_id}>",
        f"主题: {patch_card.subject[:100]}",
    ]

    if patch_card.is_series_patch:
        msg_lines.append(f"\n这是一个系列 PATCH (共 {patch_card.patch_total} 个)")

    return "\n".join(msg_lines)
