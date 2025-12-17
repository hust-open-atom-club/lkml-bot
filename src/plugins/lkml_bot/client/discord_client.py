"""Discord 客户端

负责所有 Discord REST API 的 HTTP 调用。

在当前重构中，本模块既提供底层函数式 API（兼容现有代码），
也提供基于接口的 `DiscordClient` 类，以便在多平台架构中作为
Discord 的唯一客户端实例使用。
"""

import asyncio
from typing import Dict, List, Optional, Tuple

import httpx
from nonebot.log import logger

from lkml.feed.feed_message_classifier import parse_patch_subject

from .exceptions import DiscordHTTPError, FormatPatchError
from .discord_params import PatchCardParams
from .base import PatchCardClient, ThreadClient
from ..renders.types import DiscordRenderedPatchCard, DiscordRenderedThreadOverview

# Discord embed description 限制为 4096 字符
DISCORD_EMBED_DESCRIPTION_MAX_LENGTH = 4096
# Discord content 限制为 2000 字符
DISCORD_CONTENT_MAX_LENGTH = 2000


def truncate_description(description: str) -> str:
    """截断描述以符合 Discord embed 限制

    Args:
        description: 原始描述

    Returns:
        截断后的描述
    """
    if len(description) > DISCORD_EMBED_DESCRIPTION_MAX_LENGTH:
        logger.warning(
            f"Description too long ({len(description)} chars), truncating to {DISCORD_EMBED_DESCRIPTION_MAX_LENGTH}"
        )
        description = description[:4093] + "..."
    return description


