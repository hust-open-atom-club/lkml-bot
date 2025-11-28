"""Feed 消息服务

处理 feed 消息到达时的逻辑：
1. PATCH 消息：如果是 PATCH 且 patch_cards 中不存在，则新建
2. REPLY 消息：查找对应的 PATCH 卡片，如果存在且 Thread 已创建，则更新 Thread 内容

架构说明：
- Plugins 层只负责渲染（PatchCardRenderer, ThreadOverviewRenderer）
- Service 层负责业务逻辑（PatchCardService, ThreadService, FeedMessageService）
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.repo import FeedMessageData
from .types import FeedMessage as ServiceFeedMessage
from .types import PatchCard, PatchThread

logger = logging.getLogger(__name__)


class FeedMessageService:
    """Feed 消息服务

    封装 Feed 消息处理的业务逻辑，包括 PATCH 和 REPLY 消息的处理。
    """

    def __init__(
        self,
        patch_card_renderer=None,
        thread_overview_renderer=None,
    ):
        """初始化处理器

        Args:
            patch_card_renderer: PatchCard 渲染器（Plugins 层）
            thread_overview_renderer: Thread Overview 渲染器（Plugins 层）
        """
        self.patch_card_renderer = patch_card_renderer
        self.thread_overview_renderer = thread_overview_renderer

    # ========== 公共方法 ==========

    async def process_email_message(
        self,
        session: AsyncSession,
        feed_message: FeedMessageData,
        classification,
    ) -> None:
        """处理单个 FeedMessage

        根据消息类型（PATCH/REPLY）执行相应的处理逻辑。

        Args:
            session: 数据库会话
            feed_message: Feed 消息对象
            classification: 消息分类结果（MessageClassification）
        """
        if classification.is_patch:
            await self._process_patch_message(session, feed_message, classification)
        elif classification.is_reply:
            await self._process_reply_message(session, feed_message)

    # ========== 私有方法 ==========

    async def _process_patch_message(
        self,
        session: AsyncSession,
        feed_message: FeedMessageData,
        classification,
    ) -> None:
        """处理 PATCH 消息

        如果是 PATCH 且 patch_cards 中不存在，则新建。

        Args:
            session: 数据库会话
            feed_message: Feed 消息对象（必须是 PATCH）
            classification: 消息分类结果
        """
        if not feed_message.message_id_header:
            logger.warning(
                f"PATCH message has no message_id_header: {feed_message.subject[:100]}"
            )
            return

        # 检查是否已存在 PATCH 卡片
        from ..db.database import get_patch_card_service

        async with get_patch_card_service() as patch_card_service:
            existing_patch_card = await patch_card_service.find_by_message_id_header(
                feed_message.message_id_header
            )

        if existing_patch_card:
            logger.debug(
                f"PATCH card already exists: {feed_message.message_id_header}, "
                f"subject: {feed_message.subject[:50]}"
            )
            return

        # 创建新的 PATCH 卡片并发送到 Discord
        try:
            # 检查渲染器是否可用
            if not self.patch_card_renderer:
                logger.debug(
                    f"PatchCard renderer not configured, skipping PATCH card creation: "
                    f"{feed_message.message_id_header}"
                )
                return

            # 从分类结果中获取 PATCH 信息
            patch_info = classification.patch_info
            series_message_id = classification.series_message_id

            # Series PATCH 处理：只发送 Cover Letter，子 PATCH 不单独创建卡片
            if series_message_id and patch_info:
                is_cover_letter = (
                    patch_info.is_cover_letter
                    or feed_message.is_cover_letter
                    or (patch_info.index is not None and patch_info.index == 0)
                )

                if not is_cover_letter:
                    # 子 PATCH (1/n, 2/n, ...) 只保存在 feed_message 表中
                    logger.debug(
                        f"Skipping patch_card creation for series sub-PATCH: "
                        f"{feed_message.message_id_header}, "
                        f"subject: {feed_message.subject[:50]}, "
                        f"patch_index: {patch_info.index}/{patch_info.total}. "
                        f"Sub-patch is stored in feed_message table only."
                    )
                    return

            # 准备 Service 层的 FeedMessage 对象
            service_feed_message = self._convert_to_service_feed_message(
                feed_message, patch_info, series_message_id
            )

            # 检查 PATCH 卡片是否已存在
            async with get_patch_card_service() as service:
                patch_card = await service.get_patch_card_with_series_data(
                    feed_message.message_id_header
                )

            # PATCH 卡片不存在，准备创建
            if not patch_card:
                patch_card = await self._create_and_send_patch_card(  # pylint: disable=too-many-arguments
                    session,
                    feed_message,
                    service_feed_message,
                    patch_info,
                    series_message_id,
                )

            if patch_card:
                logger.info(
                    f"Created PATCH card and sent to Discord: {feed_message.message_id_header}, "
                    f"subject: {feed_message.subject[:50]}, "
                    f"is_series={classification.is_series_patch}, "
                    f"platform_message_id={patch_card.platform_message_id}"
                )
            else:
                logger.warning(
                    f"Failed to create PATCH card for: {feed_message.message_id_header}, "
                    f"subject: {feed_message.subject[:50]}"
                )

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to create PATCH card from feed message: {e}",
                exc_info=True,
            )

    async def _create_and_send_patch_card(  # pylint: disable=too-many-arguments
        self,
        session: AsyncSession,
        feed_message: FeedMessageData,
        service_feed_message,
        patch_info,
        series_message_id: Optional[str],
    ):
        """创建并发送 PATCH 卡片到 Discord"""
        # 如果是 Cover Letter，查询数据库中已有的子 PATCH
        series_patches = await self._get_series_patches_for_cover_letter(  # pylint: disable=too-many-arguments
            session, feed_message, service_feed_message, series_message_id, patch_info
        )

        # 构建并发送 PatchCard
        temp_patch_card = (
            self._build_temp_patch_card(  # pylint: disable=too-many-arguments
                feed_message,
                service_feed_message,
                series_message_id,
                patch_info,
                series_patches,
            )
        )

        platform_message_id = await self.patch_card_renderer.render_and_send(
            temp_patch_card
        )

        # 添加延迟以避免触发 Discord rate limit
        await asyncio.sleep(0.2)

        if not platform_message_id:
            logger.error(
                f"Failed to send PATCH card to Discord: {feed_message.message_id_header}"
            )
            return None

        # 保存到数据库
        return await self._save_patch_card_to_database(
            session, service_feed_message, platform_message_id
        )

    async def _get_series_patches_for_cover_letter(  # pylint: disable=too-many-arguments
        self, session, feed_message, service_feed_message, series_message_id, patch_info
    ):
        """获取 Cover Letter 的子 PATCH 列表"""
        if not (service_feed_message.is_cover_letter and series_message_id):
            return []

        from ..db.repo import FeedMessageRepository
        from .types import SeriesPatchInfo

        feed_msg_repo = FeedMessageRepository(session)
        sub_patches = await feed_msg_repo.find_by_series_message_id(series_message_id)

        series_patches = [
            SeriesPatchInfo(
                subject=p.subject,
                url=p.url or "",
                message_id=p.message_id_header,
                patch_index=p.patch_index or 0,
                patch_total=patch_info.total or 0 if patch_info else 0,
            )
            for p in sub_patches
            if p.patch_index != 0
            and p.message_id_header != feed_message.message_id_header
        ]
        series_patches.sort(key=lambda x: x.patch_index)
        return series_patches

    def _build_temp_patch_card(  # pylint: disable=too-many-arguments
        self,
        feed_message,
        service_feed_message,
        series_message_id,
        patch_info,
        series_patches,
    ):
        """构建临时 PatchCard 对象用于渲染"""
        from .types import PatchCard

        return PatchCard(
            message_id_header=feed_message.message_id_header,
            subsystem_name=feed_message.subsystem_name,
            platform_message_id="",
            platform_channel_id=self.patch_card_renderer.config.platform_channel_id,
            subject=feed_message.subject,
            author=feed_message.author,
            url=feed_message.url,
            expires_at=feed_message.received_at,
            is_series_patch=service_feed_message.is_series_patch,
            series_message_id=series_message_id,
            patch_version=patch_info.version if patch_info else None,
            patch_index=patch_info.index if patch_info else None,
            patch_total=patch_info.total if patch_info else None,
            has_thread=False,
            is_cover_letter=service_feed_message.is_cover_letter,
            series_patches=series_patches,
        )

    async def _save_patch_card_to_database(
        self, session, service_feed_message, platform_message_id
    ):
        """保存 PATCH 卡片到数据库"""
        from .patch_card_service import PatchCardService
        from ..db.repo import (
            FeedMessageRepository,
            PatchCardRepository,
        )

        patch_card_repo = PatchCardRepository(session)
        feed_message_repo = FeedMessageRepository(session)
        patch_card_service = PatchCardService(patch_card_repo, feed_message_repo)

        return await patch_card_service.create_patch_card_for_discord(
            feed_message=service_feed_message,
            platform_message_id=platform_message_id,
            platform_channel_id=self.patch_card_renderer.config.platform_channel_id,
            timeout_hours=24,
        )

    async def _process_reply_message(
        self, session: AsyncSession, feed_message: FeedMessageData
    ) -> None:
        """处理 REPLY 消息

        查找对应的 PATCH 卡片，如果存在且 Thread 已创建，则更新 Thread 内容。

        Args:
            session: 数据库会话
            feed_message: Feed 消息对象（必须是 REPLY）
        """
        if not feed_message.in_reply_to_header:
            logger.debug(
                f"REPLY message has no in_reply_to_header: {feed_message.subject[:100]}"
            )
            return

        # 查找回复对应的 PATCH 卡片和 Thread
        patch_card, thread = await self._find_patch_card_and_thread_for_reply(
            session, feed_message
        )

        if not patch_card or not thread or not thread.is_active:
            return

        # 更新 Thread：如果是多消息模式，只更新对应的子 PATCH 消息
        await self._update_thread_with_reply(
            thread, patch_card, feed_message.in_reply_to_header
        )

    async def _find_patch_card_and_thread_for_reply(
        self, session: AsyncSession, feed_message: FeedMessageData
    ):
        """查找回复对应的 PATCH 卡片和 Thread"""

        # 创建 Repository 和 Service 实例（使用辅助函数以减少重复代码）
        from .helpers import create_repositories_and_services

        (
            _,
            _,
            _,
            patch_card_service,
            thread_service,
        ) = create_repositories_and_services(session)

        # 查找 PATCH 卡片
        patch_card = await self._find_patch_card_for_reply(
            session, patch_card_service, feed_message
        )

        if not patch_card:
            return None, None

        # 如果是系列 PATCH，需要填充 series_patches 数据（用于后续匹配子 PATCH）
        if patch_card.is_series_patch and patch_card.series_message_id:
            patch_card = await patch_card_service.get_patch_card_with_series_data(
                patch_card.message_id_header
            )
            if not patch_card:
                return None, None

        # 查找 Thread
        thread = await thread_service.find_by_message_id_header(
            patch_card.message_id_header
        )

        if not thread or not thread.is_active:
            logger.debug(
                f"No active Thread found for REPLY: {feed_message.subject[:100]}, "
                f"message_id_header: {patch_card.message_id_header}"
            )
            return patch_card, None

        return patch_card, thread

    async def _find_patch_card_for_reply(
        self, session, patch_card_service, feed_message
    ):
        """查找回复对应的 PATCH 卡片"""
        # 1. 直接匹配 in_reply_to_header（可能是 Cover Letter 或单 PATCH）
        patch_card = await patch_card_service.find_by_message_id_header(
            feed_message.in_reply_to_header
        )

        # 2. 如果没找到，可能是回复子 PATCH 的情况
        #    先查找子 PATCH 的 feed_message，获取它的 series_message_id
        if not patch_card:
            from ..db.repo import FeedMessageRepository

            feed_message_repo = FeedMessageRepository(session)
            sub_patch_feed_message = await feed_message_repo.find_by_message_id_header(
                feed_message.in_reply_to_header
            )

            # 如果找到了子 PATCH 的 feed_message，通过它的 series_message_id 查找 Cover Letter
            if sub_patch_feed_message and sub_patch_feed_message.series_message_id:
                patch_card = await patch_card_service.find_by_series_message_id(
                    sub_patch_feed_message.series_message_id
                )
                logger.debug(
                    f"Found Cover Letter via sub-patch series_message_id: "
                    f"in_reply_to={feed_message.in_reply_to_header}, "
                    f"series_message_id={sub_patch_feed_message.series_message_id}"
                )

        if not patch_card:
            logger.debug(
                f"No PATCH card found for REPLY: {feed_message.subject[:100]}, "
                f"in_reply_to: {feed_message.in_reply_to_header}"
            )

        return patch_card

    async def _send_thread_update_notification(self, thread:PatchThread, patch_card:PatchCard):
        """发送 Thread 更新通知到频道

        Args:
            thread: Thread 对象
            patch_card: PATCH 卡片对象
        """
        try:
            # 检查是否有可用的渲染器配置
            if not self.thread_overview_renderer:
                logger.debug("Thread overview renderer not configured, skipping notification")
                return

            # 获取频道 ID
            channel_id = patch_card.platform_channel_id
            if not channel_id:
                # 如果 patch_card 中没有，尝试从 renderer 的 config 获取
                if self.thread_overview_renderer and hasattr(
                    self.thread_overview_renderer, "config"
                ):
                    channel_id = getattr(
                        self.thread_overview_renderer.config, "platform_channel_id", None
                    )

            if not channel_id:
                logger.warning(
                    f"Channel ID not available, cannot send thread update notification "
                    f"for thread {thread.thread_id}"
                )
                return

            # 通过渲染器发送通知（避免直接导入 plugins 层）
            # 使用延迟导入以避免循环依赖
            import importlib

            # 动态导入 Discord 客户端函数（避免架构层级问题）
            try:
                client_module = importlib.import_module(
                    "plugins.lkml_bot.client.discord_client"
                )
                send_thread_update_notification = getattr(
                    client_module, "send_thread_update_notification"
                )
            except (ImportError, AttributeError) as e:
                logger.error(
                    f"Failed to import send_thread_update_notification: {e}",
                    exc_info=True,
                )
                return

            # 发送通知
            success = await send_thread_update_notification(
                self.thread_overview_renderer.config,
                channel_id,
                thread.thread_id,
                patch_card.platform_message_id,
            )

            if success:
                logger.info(
                    f"Sent thread update notification for thread {thread.thread_id} "
                    f"in channel {channel_id}"
                )
            else:
                logger.warning(
                    f"Failed to send thread update notification for thread {thread.thread_id}"
                )

        except (RuntimeError, ValueError, AttributeError, ImportError) as e:
            logger.error(
                f"Failed to send thread update notification: {e}",
                exc_info=True,
            )

    async def _update_thread_with_reply(
        self, thread:PatchThread, patch_card:PatchCard, in_reply_to_header: str
    ):
        """当 Reply 到达时，更新 Thread

        Args:
            thread: Thread 对象
            patch_card: PATCH 卡片对象
            in_reply_to_header: Reply 的 in_reply_to 头部
        """
        if not self.thread_overview_renderer:
            logger.debug("Thread overview renderer not configured, skipping update")
            return

        try:
            update_success = False

            # 系列 PATCH：更新对应的子 PATCH 消息
            if patch_card.is_series_patch:
                update_success = await self._update_sub_patch_for_reply(
                    thread, patch_card, in_reply_to_header
                )
            else:
                # 单 PATCH：更新 overview 消息
                update_success = await self._update_single_patch_for_reply(thread, patch_card)

            # 如果更新成功，发送频道通知
            if update_success:
                await self._send_thread_update_notification(thread, patch_card)

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to update thread with reply: {e}",
                exc_info=True,
            )

    async def _update_sub_patch_for_reply(
        self, thread:PatchThread, patch_card:PatchCard, in_reply_to_header: str
    ) -> bool:
        """更新特定子 PATCH 的消息（多消息模式）

        Args:
            thread: Thread 对象
            patch_card: PATCH 卡片对象
            in_reply_to_header: Reply 的 in_reply_to 头部

        Returns:
            更新成功返回 True，失败返回 False
        """
        try:
            from ..db.database import get_thread_service

            # 查找 Reply 对应的子 PATCH
            target_patch = None
            target_patch_index = None

            for patch in patch_card.series_patches or []:
                patch_msg_id = patch.message_id
                if patch_msg_id and patch_msg_id in in_reply_to_header:
                    target_patch = patch
                    target_patch_index = patch.patch_index
                    break

            if not target_patch or target_patch_index is None:
                logger.debug(
                    f"Could not find target sub-patch for reply: {in_reply_to_header}"
                )
                return False

            # 查找该子 PATCH 的消息 ID
            sub_patch_messages = thread.sub_patch_messages
            message_id = sub_patch_messages.get(str(target_patch_index))

            if not message_id:
                logger.warning(
                    f"No message_id found for sub-patch {target_patch_index}"
                )
                return False

            # 查询整个系列的所有 Reply，然后准备该子 PATCH 的独立 overview 数据
            async with get_thread_service() as service:
                # 获取整个系列的所有回复
                all_replies = await service.find_all_replies_to_patch(
                    patch_card.message_id_header
                )

                # 为该子 PATCH 准备独立的 overview 数据
                sub_overview = await service.prepare_sub_patch_overview_data(
                    target_patch, all_replies
                )

            # 只更新该子 PATCH 的消息（使用 service 层准备好的数据）
            success = await self.thread_overview_renderer.update_sub_patch_message(
                thread.thread_id,
                message_id,
                sub_overview,
            )

            if success:
                logger.info(
                    f"Updated sub-patch [{target_patch_index}] message "
                    f"in thread {thread.thread_id}"
                )

            return success

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to update sub-patch for reply: {e}",
                exc_info=True,
            )
            return False

    def _build_single_patch_info(self, patch_card):
        """构建单 PATCH 的 SeriesPatchInfo 对象（辅助函数以减少重复）"""
        from .helpers import build_single_patch_info

        return build_single_patch_info(patch_card)

    async def _update_single_patch_for_reply(self, thread, patch_card) -> bool:
        """更新单 PATCH 的消息

        Args:
            thread: Thread 对象
            patch_card: PATCH 卡片对象

        Returns:
            更新成功返回 True，失败返回 False
        """
        try:
            from ..db.database import get_thread_service

            # 查找单 PATCH 的消息 ID（使用 patch_index=1）
            sub_patch_messages = thread.sub_patch_messages
            message_id = sub_patch_messages.get("1")

            if not message_id:
                logger.warning(
                    f"No message_id found for single patch in thread {thread.thread_id}"
                )
                return False

            # 查询该 PATCH 的所有 Reply，然后准备独立的 overview 数据
            async with get_thread_service() as service:
                # 获取所有回复
                all_replies = await service.find_all_replies_to_patch(
                    patch_card.message_id_header
                )

                # 构建单 PATCH 信息
                single_patch = self._build_single_patch_info(patch_card)

                # 为该单 PATCH 准备独立的 overview 数据
                sub_overview = await service.prepare_sub_patch_overview_data(
                    single_patch, all_replies
                )

            # 更新单 PATCH 的消息（使用 service 层准备好的数据）
            success = await self.thread_overview_renderer.update_sub_patch_message(
                thread.thread_id,
                message_id,
                sub_overview,
            )

            if success:
                logger.info(
                    f"Updated single patch message in thread {thread.thread_id}"
                )

            return success

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to update single patch for reply: {e}",
                exc_info=True,
            )
            return False

    def _convert_to_service_feed_message(
        self, feed_message, patch_info, series_message_id
    ) -> ServiceFeedMessage:
        """转换为 Service 层的 FeedMessage 对象

        Args:
            feed_message: Repository 层的 FeedMessageData
            patch_info: PATCH 信息
            series_message_id: Series 消息 ID

        Returns:
            Service 层的 FeedMessage 对象
        """
        is_series = (
            series_message_id is not None
            and (patch_info.total is not None and patch_info.total > 1)
            if patch_info
            else False
        )

        return ServiceFeedMessage(
            subsystem_name=feed_message.subsystem_name,
            message_id_header=feed_message.message_id_header,
            subject=feed_message.subject,
            author=feed_message.author,
            author_email=feed_message.author_email,
            message_id=feed_message.message_id,
            in_reply_to_header=feed_message.in_reply_to_header,
            content=feed_message.content,
            url=feed_message.url,
            received_at=feed_message.received_at,
            is_patch=feed_message.is_patch,
            is_reply=feed_message.is_reply,
            is_series_patch=is_series,
            patch_version=patch_info.version if patch_info else None,
            patch_index=patch_info.index if patch_info else None,
            patch_total=patch_info.total if patch_info else None,
            is_cover_letter=patch_info.is_cover_letter if patch_info else False,
            series_message_id=series_message_id,
        )
