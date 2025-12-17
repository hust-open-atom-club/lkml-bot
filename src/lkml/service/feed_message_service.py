"""Feed 消息服务

处理 feed 消息到达时的逻辑：
1. PATCH 消息：如果是 PATCH 且 patch_cards 中不存在，则新建
2. REPLY 消息：查找对应的 PATCH 卡片，如果存在且 Thread 已创建，则更新 Thread 内容

架构说明：
- Plugins 层只负责渲染（PatchCardRenderer, ThreadOverviewRenderer）
- Service 层负责业务逻辑（PatchCardService, ThreadService, FeedMessageService）
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.repo import (
    FeedMessageData,
    FeedMessageRepository,
    PatchCardRepository,
)
from .types import (
    FeedMessage as ServiceFeedMessage,
    PatchCard,
    PatchThread,
    SeriesPatchInfo,
)
from .patch_card_service import PatchCardService

logger = logging.getLogger(__name__)


class FeedMessageService:
    """Feed 消息服务

    封装 Feed 消息处理的业务逻辑，包括 PATCH 和 REPLY 消息的处理。
    """

    def __init__(
        self,
        patch_card_sender=None,
        thread_sender=None,
    ):
        """初始化处理器

        Args:
            patch_card_sender: PatchCard 多平台发送服务
            thread_sender: Thread 多平台发送服务
        """
        # 通过统一的多平台发送服务发送（由 Plugins 层注入）
        self.patch_card_sender = patch_card_sender
        self.thread_sender = thread_sender

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
            if await patch_card_service.find_by_message_id_header(
                feed_message.message_id_header
            ):
                logger.debug(
                    f"PATCH card already exists: {feed_message.message_id_header}, "
                    f"subject: {feed_message.subject[:50]}"
                )
                return

        # 创建新的 PATCH 卡片并发送到 Discord
        try:
            # 检查渲染器是否可用
            if not self.patch_card_sender:
                logger.debug(
                    f"PatchCard renderer not configured, skipping PATCH card creation: "
                    f"{feed_message.message_id_header}"
                )
                return

            # 从分类结果中获取 PATCH 信息
            patch_info = classification.patch_info
            # Series PATCH 处理：只发送 Cover Letter，子 PATCH 不单独创建卡片
            if classification.series_message_id and patch_info:
                if not (
                    patch_info.is_cover_letter
                    or feed_message.is_cover_letter
                    or (patch_info.index is not None and patch_info.index == 0)
                ):
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
                feed_message, patch_info, classification.series_message_id
            )

            # 应用过滤规则（在默认 filter 基础上）
            should_create, matched_filters = await self._should_create_patch_card(
                session, service_feed_message, patch_info
            )
            if not should_create:
                logger.debug(
                    f"Patch card creation filtered out by rules: {feed_message.message_id_header}, "
                    f"subject: {feed_message.subject[:50]}"
                )
                return

            # 将匹配的过滤规则名称传递给 service_feed_message（用于后续渲染）
            if matched_filters:
                service_feed_message.matched_filters = matched_filters

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
                    classification.series_message_id,
                )

            if patch_card:
                logger.info(
                    f"Created PATCH card and sent: {feed_message.message_id_header}, "
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
        """创建并发送 PATCH 卡片到各平台"""
        # 如果是 Cover Letter，查询数据库中已有的子 PATCH
        series_patches = await self._get_series_patches_for_cover_letter(  # pylint: disable=too-many-arguments
            session, feed_message, service_feed_message, series_message_id, patch_info
        )

        # 构建用于渲染和发送的 PatchCard（Service 层统一构建数据）
        temp_patch_card = (
            self._build_temp_patch_card(  # pylint: disable=too-many-arguments
                feed_message,
                service_feed_message,
                series_message_id,
                patch_info,
                series_patches,
            )
        )

        # 使用 PatchCard 发送服务（如果已注入）
        platform_message_id = None
        platform_channel_id = ""

        if self.patch_card_sender is not None:
            try:
                platform_message_id, platform_channel_id = (
                    await self.patch_card_sender.send_patch_card(temp_patch_card)
                )
            except (RuntimeError, ValueError, AttributeError) as e:
                logger.error(
                    "Failed to send PATCH card via patch_card_sender: %s",
                    e,
                    exc_info=True,
                )
                platform_message_id = None
                platform_channel_id = ""

        if not platform_message_id:
            logger.warning(
                "Failed to send PATCH card via any sender requiring message id: %s",
                feed_message.message_id_header,
            )
            return None

        # 保存到数据库
        return await self._save_patch_card_to_database(
            session, service_feed_message, platform_message_id, platform_channel_id
        )

    async def _get_series_patches_for_cover_letter(  # pylint: disable=too-many-arguments
        self, session, feed_message, service_feed_message, series_message_id, patch_info
    ):
        """获取 Cover Letter 的子 PATCH 列表"""
        if not (service_feed_message.is_cover_letter and series_message_id):
            return []

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
        # PatchCard 已在模块顶部导入，不需要重新导入

        return PatchCard(
            message_id_header=feed_message.message_id_header,
            subsystem_name=feed_message.subsystem_name,
            platform_message_id="",
            platform_channel_id="",
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
            matched_filters=service_feed_message.matched_filters,
        )

    async def _save_patch_card_to_database(
        self, session, service_feed_message, platform_message_id, platform_channel_id
    ):
        """保存 PATCH 卡片到数据库"""
        patch_card_repo = PatchCardRepository(session)
        feed_message_repo = FeedMessageRepository(session)
        patch_card_service = PatchCardService(patch_card_repo, feed_message_repo)

        return await patch_card_service.create_patch_card(
            feed_message=service_feed_message,
            platform_message_id=platform_message_id,
            platform_channel_id=platform_channel_id,
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
        # 传入 session 以确保能查询到新保存的 REPLY（还在同一事务中）
        await self._update_thread_with_reply(
            session, thread, patch_card, feed_message.in_reply_to_header
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
        self,
        session: AsyncSession,
        patch_card_service: PatchCardService,
        feed_message: FeedMessageData,
    ):
        """查找回复对应的 PATCH 卡片

        查找逻辑：
        1. 直接匹配 in_reply_to_header（可能是 Cover Letter 或单 PATCH）
        2. 如果没找到，可能是回复子 PATCH 的情况，通过子 PATCH 的 series_message_id 查找 Cover Letter
        """
        # 1. 直接匹配 in_reply_to_header（可能是 Cover Letter 或单 PATCH）
        patch_card = await patch_card_service.find_by_message_id_header(
            feed_message.in_reply_to_header
        )

        # 2. 如果没找到，可能是回复子 PATCH 的情况
        if not patch_card:
            feed_message_repo = FeedMessageRepository(session)
            sub_patch_feed_message = await feed_message_repo.find_by_message_id_header(
                feed_message.in_reply_to_header
            )

            # 如果找到了子 PATCH 的 feed_message，通过它的 series_message_id 查找 Cover Letter
            if sub_patch_feed_message and sub_patch_feed_message.series_message_id:
                patch_card = await patch_card_service.find_series_patch_card(
                    sub_patch_feed_message.series_message_id
                )
                if patch_card:
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

    async def _send_thread_update_notification(
        self, thread: PatchThread, patch_card: PatchCard
    ):
        """发送 Thread 更新通知到频道

        Args:
            thread: Thread 对象
            patch_card: PATCH 卡片对象
        """
        try:
            # 使用新的 thread_sender（如果可用）
            if self.thread_sender:
                channel_id = patch_card.platform_channel_id
                if not channel_id:
                    logger.warning(
                        f"Channel ID not available, cannot send thread update notification "
                        f"for thread {thread.thread_id}"
                    )
                    return

                success = await self.thread_sender.send_thread_update_notification(
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
                return
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to send thread update notification: {e}",
                exc_info=True,
            )

    async def _update_thread_with_reply(
        self,
        session: AsyncSession,
        thread: PatchThread,
        patch_card: PatchCard,
        in_reply_to_header: str,
    ):
        """当 Reply 到达时，更新 Thread

        根据是否配置了 ``thread_sender``，选择对应的更新实现。

        Args:
            session: 数据库会话（用于查询，确保能查询到新保存的 REPLY）
            thread: Thread 对象
            patch_card: PATCH 卡片对象
            in_reply_to_header: Reply 的 in_reply_to 头部
        """
        if self.thread_sender:
            await self._update_thread_with_reply_via_thread_sender(
                session, thread, patch_card, in_reply_to_header
            )
            return

        await self._update_thread_with_reply_via_renderers(
            session, thread, patch_card, in_reply_to_header
        )

    async def _update_thread_with_reply_via_thread_sender(
        self,
        session: AsyncSession,
        thread: PatchThread,
        patch_card: PatchCard,
        in_reply_to_header: str,
    ) -> None:
        """当 Reply 到达时，使用 ``thread_sender`` 更新 Thread。"""
        try:
            target_patch, target_patch_index = await self._find_target_patch_for_reply(
                patch_card, in_reply_to_header
            )

            if not target_patch or target_patch_index is None:
                logger.debug(
                    "Could not find target patch for reply: %s", in_reply_to_header
                )
                return

            sub_patch_messages = thread.sub_patch_messages or {}
            message_id = sub_patch_messages.get(target_patch_index)

            if not message_id:
                logger.warning(
                    "No message_id found for patch %s in thread %s",
                    target_patch_index,
                    thread.thread_id,
                )
                return

            sub_overview = await self._prepare_patch_overview_data(
                session, target_patch
            )

            if not sub_overview:
                return

            success = await self.thread_sender.update_thread_overview(
                thread.thread_id,
                message_id,
                sub_overview,
            )

            if success:
                logger.info(
                    "Updated patch [%s] message in thread %s",
                    target_patch_index,
                    thread.thread_id,
                )
                await self._send_thread_update_notification(thread, patch_card)
            else:
                logger.warning(
                    "Failed to update patch [%s] message in thread %s",
                    target_patch_index,
                    thread.thread_id,
                )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                "Failed to update thread with reply: %s",
                e,
                exc_info=True,
            )

    async def _update_thread_with_reply_via_renderers(
        self,
        session: AsyncSession,
        thread: PatchThread,
        patch_card: PatchCard,
        in_reply_to_header: str,
    ) -> None:
        """当 Reply 到达时，通过渲染器列表更新 Thread。"""
        try:
            target_patch, target_patch_index = await self._find_target_patch_for_reply(
                patch_card, in_reply_to_header
            )

            if not target_patch or target_patch_index is None:
                logger.debug(
                    "Could not find target patch for reply: %s", in_reply_to_header
                )
                return

            sub_patch_messages = thread.sub_patch_messages or {}
            message_id = sub_patch_messages.get(target_patch_index)

            if not message_id:
                logger.warning(
                    "No message_id found for patch %s in thread %s",
                    target_patch_index,
                    thread.thread_id,
                )
                return

            sub_overview = await self._prepare_patch_overview_data(
                session, target_patch
            )

            if not sub_overview:
                return

            successes: list[bool] = []
            for renderer in self.thread_overview_renderers:
                try:
                    result = await renderer.update_sub_patch_message(
                        thread.thread_id,
                        message_id,
                        sub_overview,
                    )
                    successes.append(bool(result))
                except (RuntimeError, ValueError, AttributeError) as e:
                    successes.append(False)
                    logger.error(
                        "Failed to update patch [%s] message in thread %s: %s",
                        target_patch_index,
                        thread.thread_id,
                        e,
                        exc_info=True,
                    )

            if any(successes):
                logger.info(
                    "Updated patch [%s] message in thread %s",
                    target_patch_index,
                    thread.thread_id,
                )
                await self._send_thread_update_notification(thread, patch_card)
            else:
                logger.warning(
                    "Failed to update patch [%s] message in thread %s",
                    target_patch_index,
                    thread.thread_id,
                )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                "Failed to update thread with reply: %s",
                e,
                exc_info=True,
            )

    async def _find_target_patch_for_reply(
        self, patch_card: PatchCard, in_reply_to_header: str
    ) -> tuple:
        """找到 REPLY 对应的 Patch

        Args:
            patch_card: PATCH 卡片对象
            in_reply_to_header: Reply 的 in_reply_to 头部

        Returns:
            (target_patch, target_patch_index) 元组，如果找不到返回 (None, None)
        """
        from .helpers import build_single_patch_info
        from .thread_service import _extract_message_id_from_header

        # 提取 in_reply_to 中的 message_id
        in_reply_to = _extract_message_id_from_header(in_reply_to_header)
        if not in_reply_to:
            return None, None

        # 单 Patch：直接匹配
        if not patch_card.is_series_patch:
            if patch_card.message_id_header in in_reply_to:
                single_patch = build_single_patch_info(patch_card)
                return single_patch, 1
            return None, None

        # Series Patch：查找匹配的子 Patch
        if patch_card.series_patches:
            for patch in patch_card.series_patches:
                if patch.patch_index == 0:  # 跳过 Cover Letter
                    continue
                if patch.message_id and patch.message_id in in_reply_to:
                    return patch, patch.patch_index

        return None, None

    async def _prepare_patch_overview_data(self, session: AsyncSession, target_patch):
        """准备 Patch 的 overview 数据

        Args:
            session: 数据库会话
            target_patch: 目标 Patch 对象

        Returns:
            SubPatchOverviewData 对象，失败返回 None
        """
        from .helpers import create_repositories_and_services
        from .types import SubPatchOverviewData

        try:
            (
                _,
                _,
                _,
                _,
                thread_service,
            ) = create_repositories_and_services(session)

            patch_replies = await thread_service.get_all_replies_for_patch(
                target_patch.message_id
            )

            patch_reply_hierarchy = await thread_service.build_reply_hierarchy(
                patch_replies, target_patch.message_id
            )

            return SubPatchOverviewData(
                patch=target_patch,
                replies=patch_replies,
                reply_hierarchy=patch_reply_hierarchy,
            )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to prepare patch overview data: {e}",
                exc_info=True,
            )
            return None

    async def _should_create_patch_card(
        self,
        session: AsyncSession,
        service_feed_message: ServiceFeedMessage,
        patch_info,
    ) -> tuple[bool, list[str]]:
        """判断是否应该创建 Patch Card（应用过滤规则）

        Args:
            session: 数据库会话
            service_feed_message: Service 层的 FeedMessage 对象
            patch_info: PATCH 信息

        Returns:
            (should_create, matched_filter_names) 元组
            - should_create: True 表示应该创建，False 表示不应该创建
            - matched_filter_names: 匹配的过滤规则名称列表
        """
        try:
            from ..db.repo import PatchCardFilterRepository
            from .patch_card_filter_service import PatchCardFilterService

            filter_repo = PatchCardFilterRepository(session)
            filter_service = PatchCardFilterService(filter_repo)

            return await filter_service.should_create_patch_card(
                service_feed_message, patch_info
            )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.warning(
                f"Failed to check filter rules, allowing creation by default: {e}",
                exc_info=True,
            )
            # 如果过滤检查失败，默认允许创建（保持原有行为）
            return (True, [])

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