async def send_discord_embed(
    config,
    params: PatchCardParams,
    description: str,
    max_retries: int = 3,
    embed_color: Optional[int] = None,
    title: Optional[str] = None,
) -> Optional[str]:
    """发送 Discord embed 消息（带 rate limit 处理）

    Args:
        config: 配置对象
        params: 订阅卡片参数
        description: embed 描述
        max_retries: 遇到 429 时的最大重试次数
        embed_color: Embed 颜色（可选，默认 Discord 蓝色）
        title: Embed 标题（可选，默认使用 subject）

    Returns:
        Discord 消息 ID，失败返回 None
    """
    # 构建订阅卡片内容
    embed = {
        "title": title if title else f"📨 {params.subject[:200]}",
        "description": description,
        "color": (
            embed_color if embed_color is not None else 0x5865F2
        ),  # Discord 蓝色（默认）
    }

    if params.url:
        embed["url"] = params.url

    # 发送到 Discord
    headers = {
        "Authorization": f"Bot {config.discord_bot_token}",
        "Content-Type": "application/json",
    }

    # 重试逻辑（处理 rate limit）
    for attempt in range(max_retries):
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"https://discord.com/api/v10/channels/{config.platform_channel_id}/messages",
                    json={"embeds": [embed]},
                    headers=headers,
                    timeout=30.0,
                )

                if response.status_code in {200, 201}:
                    result = response.json()
                    platform_message_id = result.get("id")
                    logger.info(
                        f"Sent subscription card, message ID: {platform_message_id}"
                    )
                    return platform_message_id

                # Discord rate limit (429)
                if response.status_code == 429:
                    retry_after = response.json().get("retry_after", 1.0)
                    logger.warning(
                        f"Discord rate limit hit (429), retry after {retry_after}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_after)
                        continue
                    logger.error("Max retries reached for rate limit")
                    return None

                # 其他错误
                logger.error(
                    f"Failed to send subscription card: {response.status_code}, {response.text}"
                )
                return None

            except httpx.TimeoutException:
                logger.error("Timeout sending Discord embed")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
            except (httpx.HTTPError, RuntimeError) as e:
                logger.error(f"Error sending Discord embed: {e}", exc_info=True)
                return None

    return None


def _format_patch_list(patches: list, format_patch_list_item_func) -> List[str]:
    """格式化 PATCH 列表

    Args:
        patches: PATCH 列表
        format_patch_list_item_func: 格式化函数

    Returns:
        格式化后的 PATCH 列表
    """
    patch_list = []
    for patch in patches:
        try:
            patch_list.append(format_patch_list_item_func(patch))
        except (ValueError, AttributeError, KeyError) as e:
            logger.warning(f"Failed to format patch list item: {e}, patch: {patch}")
            continue
    return patch_list


def _build_series_description(
    series_patch_card, patch_info, patch_list: List[str]
) -> str:
    """构建系列描述

    Args:
        series_patch_card: 系列 PATCH 卡片订阅对象
        patch_info: 解析后的 patch 信息
        patch_list: 格式化后的 PATCH 列表

    Returns:
        描述字符串
    """
    yaml_content = f"""```yaml
Subsystem: {series_patch_card.subsystem_name}
Date: {series_patch_card.received_at.strftime("%Y-%m-%d %H:%M:%S")}
Author: {series_patch_card.author}
Total Patches: {patch_info.total + 1}
Received: {len(patch_list)}/{patch_info.total + 1}
```"""

    description_parts = [
        yaml_content,
        "**Series:**",
        "",
    ]
    description_parts.extend(patch_list)
    description_parts.extend(
        [
            "",
            "Create a dedicated Thread to receive follow-up replies using the command:",
            f"```bash\n/watch {series_patch_card.message_id_header}\n```",
        ]
    )

    description = "\n".join(description_parts)
    return truncate_description(description)


def _build_series_embed(series_patch_card, description: str) -> Dict:
    """构建系列 embed

    Args:
        series_patch_card: 系列 PATCH 卡片订阅对象
        description: 描述字符串

    Returns:
        embed 字典
    """
    title = f"📨 {series_patch_card.subject[:120]}"
    embed = {
        "title": title,
        "description": description,
        "color": 0x5865F2,
    }

    if series_patch_card.url:
        embed["url"] = series_patch_card.url

    return embed


async def _update_discord_message(config, series_patch_card, embed: Dict) -> None:
    """更新 Discord 消息

    Args:
        config: 配置对象
        series_patch_card: 系列 PATCH 卡片订阅对象
        embed: embed 字典

    Raises:
        DiscordHTTPError: 当 HTTP 请求失败时
        httpx.HTTPError: 当网络请求失败时
    """
    headers = {
        "Authorization": f"Bot {config.discord_bot_token}",
        "Content-Type": "application/json",
    }

    message_data = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient() as client:
            channel_id = series_patch_card.platform_channel_id
            message_id = series_patch_card.platform_message_id
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
            response = await client.patch(
                url,
                json=message_data,
                headers=headers,
                timeout=30.0,
            )

            if response.status_code in {200, 201}:
                logger.info(f"Updated series patch card: {series_patch_card.subject}")
                return

            raise DiscordHTTPError(
                response.status_code,
                f"Failed to update series card: {response.text}",
            )
    except httpx.HTTPError as e:
        # 重新抛出 httpx.HTTPError，让上层处理
        logger.debug(
            f"HTTP error in _update_discord_message: {type(e).__name__}: {str(e)}, "
            f"channel_id={channel_id}, message_id={message_id}"
        )
        raise


async def update_discord_series_card(
    config, series_patch_card, patches: list, format_patch_list_item_func
) -> None:
    """更新 Discord 上的系列 PATCH 卡片

    Args:
        config: 配置对象
        series_patch_card: 系列 PATCH 卡片订阅对象
        patches: PATCH 列表
        format_patch_list_item_func: 格式化 PATCH 列表项的函数
    """
    try:
        logger.debug(
            f"Starting to update Discord series patch card: "
            f"message_id={series_patch_card.message_id_header}, "
            f"patches_count={len(patches)}"
        )

        if not config.discord_bot_token or not config.platform_channel_id:
            logger.debug(
                "Missing Discord bot token or channel ID, skipping card update"
            )
            return

        patch_list = _format_patch_list(patches, format_patch_list_item_func)
        patch_info = parse_patch_subject(series_patch_card.subject)
        description = _build_series_description(
            series_patch_card, patch_info, patch_list
        )
        embed = _build_series_embed(series_patch_card, description)
        await _update_discord_message(config, series_patch_card, embed)

    except (DiscordHTTPError, FormatPatchError) as e:
        logger.error(
            f"Failed to update Discord series patch card: {e}, "
            f"series_patch_card={series_patch_card.message_id_header if series_patch_card else 'None'}, "
            f"platform_message_id={getattr(series_patch_card, 'platform_message_id', 'N/A')}, "
            f"patches_count={len(patches) if patches else 0}",
            exc_info=True,
        )
    except httpx.HTTPError as e:
        error_details = {
            "error_type": type(e).__name__,
            "error_message": str(e) if str(e) else "Unknown HTTP error",
        }
        # 如果是 RequestError，尝试获取更多信息
        if hasattr(e, "request") and e.request:  # pylint: disable=no-member
            error_details["url"] = str(e.request.url)  # pylint: disable=no-member
        # 检查是否有 response 属性（某些 httpx 错误类型有）
        response = getattr(e, "response", None)
        if response:
            error_details["status_code"] = getattr(response, "status_code", None)
            response_text = getattr(response, "text", None)
            if response_text:
                error_details["response_text"] = response_text[:200]

        logger.error(
            f"HTTP error updating Discord series patch card: {error_details}, "
            f"series_patch_card={series_patch_card.message_id_header if series_patch_card else 'None'}, "
            f"platform_message_id={getattr(series_patch_card, 'platform_message_id', 'N/A')}, "
            f"platform_channel_id={getattr(series_patch_card, 'platform_channel_id', 'N/A')}",
            exc_info=True,
        )


async def _handle_thread_exists_error(config, message_id: str) -> Optional[str]:
    """处理 Thread 已存在的错误

    Args:
        config: 配置对象
        message_id: Discord 消息 ID

    Returns:
        已存在的 Thread ID，如果无法获取则返回 None
    """
    logger.warning(
        f"Thread already exists for message {message_id}, attempting to retrieve existing thread"
    )
    return await _handle_existing_thread_retrieval(config, message_id)


async def _handle_existing_thread_retrieval(config, message_id: str) -> Optional[str]:
    """处理已存在 Thread 的检索逻辑

    Args:
        config: 配置对象
        message_id: Discord 消息 ID

    Returns:
        已存在的 Thread ID，如果无法获取则返回 None
    """
    existing_thread_id = await get_existing_thread_id(config, message_id)
    if existing_thread_id:
        logger.info(f"Found existing thread: {existing_thread_id}")
        return existing_thread_id
    # 无法获取 Thread ID，返回 None（由上层处理错误消息）
    logger.warning(f"Could not retrieve existing thread ID for message {message_id}")
    return None


async def _create_thread_request(
    config, thread_name: str, message_id: str
) -> Tuple[Optional[str], bool]:
    """发送创建 Thread 的 HTTP 请求

    Args:
        config: 配置对象
        thread_name: Thread 名称
        message_id: Discord 消息 ID

    Returns:
        (Thread ID, is_thread_exists_error) 元组
        - Thread ID: 成功创建或获取到的 Thread ID，失败返回 None
        - is_thread_exists_error: 是否是 "Thread 已存在" 错误（error code 160004）
    """
    headers = {
        "Authorization": f"Bot {config.discord_bot_token}",
        "Content-Type": "application/json",
    }

    thread_data = {
        "name": thread_name[:100],  # Discord thread 名称限制为 100 字符
        "auto_archive_duration": 10080,  # 7 天后自动归档
    }

    async with httpx.AsyncClient() as client:
        channel_id = config.platform_channel_id
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/threads"
        response = await client.post(
            url,
            json=thread_data,
            headers=headers,
            timeout=30.0,
        )

        if response.status_code in {200, 201}:
            thread_data = response.json()
            thread_id = thread_data.get("id")
            logger.info(f"Created Discord Thread: {thread_name} (ID: {thread_id})")
            return thread_id, False

        # 检查是否是 Thread 已存在的错误
        error_data = response.json() if response.text else {}
        error_code = error_data.get("code")

        if response.status_code == 400 and error_code == 160004:
            # Thread 已存在，尝试获取 Thread ID
            thread_id = await _handle_thread_exists_error(config, message_id)
            if thread_id:
                return thread_id, True
            # 如果无法获取 Thread ID，返回 None 但标记为 Thread 已存在错误
            return None, True

        logger.error(
            f"Failed to create Discord Thread: {response.status_code}, {response.text}"
        )
        return None, False


async def create_discord_thread(
    config, thread_name: str, message_id: str
) -> Tuple[Optional[str], bool]:
    """创建 Discord Thread

    Args:
        config: 配置对象
        thread_name: Thread 名称
        message_id: Discord 消息 ID（Thread 将从这条消息创建）

    Returns:
        (Thread ID, is_thread_exists_error) 元组
        - Thread ID: 成功创建或获取到的 Thread ID，失败返回 None
        - is_thread_exists_error: 是否是 "Thread 已存在" 错误
    """
    try:
        if not config.discord_bot_token or not config.platform_channel_id:
            logger.error("Discord bot token or channel ID not configured")
            return None, False

        return await _create_thread_request(config, thread_name, message_id)

    except httpx.HTTPError as e:
        logger.error(f"HTTP error creating Discord Thread: {e}", exc_info=True)
        return None, False
    except (ValueError, KeyError) as e:
        logger.error(f"Data error creating Discord Thread: {e}", exc_info=True)
        return None, False


async def get_existing_thread_id(config, message_id: str) -> Optional[str]:
    """获取已存在的 Thread ID

    Args:
        config: 配置对象
        message_id: Discord 消息 ID

    Returns:
        Thread ID，如果不存在则返回 None
    """
    try:
        if not config.discord_bot_token:
            return None

        headers = {
            "Authorization": f"Bot {config.discord_bot_token}",
        }

        async with httpx.AsyncClient() as client:
            # 方法1: 获取消息对象，检查是否有 thread 字段
            response = await client.get(
                f"https://discord.com/api/v10/channels/{config.platform_channel_id}/messages/{message_id}",
                headers=headers,
                timeout=30.0,
            )

            if response.status_code == 200:
                message_data = response.json()
                # 检查消息是否有 thread 字段
                thread = message_data.get("thread")
                if thread and thread.get("id"):
                    return thread.get("id")

            # 方法2: 如果方法1失败，尝试获取活跃的 Threads
            response = await client.get(
                f"https://discord.com/api/v10/channels/{config.platform_channel_id}/threads/active",
                headers=headers,
                timeout=30.0,
            )

            if response.status_code == 200:
                threads_data = response.json()
                threads = threads_data.get("threads", [])
                # 查找与消息相关的 Thread（通过 parent_id 匹配）
                for thread in threads:
                    if thread.get("parent_id") == message_id:
                        return thread.get("id")

            return None

    except httpx.HTTPError as e:
        logger.warning(f"HTTP error getting existing thread ID: {e}")
        return None
    except (ValueError, KeyError) as e:
        logger.warning(f"Data error getting existing thread ID: {e}")
        return None


async def send_thread_exists_error(  # pylint: disable=unused-argument
    config, message_id: str
) -> None:
    """发送 Thread 已存在的错误消息

    Args:
        config: 配置对象
        message_id: Discord 消息 ID
    """
    try:
        if not config.discord_bot_token or not config.platform_channel_id:
            return

        headers = {
            "Authorization": f"Bot {config.discord_bot_token}",
            "Content-Type": "application/json",
        }

        # 尝试获取已存在的 Thread ID
        thread_id = await get_existing_thread_id(config, message_id)
        # 构建错误消息描述
        description = "此消息已经有一个 Thread 了。\n\n请使用现有的 Thread 继续讨论。"
        description += f"\n\nThread: <#{thread_id}>"

        error_embed = {
            "title": "⚠️ Thread 已存在",
            "description": description,
            "color": 0xFFA500,  # 橙色
            "footer": {"text": "LKML Bot"},
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://discord.com/api/v10/channels/{config.platform_channel_id}/messages",
                json={"embeds": [error_embed]},
                headers=headers,
                timeout=30.0,
            )

            if response.status_code in {200, 201}:
                logger.info("Sent thread exists error message")
            else:
                logger.warning(
                    f"Failed to send thread exists error message: {response.status_code}, {response.text}"
                )

    except httpx.HTTPError as e:
        logger.warning(f"HTTP error sending thread exists error: {e}")
    except (ValueError, KeyError) as e:
        logger.warning(f"Data error sending thread exists error: {e}")


def _is_thread_type(thread_data: Dict) -> bool:
    """检查是否是 Thread 类型

    Args:
        thread_data: Thread 数据字典

    Returns:
        如果是 Thread 类型返回 True
    """
    thread_type = thread_data.get("type")
    # Thread 类型是 11 (PUBLIC_THREAD) 或 12 (PRIVATE_THREAD)
    return thread_type in {11, 12}


async def _check_thread_request(config, thread_id: str) -> bool:
    """发送检查 Thread 的 HTTP 请求

    Args:
        config: 配置对象
        thread_id: Discord Thread ID

    Returns:
        如果 Thread 存在返回 True，否则返回 False
    """
    headers = {
        "Authorization": f"Bot {config.discord_bot_token}",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://discord.com/api/v10/channels/{thread_id}",
            headers=headers,
            timeout=30.0,
        )

        if response.status_code == 200:
            thread_data = response.json()
            return _is_thread_type(thread_data)
        if response.status_code == 404:
            return False
        logger.warning(
            f"Unexpected status code when checking thread: {response.status_code}"
        )
        return False


async def check_thread_exists(config, thread_id: str) -> bool:
    """检查 Thread 是否真的存在于 Discord

    Args:
        config: 配置对象
        thread_id: Discord Thread ID

    Returns:
        如果 Thread 存在返回 True，否则返回 False
    """
    try:
        if not config.discord_bot_token:
            logger.error("Discord bot token not configured")
            return False

        return await _check_thread_request(config, thread_id)

    except httpx.HTTPError as e:
        logger.warning(f"HTTP error checking thread existence: {e}")
        return False
    except (ValueError, KeyError) as e:
        logger.warning(f"Data error checking thread existence: {e}")
        return False


async def send_thread_update_notification(
    config,
    channel_id: str,
    thread_id: str,
    platform_message_id: Optional[str] = None,  # pylint: disable=unused-argument
) -> bool:
    """发送 Thread 更新通知到频道

    Args:
        config: 配置对象
        channel_id: 频道 ID
        thread_id: Thread ID
        platform_message_id: Patch Card 的消息 ID（用于构建 Thread 链接）

    Returns:
        成功返回 True，失败返回 False
    """
    try:
        if not config.discord_bot_token:
            logger.error("Discord bot token not configured")
            return False

        headers = {
            "Authorization": f"Bot {config.discord_bot_token}",
            "Content-Type": "application/json",
        }

        # 使用 Thread 提及格式 <#{thread_id}>
        thread_mention = f"Thread: <#{thread_id}>"

        # 构建通知消息
        content = f"🔄 **Thread Overview 已更新**\n\n{thread_mention}\n\n"

        message_data = {"content": content}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                json=message_data,
                headers=headers,
                timeout=30.0,
            )

            if response.status_code in {200, 201}:
                logger.debug(f"Sent Thread update notification to channel {channel_id}")
                return True
            logger.error(
                f"Failed to send Thread update notification: {response.status_code}, {response.text}"
            )
            return False

    except httpx.HTTPError as e:
        logger.error(
            f"HTTP error sending Thread update notification: {e}", exc_info=True
        )
        return False
    except (ValueError, KeyError) as e:
        logger.error(
            f"Data error sending Thread update notification: {e}", exc_info=True
        )
        return False


