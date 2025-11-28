"""PATCH 卡片服务

封装 PATCH 卡片相关的数据库操作，提供业务逻辑层接口。
Service 层通过依赖注入接受 Repository 实例。
"""

import logging
from typing import TYPE_CHECKING, Optional, List

from .types import PatchCard, SeriesPatchInfo

if TYPE_CHECKING:
    from ..db.repo import (
        FeedMessageRepository,
        PatchCardRepository,
    )

logger = logging.getLogger(__name__)


class PatchCardService:
    """PATCH 卡片服务类（业务 API 层）

    Service 层通过依赖注入接受 Repository 实例。
    Plugins 层通过 `get_patch_card_service()` 函数获取 Service 实例。
    """

    def __init__(
        self,
        patch_card_repo: "PatchCardRepository",
        feed_message_repo: "FeedMessageRepository",
    ):
        """初始化服务

        Args:
            patch_card_repo: PATCH 卡片仓库实例（已注入 session）
            feed_message_repo: Feed 消息仓库实例（已注入 session）
        """
        self.patch_card_repo = patch_card_repo
        self.feed_message_repo = feed_message_repo

    def _repo_data_to_service_data(self, repo_data) -> PatchCard:
        """将 repo 层的 PatchCardData 转换为 service 层的 PatchCard

        Args:
            repo_data: repo 层的 PatchCardData

        Returns:
            service 层的 PatchCard
        """
        from .helpers import extract_common_patch_card_fields

        common_fields = extract_common_patch_card_fields(repo_data)
        return PatchCard(**common_fields)

    def _convert_to_repo_data(self, data: PatchCard):
        """将 service 层的 PatchCard 转换为 repo 层的 PatchCardData

        Args:
            data: service 层的 PatchCard

        Returns:
            repo 层的 PatchCardData
        """
        from ..db.repo import PatchCardData as RepoPatchCardData

        from .helpers import extract_common_patch_card_fields

        common_fields = extract_common_patch_card_fields(data)
        return RepoPatchCardData(**common_fields)

    async def find_by_message_id_header(
        self, message_id_header: str
    ) -> Optional[PatchCard]:
        """根据 message_id_header 查找 PATCH 卡片

        Args:
            message_id_header: PATCH message_id_header

        Returns:
            PATCH 卡片数据，如果不存在则返回 None
        """
        try:
            repo_data = await self.patch_card_repo.find_by_message_id_header(
                message_id_header
            )
            return self._repo_data_to_service_data(repo_data) if repo_data else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to find patch card by message_id_header: {e}", exc_info=True
            )
            return None

    async def exists_by_message_id_header(self, message_id_header: str) -> bool:
        """检查是否已存在 PATCH 卡片

        Args:
            message_id_header: PATCH message_id_header

        Returns:
            True 如果存在，False 如果不存在
        """
        try:
            return await self.patch_card_repo.exists_by_message_id_header(
                message_id_header
            )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to check if patch card exists by message_id_header: {e}",
                exc_info=True,
            )
            return False

    async def find_by_series_message_id(
        self, series_message_id: str
    ) -> Optional[PatchCard]:
        """根据系列 message_id 查找 PATCH 卡片

        Args:
            series_message_id: 系列 message_id

        Returns:
            PATCH 卡片数据，如果不存在则返回 None
        """
        try:
            repo_data = await self.patch_card_repo.find_by_series_message_id(
                series_message_id
            )
            return self._repo_data_to_service_data(repo_data) if repo_data else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to find patch card by series_message_id: {e}",
                exc_info=True,
            )
            return None

    async def find_series_patch_card(
        self, series_message_id: str
    ) -> Optional[PatchCard]:
        """查找系列 PATCH 卡片（Cover Letter）

        Args:
            series_message_id: 系列 message_id

        Returns:
            系列 PATCH 卡片数据，如果不存在则返回 None
        """
        try:
            repo_data = await self.patch_card_repo.find_series_patch_card(
                series_message_id
            )
            return self._repo_data_to_service_data(repo_data) if repo_data else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to find series patch card: {e}", exc_info=True)
            return None

    async def create(self, data: PatchCard) -> Optional[PatchCard]:
        """创建 PATCH 卡片记录

        Args:
            data: PATCH 卡片数据（service 层）

        Returns:
            创建的 PATCH 卡片数据，失败返回 None
        """
        try:
            repo_data = self._convert_to_repo_data(data)
            repo_result = await self.patch_card_repo.create(repo_data)
            return self._repo_data_to_service_data(repo_result) if repo_result else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to create patch card: {e}", exc_info=True)
            return None

    async def update_platform_message_id(
        self, message_id_header: str, platform_message_id: str
    ) -> Optional[PatchCard]:
        """更新 PATCH 的 platform_message_id

        Args:
            message_id_header: PATCH 的 message_id_header
            platform_message_id: 新的 platform_message_id

        Returns:
            更新后的 PATCH 卡片数据，如果不存在则返回 None
        """
        try:
            repo_data = await self.patch_card_repo.update_platform_message_id(
                message_id_header, platform_message_id
            )
            return self._repo_data_to_service_data(repo_data) if repo_data else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to update platform_message_id: {e}", exc_info=True)
            return None

    async def mark_as_has_thread(self, message_id_header: str) -> bool:
        """标记 PATCH 为已建立 Thread

        Args:
            message_id_header: PATCH 的 message_id_header

        Returns:
            成功返回 True，失败返回 False
        """
        try:
            result = await self.patch_card_repo.mark_as_has_thread(message_id_header)
            return result is not None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to mark patch as has_thread: {e}", exc_info=True)
            return False

    async def get_series_patches(self, series_message_id: str) -> List[SeriesPatchInfo]:
        """获取系列的所有 PATCH（从 feed_message 表查询，因为子 PATCH 不存储在 patch_cards 表中）

        Args:
            series_message_id: 系列 message_id

        Returns:
            系列 PATCH 信息列表
        """
        try:
            # 使用 repository 查询系列的所有 PATCH（包括子 PATCH）
            series_feed_messages = await self.feed_message_repo.find_series_patches(
                series_message_id
            )

            if series_feed_messages:
                # 转换为 SeriesPatchInfo 对象列表
                series_patches_info = self._build_series_patches_info(
                    series_feed_messages
                )
                logger.info(
                    f"Queried {len(series_patches_info)} patches from feed_message "
                    f"table for series {series_message_id}: "
                    f"indices=[{', '.join(str(p.patch_index) for p in series_patches_info)}]"
                )
                return series_patches_info

            return []
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to get series patches: {e}", exc_info=True)
            return []

    def _build_series_patches_info(
        self, series_feed_messages: List
    ) -> List[SeriesPatchInfo]:
        """构建系列 PATCH 信息列表

        Args:
            series_feed_messages: Feed 消息列表

        Returns:
            系列 PATCH 信息列表
        """
        from ..feed.feed_message_classifier import parse_patch_subject

        series_patches_info = []
        for msg in series_feed_messages:
            patch_info = parse_patch_subject(msg.subject)
            patch_index = patch_info.index if patch_info.index is not None else 0

            # 调试：记录解析结果
            if patch_index == 1:
                logger.debug(
                    f"Building series patch info: index={patch_index}, "
                    f"subject={msg.subject[:60]}, "
                    f"parsed_index={patch_info.index}, "
                    f"parsed_total={patch_info.total}"
                )

            series_patches_info.append(
                SeriesPatchInfo(
                    subject=msg.subject,
                    patch_index=patch_index,
                    patch_total=patch_info.total or 0,
                    message_id=msg.message_id_header,
                    url=msg.url or "",
                )
            )
        return series_patches_info

    async def get_patch_card_with_series_data(
        self, message_id_header: str
    ) -> Optional[PatchCard]:
        """获取 PatchCard 并自动填充 series_patches（供 Plugins 层渲染使用）

        这个方法做所有的业务逻辑：
        - 查询 PatchCard
        - 如果是系列，自动查询所有 patches
        - 返回包含完整数据的 PatchCard

        Args:
            message_id_header: PATCH message_id_header

        Returns:
            包含完整渲染数据的 PatchCard，如果不存在返回 None
        """
        # 1. 查询 PatchCard
        patch_card = await self.find_by_message_id_header(message_id_header)
        if not patch_card:
            return None

        # 2. 如果是系列 PATCH，自动填充 series_patches
        if patch_card.is_series_patch and patch_card.series_message_id:
            series_patches = await self.get_series_patches(patch_card.series_message_id)
            patch_card.series_patches = series_patches

        return patch_card

    async def find_feed_message_by_id(self, message_id_header: str):
        """从 feed_messages 查找消息（供 watch 命令使用）

        Args:
            message_id_header: PATCH message_id_header

        Returns:
            FeedMessageData 对象，如果不存在返回 None
        """
        return await self.feed_message_repo.find_by_message_id_header(message_id_header)

    async def create_patch_card_for_discord(
        self,
        feed_message,
        platform_message_id: str,
        platform_channel_id: str,
        timeout_hours: int = 24,
    ) -> Optional[PatchCard]:
        """创建 PatchCard（供 Plugins 层使用，包含所有业务逻辑）

        这个方法做所有的业务逻辑：
        - 判断是单 patch 还是系列 patch
        - 计算过期时间
        - 查询 series patches（如果是系列）
        - 保存到数据库
        - 返回包含完整数据的 PatchCard

        Args:
            feed_message: Feed 消息对象
            platform_message_id: Discord 消息 ID
            platform_channel_id: Discord 频道 ID
            timeout_hours: 超时小时数

        Returns:
            创建的 PatchCard（包含 series_patches），失败返回 None
        """
        try:
            from datetime import timedelta
            from datetime import datetime as dt

            # 计算过期时间（业务逻辑）
            expires_at = dt.utcnow() + timedelta(hours=timeout_hours)

            # 判断是否是系列 PATCH（业务逻辑）
            is_series = feed_message.is_series_patch or (
                feed_message.patch_total and feed_message.patch_total > 1
            )

            # 构建 PatchCard 数据
            patch_card = PatchCard(
                message_id_header=feed_message.message_id_header,
                subsystem_name=feed_message.subsystem_name,
                platform_message_id=platform_message_id,
                platform_channel_id=platform_channel_id,
                subject=feed_message.subject,
                author=feed_message.author,
                url=feed_message.url,
                expires_at=expires_at,
                is_series_patch=is_series,
                series_message_id=feed_message.series_message_id,
                patch_version=feed_message.patch_version,
                patch_index=feed_message.patch_index,
                patch_total=feed_message.patch_total,
                has_thread=False,
                is_cover_letter=feed_message.is_cover_letter,
            )

            # 保存到数据库
            created_card = await self.create(patch_card)

            # 如果是系列 PATCH，填充 series_patches
            if created_card and is_series and feed_message.series_message_id:
                series_patches = await self.get_series_patches(
                    feed_message.series_message_id
                )
                created_card.series_patches = series_patches

            logger.info(
                f"Created PatchCard for Discord: {feed_message.message_id_header}, "
                f"is_series={is_series}, platform_message_id={platform_message_id}"
            )

            return created_card

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to create patch card for discord: {e}", exc_info=True)
            return None


# 工厂函数已移至 lkml.db.database 模块以避免循环导入
# 不再在此模块导入，直接从 lkml.db.database 或 lkml.service 导入
