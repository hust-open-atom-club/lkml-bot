"""Feishu 客户端

负责通过 Feishu 自定义机器人 webhook 发送卡片消息。

实现 PatchCardClient 和 ThreadClient 接口：
- PatchCard：发送 Patch Card 卡片
- Thread：发送 Thread 通知卡片（Feishu 不支持真正的 Thread，用通知卡片代替）
"""

from typing import Dict, Optional, Tuple

import httpx
from nonebot.log import logger

from .base import PatchCardClient, ThreadClient
from ..renders.types import (
    FeishuRenderedPatchCard,
    FeishuRenderedThreadNotification,
)


class FeishuClient(
    PatchCardClient, ThreadClient
):  # pylint: disable=too-few-public-methods
    """Feishu 平台客户端

    负责发送 Patch Card 和 Thread 通知卡片到 Feishu webhook。
    """

    def __init__(self, config):
        """初始化 FeishuClient

        Args:
            config: 插件配置对象（需要包含 feishu_webhook_url）
        """
        self.config = config
        self.webhook_url: str = getattr(config, "feishu_webhook_url", "") or ""

    async def send_patch_card(
        self, rendered_data: FeishuRenderedPatchCard
    ) -> Optional[str]:
        """发送 Patch Card 到 Feishu

        Args:
            rendered_data: 渲染后的 Feishu 卡片数据

        Returns:
            由于 Feishu webhook 一般不会返回消息 ID，这里统一返回 None。
        """
        if not self.webhook_url:
            # 未配置 Feishu webhook，直接跳过
            logger.debug("Feishu webhook URL not configured, skip sending patch card")
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url, json=rendered_data.card, timeout=30.0
                )
                if response.status_code not in {200, 201}:
                    logger.warning(
                        "Failed to send patch card to Feishu: %s, %s",
                        response.status_code,
                        response.text,
                    )
        except httpx.HTTPError as e:
            logger.warning("HTTP error sending patch card to Feishu: %s", e)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error sending patch card to Feishu: %s", e)

        # 当前不返回 Feishu 消息 ID
        return None

    # ========== ThreadClient 接口实现 ==========

    async def create_thread(
        self, thread_name: str, message_id: str
    ) -> Tuple[Optional[str], bool]:
        """创建 Thread（Feishu 不支持 Thread，发送创建通知卡片）

        Args:
            thread_name: Thread 名称（未使用）
            message_id: 消息 ID（未使用）

        Returns:
            (None, False) - Feishu 不支持 Thread，返回 None
        """
        # Feishu 不支持 Thread，返回 None
        return None, False

    async def send_thread_overview(
        self, thread_id: str, overview_data
    ) -> Dict[int, str]:
        """发送 Thread Overview 通知卡片到 Feishu

        Args:
            thread_id: Thread ID（未使用，Feishu 不支持 Thread）
            overview_data: FeishuRenderedThreadNotification 渲染结果

        Returns:
            空字典（Feishu 不支持消息 ID 映射）
        """
        if not isinstance(overview_data, FeishuRenderedThreadNotification):
            logger.error(
                f"Invalid overview_data type: {type(overview_data)}, "
                "expected FeishuRenderedThreadNotification"
            )
            return {}

        if not self.webhook_url:
            logger.debug(
                "Feishu webhook URL not configured, skip sending thread notification"
            )
            return {}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url, json=overview_data.card, timeout=30.0
                )
                if response.status_code not in {200, 201}:
                    logger.warning(
                        "Failed to send thread notification to Feishu: %s, %s",
                        response.status_code,
                        response.text,
                    )
        except httpx.HTTPError as e:
            logger.warning("HTTP error sending thread notification to Feishu: %s", e)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Data error sending thread notification to Feishu: %s", e)

        return {}

    async def update_thread_overview(
        self, thread_id: str, message_id: str, overview_data
    ) -> bool:
        """更新 Thread Overview（Feishu 不支持更新，发送新的通知卡片）

        Args:
            thread_id: Thread ID（未使用）
            message_id: 消息 ID（未使用）
            overview_data: FeishuRenderedThreadNotification 渲染结果

        Returns:
            成功返回 True，失败返回 False
        """
        if not isinstance(overview_data, FeishuRenderedThreadNotification):
            logger.error(
                f"Invalid overview_data type: {type(overview_data)}, "
                "expected FeishuRenderedThreadNotification"
            )
            return False

        if not self.webhook_url:
            logger.debug(
                "Feishu webhook URL not configured, skip sending thread update notification"
            )
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url, json=overview_data.card, timeout=30.0
                )
                if response.status_code in {200, 201}:
                    return True
                logger.warning(
                    "Failed to send thread update notification to Feishu: %s, %s",
                    response.status_code,
                    response.text,
                )
                return False
        except httpx.HTTPError as e:
            logger.warning(
                "HTTP error sending thread update notification to Feishu: %s", e
            )
            return False
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(
                "Data error sending thread update notification to Feishu: %s", e
            )
            return False

    async def send_thread_update_notification(
        self, channel_id: str, thread_id: str, platform_message_id: Optional[str] = None
    ) -> bool:
        """发送 Thread 更新通知（Feishu 不支持，直接返回 True）

        Args:
            channel_id: 频道 ID（未使用）
            thread_id: Thread ID（未使用）
            platform_message_id: 消息 ID（未使用）

        Returns:
            总是返回 True（Feishu 不支持此功能）
        """
        # Feishu 不支持 Thread 更新通知，直接返回 True
        return True