async def send_message_to_thread(
    config,
    thread_id: str,
    content: Optional[str] = None,
    embed: Optional[Dict] = None,
    max_retries: int = 3,
) -> Optional[str]:
    """发送消息到 Thread（带 rate limit 处理）

    Args:
        config: 配置对象
        thread_id: Thread ID
        content: 消息内容
        embed: 可选的 embed 字典
        max_retries: 遇到 429 时的最大重试次数

    Returns:
        成功返回消息 ID，失败返回 None
    """
    try:
        if not config.discord_bot_token:
            logger.error("Discord bot token not configured")
            return None

        headers = {
            "Authorization": f"Bot {config.discord_bot_token}",
            "Content-Type": "application/json",
        }

        message_data = {}
        if content:
            # Discord content 限制为 2000 字符
            if len(content) > DISCORD_CONTENT_MAX_LENGTH:
                logger.warning(
                    f"Content too long ({len(content)} chars), truncating to {DISCORD_CONTENT_MAX_LENGTH}"
                )
                content = content[: DISCORD_CONTENT_MAX_LENGTH - 3] + "..."
            message_data["content"] = content
        if embed:
            message_data["embeds"] = [embed]

        url = f"https://discord.com/api/v10/channels/{thread_id}/messages"
        result_message_id = None

        # 重试逻辑（处理 rate limit）
        for attempt in range(max_retries):
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        url,
                        json=message_data,
                        headers=headers,
                        timeout=30.0,
                    )

                    if response.status_code in {200, 201}:
                        result = response.json()
                        result_message_id = result.get("id")
                        logger.debug(
                            f"Sent message to thread {thread_id}, message_id={result_message_id}"
                        )
                        break

                    # Discord rate limit (429)
                    if response.status_code == 429:
                        retry_after = response.json().get("retry_after", 1.0)
                        logger.warning(
                            f"Discord rate limit hit (429) for thread message, "
                            f"retry after {retry_after}s (attempt {attempt + 1}/{max_retries})"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_after)
                            continue
                        logger.error("Max retries reached for rate limit")
                        break

                    logger.error(
                        f"Failed to send message to Thread: {response.status_code}, {response.text}"
                    )
                    break

                except httpx.TimeoutException:
                    logger.error("Timeout sending message to thread")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    break

                except (httpx.HTTPError, RuntimeError) as e:
                    logger.error(f"Error sending message to thread: {e}", exc_info=True)
                    break

        return result_message_id

    except (ValueError, KeyError) as e:
        logger.error(f"Data error sending message to Thread: {e}", exc_info=True)
        return None


