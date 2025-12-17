"""多平台 Thread 发送服务

负责协调将 Thread Overview 发送到多个平台：
- Discord：创建 Thread 并发送多条 overview 消息
- Feishu：发送 Thread 创建/更新通知卡片

Service 层只关心"有一个 Thread Overview 要发送/更新"，
具体多平台细节由本模块处理。
"""

from typing import Dict, Optional, Tuple

from nonebot.log import logger

from lkml.service.types import SubPatchOverviewData, ThreadOverviewData

from .client.discord_client import DiscordClient
from .client.feishu_client import FeishuClient
from .renders.thread.renderer import ThreadOverviewRenderer
from .renders.thread.feishu_render import FeishuThreadOverviewRenderer


class MultiPlatformThreadSender:  # pylint: disable=too-few-public-methods
    """Thread 多平台发送服务

    当前实现：
    - Discord：创建 Thread，发送多条 overview 消息，返回消息 ID 映射
    - Feishu：发送 Thread 创建/更新通知卡片（如果配置了 webhook）
    """

    def __init__(
        self,
        discord_client: DiscordClient,
        discord_renderer: ThreadOverviewRenderer,
        feishu_client: FeishuClient,
        feishu_renderer: FeishuThreadOverviewRenderer,
    ):
        self.discord_client = discord_client
        self.discord_renderer = discord_renderer
        self.feishu_client = feishu_client
        self.feishu_renderer = feishu_renderer

    async def create_thread_and_send_overview(
        self, thread_name: str, message_id: str, overview_data: ThreadOverviewData
    ) -> Tuple[Optional[str], Dict[int, str]]:
        """创建 Thread 并发送 Overview

        Args:
            thread_name: Thread 名称
            message_id: Patch Card 消息 ID（用于创建 Thread）
            overview_data: Thread Overview 数据

        Returns:
            (thread_id, sub_patch_messages) 元组
            - thread_id: Discord Thread ID（如果创建成功）
            - sub_patch_messages: {patch_index: message_id} 映射
        """
        thread_id: Optional[str] = None
        sub_patch_messages: Dict[int, str] = {}

        # 1) Discord：创建 Thread 并发送 Overview
        try:
            thread_id, _ = await self.discord_client.create_thread(
                thread_name, message_id
            )
            if thread_id:
                # 渲染并发送
                discord_rendered = self.discord_renderer.render(overview_data)
                sub_patch_messages = await self.discord_client.send_thread_overview(
                    thread_id, discord_rendered
                )
                logger.info(
                    "Created Discord Thread and sent overview: thread_id=%s, "
                    "messages_count=%d",
                    thread_id,
                    len(sub_patch_messages),
                )
            else:
                logger.warning("Failed to create Discord Thread")
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                "Error creating Discord Thread and sending overview: %s",
                e,
                exc_info=True,
            )

        # 2) Feishu：发送 Thread 创建通知卡片
        try:
            feishu_rendered = self.feishu_renderer.render_create_notification(
                overview_data
            )
            await self.feishu_client.send_thread_overview("", feishu_rendered)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Error sending Feishu thread creation notification: %s", e)

        return thread_id, sub_patch_messages

    async def update_thread_overview(
        self,
        thread_id: str,
        message_id: str,
        sub_overview: SubPatchOverviewData,
    ) -> bool:
        """更新 Thread Overview

        Args:
            thread_id: Discord Thread ID
            message_id: 要更新的消息 ID
            sub_overview: 子 PATCH Overview 数据

        Returns:
            成功返回 True，失败返回 False
        """
        success = False

        # 1) Discord：更新 Thread 消息
        try:
            discord_rendered = self.discord_renderer.render_sub_patch(sub_overview)
            success = await self.discord_client.update_thread_overview(
                thread_id, message_id, discord_rendered
            )
            if success:
                logger.info(
                    "Updated Discord Thread message: thread_id=%s, message_id=%s",
                    thread_id,
                    message_id,
                )
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error updating Discord Thread message: %s", e, exc_info=True)

        # 2) Feishu：发送 Thread 更新通知卡片
        try:
            feishu_rendered = self.feishu_renderer.render_update_notification(
                sub_overview
            )
            await self.feishu_client.update_thread_overview("", "", feishu_rendered)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("Error sending Feishu thread update notification: %s", e)

        return success

    async def send_thread_update_notification(
        self, channel_id: str, thread_id: str, platform_message_id: Optional[str] = None
    ) -> bool:
        """发送 Thread 更新通知

        Args:
            channel_id: 频道 ID
            thread_id: Thread ID
            platform_message_id: Patch Card 消息 ID（可选）

        Returns:
            成功返回 True，失败返回 False
        """
        # 只由 Discord 发送（Feishu 不支持）
        return await self.discord_client.send_thread_update_notification(
            channel_id, thread_id, platform_message_id
        )
