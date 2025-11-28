"""PATCH 订阅仓库

负责 PATCH 订阅的数据库操作。
"""

import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import PatchCardModel

logger = logging.getLogger(__name__)


@dataclass
class PatchCardData:
    """PATCH 卡片数据（Repository 层）"""

    message_id_header: str
    subsystem_name: str
    platform_message_id: str
    platform_channel_id: str
    subject: str
    author: str
    url: Optional[str] = None
    expires_at: Optional[datetime] = None
    is_series_patch: bool = False
    series_message_id: Optional[str] = None
    patch_version: Optional[str] = None
    patch_index: Optional[int] = None
    patch_total: Optional[int] = None
    id: Optional[int] = None  # 数据库 ID（Repository 层内部使用，不暴露给上层）
    has_thread: bool = False  # 是否已建立 Thread


class PatchCardRepository:  # pylint: disable=too-many-instance-attributes
    """PATCH 卡片仓库"""

    def __init__(self, session: AsyncSession):
        """初始化仓库

        Args:
            session: 数据库会话（由 DB 层创建并维护）
        """
        self.session = session

    @staticmethod
    def _model_to_data(model: PatchCardModel) -> PatchCardData:
        """将 Model 转换为 Data

        Args:
            model: PatchCardModel 对象

        Returns:
            PatchCardData 对象
        """
        return PatchCardData(
            message_id_header=model.message_id_header,
            subsystem_name=model.subsystem_name,
            platform_message_id=model.platform_message_id,
            platform_channel_id=model.platform_channel_id,
            subject=model.subject,
            author=model.author,
            url=model.url,
            expires_at=model.expires_at,
            is_series_patch=model.is_series_patch,
            series_message_id=model.series_message_id,
            patch_version=model.patch_version,
            patch_index=model.patch_index,
            patch_total=model.patch_total,
            id=model.id,
            has_thread=model.has_thread,
        )

    async def create(self, data: PatchCardData) -> PatchCardData:
        """创建 PATCH 订阅记录

        Args:
            data: PATCH 订阅数据

        Returns:
            创建的 PATCH 订阅对象
        """
        patch_card = PatchCardModel(
            message_id_header=data.message_id_header,
            subsystem_name=data.subsystem_name,
            platform_message_id=data.platform_message_id,
            platform_channel_id=data.platform_channel_id,
            subject=data.subject,
            author=data.author,
            url=data.url,
            expires_at=data.expires_at or datetime.utcnow(),
            is_series_patch=data.is_series_patch,
            series_message_id=data.series_message_id,
            patch_version=data.patch_version,
            patch_index=data.patch_index,
            patch_total=data.patch_total,
        )
        self.session.add(patch_card)
        await self.session.flush()
        logger.debug(f"Created PATCH card: {data.message_id_header}")
        return self._model_to_data(patch_card)

    async def find_by_message_id_header(
        self, message_id_header: str
    ) -> Optional[PatchCardData]:
        """根据 message_id_header 查找 PATCH 订阅

        Args:
            message_id_header: PATCH 的 message_id_header

        Returns:
            PATCH 订阅数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchCardModel).where(
                PatchCardModel.message_id_header == message_id_header
            )
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def exists_by_message_id_header(self, message_id_header: str) -> bool:
        """检查是否已存在 PATCH 订阅

        Args:
            message_id_header: PATCH 的 message_id_header

        Returns:
            True 如果存在，False 如果不存在
        """
        result = await self.session.execute(
            select(PatchCardModel).where(
                PatchCardModel.message_id_header == message_id_header
            )
        )
        return result.scalar_one_or_none() is not None

    async def update_platform_message_id(
        self, message_id_header: str, platform_message_id: str
    ) -> Optional[PatchCardData]:
        """更新 PATCH 的 platform_message_id

        Args:
            message_id_header: PATCH 的 message_id_header
            platform_message_id: 新的 platform_message_id

        Returns:
            更新后的 PATCH 卡片数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchCardModel).where(
                PatchCardModel.message_id_header == message_id_header
            )
        )
        patch_card = result.scalar_one_or_none()
        if patch_card:
            patch_card.platform_message_id = platform_message_id
            await self.session.flush()
            logger.debug(
                f"Updated platform_message_id for PATCH: {patch_card.message_id_header}"
            )
            return self._model_to_data(patch_card)
        return None

    async def mark_as_has_thread(
        self, message_id_header: str
    ) -> Optional[PatchCardData]:
        """标记 PATCH 为已建立 Thread

        Args:
            message_id_header: PATCH 的 message_id_header

        Returns:
            更新后的 PATCH 卡片数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchCardModel).where(
                PatchCardModel.message_id_header == message_id_header
            )
        )
        patch_card = result.scalar_one_or_none()
        if patch_card:
            patch_card.has_thread = True
            await self.session.flush()
            logger.debug(f"Marked PATCH as has_thread: {patch_card.message_id_header}")
            return self._model_to_data(patch_card)
        return None

    async def find_by_series_message_id(
        self, series_message_id: str
    ) -> Optional[PatchCardData]:
        """根据系列 message_id 查找已建立 Thread 的 PATCH

        Args:
            series_message_id: 系列 PATCH 的根 message_id

        Returns:
            PATCH 卡片数据，如果不存在或未建立 Thread 则返回 None
        """
        result = await self.session.execute(
            select(PatchCardModel).where(
                PatchCardModel.series_message_id == series_message_id,
                PatchCardModel.has_thread.is_(True),
            )
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def find_series_patch_card(
        self, series_message_id: str
    ) -> Optional[PatchCardData]:
        """查找系列的汇总卡片（已发送平台消息的）

        查找第一个有 platform_message_id 的 PATCH 记录。
        这确保我们总是更新同一张平台卡片。

        Args:
            series_message_id: 系列 PATCH 的根 message_id

        Returns:
            系列汇总卡片数据，如果不存在则返回 None
        """
        # 查找第一个有 platform_message_id 的记录（按创建时间排序）
        result = await self.session.execute(
            select(PatchCardModel)
            .where(
                PatchCardModel.series_message_id == series_message_id,
                PatchCardModel.platform_message_id != "",
                PatchCardModel.platform_message_id.isnot(None),
            )
            .order_by(PatchCardModel.created_at)
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None