async def update_message_in_thread(
    config, thread_id: str, message_id: str, content: str, embed: Optional[Dict] = None
) -> bool:
    """更新 Thread 中的消息

    Args:
        config: 配置对象
        thread_id: Thread ID
        message_id: 要更新的消息 ID
        content: 消息内容
        embed: 可选的 embed 字典

    Returns:
        成功返回 True，失败返回 False
    """
    try:
        if not config.discord_bot_token:
            logger.error("Discord bot token not configured")
            return False

        headers = {
            "Authorization": f"Bot {config.discord_bot_token}",
            "Content-Type": "application/json",
        }

        message_data = {}
        if content:
            # Discord content 限制为 2000 字符
            if len(content) > DISCORD_CONTENT_MAX_LENGTH:
                logger.warning(
                    f"Content too long ({len(content)} chars), truncating to {DISCORD_CONTENT_MAX_LENGTH}"
                )
                content = content[: DISCORD_CONTENT_MAX_LENGTH - 3] + "..."
            message_data["content"] = content
        if embed:
            message_data["embeds"] = [embed]

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"https://discord.com/api/v10/channels/{thread_id}/messages/{message_id}",
                json=message_data,
                headers=headers,
                timeout=30.0,
            )

            if response.status_code in {200, 201}:
                logger.debug(f"Updated message {message_id} in thread {thread_id}")
                return True
            logger.error(
                f"Failed to update message in Thread: {response.status_code}, {response.text}"
            )
            return False

    except httpx.HTTPError as e:
        logger.error(f"HTTP error updating message in Thread: {e}", exc_info=True)
        return False
    except (ValueError, KeyError) as e:
        logger.error(f"Data error updating message in Thread: {e}", exc_info=True)
        return False


class DiscordClient(
    PatchCardClient, ThreadClient
):  # pylint: disable=too-few-public-methods
    """Discord 客户端类

    作为 Discord 的唯一客户端实例，封装所有与 Discord 交互的能力。

    - PatchCard 能力：发送订阅卡片（Patch Card）
    - Thread 能力：创建 Thread、发送/更新 Thread 消息、发送 Thread 更新通知
    """

    def __init__(self, config):
        """初始化 DiscordClient

        Args:
            config: 插件配置对象（包含 discord_bot_token、platform_channel_id 等）
        """
        self.config = config

    # ========== PatchCardClient 接口实现 ==========

    async def send_patch_card(
        self, rendered_data: DiscordRenderedPatchCard
    ) -> Optional[str]:
        """发送 Patch Card 到 Discord

        Args:
            rendered_data: 渲染后的 PatchCard 数据

        Returns:
            Discord 消息 ID，失败返回 None
        """
        return await send_discord_embed(
            self.config,
            rendered_data.params,
            rendered_data.description,
            embed_color=rendered_data.embed_color,
            title=rendered_data.title,
        )

    # ========== ThreadClient 接口实现 ==========

    async def create_thread(
        self, thread_name: str, message_id: str
    ) -> Tuple[Optional[str], bool]:
        """创建 Discord Thread（或获取已存在的 Thread）"""
        return await create_discord_thread(self.config, thread_name, message_id)

    async def send_thread_overview(
        self, thread_id: str, overview_data
    ) -> Dict[int, str]:
        """发送 Thread Overview 消息到 Discord Thread

        Args:
            thread_id: Discord Thread ID
            overview_data: DiscordRenderedThreadOverview 渲染结果

        Returns:
            {patch_index: message_id} 映射
        """

        if not isinstance(overview_data, DiscordRenderedThreadOverview):
            logger.error(
                f"Invalid overview_data type: {type(overview_data)}, "
                "expected DiscordRenderedThreadOverview"
            )
            return {}

        sub_patch_messages: Dict[int, str] = {}
        messages = overview_data.messages

        for patch_index, message in messages.items():
            try:
                msg_id = await send_message_to_thread(
                    self.config,
                    thread_id,
                    content=message.content,
                    embed=message.embed,
                )

                if msg_id:
                    sub_patch_messages[patch_index] = msg_id
                    logger.info(
                        f"Sent thread message for patch [{patch_index}] to thread {thread_id}, "
                        f"message_id={msg_id}"
                    )
                else:
                    logger.warning(
                        f"Failed to send thread message for patch [{patch_index}] to thread {thread_id}"
                    )

                # 添加延迟以避免触发 Discord rate limit
                await asyncio.sleep(0.2)
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    f"Error sending thread message for patch [{patch_index}]: {e}",
                    exc_info=True,
                )

        return sub_patch_messages

    async def update_thread_overview(
        self, thread_id: str, message_id: str, overview_data
    ) -> bool:
        """更新 Thread Overview 消息

        Args:
            thread_id: Discord Thread ID
            message_id: 要更新的消息 ID
            overview_data: DiscordRenderedThreadMessage 渲染结果

        Returns:
            成功返回 True，失败返回 False
        """
        from ..renders.types import DiscordRenderedThreadMessage

        if not isinstance(overview_data, DiscordRenderedThreadMessage):
            logger.error(
                f"Invalid overview_data type: {type(overview_data)}, "
                "expected DiscordRenderedThreadMessage"
            )
            return False

        return await update_message_in_thread(
            self.config,
            thread_id,
            message_id,
            overview_data.content,
            embed=overview_data.embed,
        )

    async def send_thread_update_notification(
        self, channel_id: str, thread_id: str, platform_message_id: Optional[str] = None
    ) -> bool:
        """发送 Thread 更新通知到频道"""
        return await send_thread_update_notification(
            self.config, channel_id, thread_id, platform_message_id
        )
