"""Feed 消息仓储类"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import FeedMessageModel

logger = logging.getLogger(__name__)


@dataclass
class FeedMessageData:
    """Feed 消息数据对象（Repository 层）"""

    subsystem_name: str
    message_id_header: str
    subject: str
    author: str
    author_email: str
    message_id: Optional[str] = None
    in_reply_to_header: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    received_at: Optional[object] = None
    is_patch: bool = False
    is_reply: bool = False
    is_series_patch: bool = False
    patch_version: Optional[str] = None
    patch_index: Optional[int] = None
    patch_total: Optional[int] = None
    is_cover_letter: bool = False
    series_message_id: Optional[str] = None
    id: Optional[int] = None  # 数据库 ID（Repository 层内部使用，不暴露给上层）


class FeedMessageRepository:
    """Feed 消息仓储类，提供 Feed 消息的数据访问操作"""

    def __init__(self, session: AsyncSession):
        """初始化仓库

        Args:
            session: 数据库会话（由 DB 层创建并维护）
        """
        self.session = session

    @staticmethod
    def _model_to_data(model: FeedMessageModel) -> FeedMessageData:
        """将 Model 转换为 Data

        Args:
            model: FeedMessageModel 对象

        Returns:
            FeedMessageData 对象
        """
        return FeedMessageData(
            id=model.id,
            subsystem_name=model.subsystem_name,
            message_id=model.message_id,
            message_id_header=model.message_id_header,
            in_reply_to_header=model.in_reply_to_header,
            subject=model.subject,
            author=model.author,
            author_email=model.author_email,
            content=model.content,
            url=model.url,
            received_at=model.received_at,
            is_patch=model.is_patch,
            is_reply=model.is_reply,
            is_series_patch=model.is_series_patch,
            patch_version=model.patch_version,
            patch_index=model.patch_index,
            patch_total=model.patch_total,
            is_cover_letter=model.is_cover_letter,
            series_message_id=model.series_message_id,
        )

    async def find_by_message_id_header(
        self, message_id_header: str
    ) -> Optional[FeedMessageData]:
        """根据 Message-ID Header 查找 Feed 消息

        Args:
            message_id_header: Message-ID 头部

        Returns:
            Feed 消息数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(FeedMessageModel).where(
                FeedMessageModel.message_id_header == message_id_header
            )
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def find_by_message_id(self, message_id: str) -> Optional[FeedMessageData]:
        """根据消息ID查找 Feed 消息

        Args:
            message_id: 消息唯一标识

        Returns:
            Feed 消息数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(FeedMessageModel).where(FeedMessageModel.message_id == message_id)
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def create(
        self,
        *,
        data: FeedMessageData,
    ) -> FeedMessageData:
        """创建 Feed 消息

        Args:
            data: Feed 消息数据对象

        Returns:
            创建的 Feed 消息数据
        """
        # 使用辅助函数提取公共字段以减少重复代码
        from ...service.helpers import extract_common_feed_message_fields

        feed_message_data = extract_common_feed_message_fields(data)
        entity = FeedMessageModel(**feed_message_data)
        self.session.add(entity)
        await self.session.flush()
        return self._model_to_data(entity)

    async def _update_existing_feed_message(
        self, data: FeedMessageData
    ) -> FeedMessageData:
        """更新现有的 Feed 消息记录"""
        result = await self.session.execute(
            select(FeedMessageModel).where(
                FeedMessageModel.message_id_header == data.message_id_header
            )
        )
        existing_model = result.scalar_one_or_none()
        if not existing_model:
            return None

        # 更新现有记录
        existing_model.subsystem_name = data.subsystem_name
        existing_model.message_id = data.message_id
        existing_model.in_reply_to_header = data.in_reply_to_header
        existing_model.subject = data.subject
        existing_model.author = data.author
        existing_model.author_email = data.author_email
        existing_model.content = data.content
        existing_model.url = data.url
        if data.received_at:
            existing_model.received_at = data.received_at
        existing_model.is_patch = data.is_patch
        existing_model.is_reply = data.is_reply
        existing_model.is_series_patch = data.is_series_patch
        existing_model.patch_version = data.patch_version
        existing_model.patch_index = data.patch_index
        existing_model.patch_total = data.patch_total
        existing_model.is_cover_letter = data.is_cover_letter
        existing_model.series_message_id = data.series_message_id
        await self.session.flush()
        return self._model_to_data(existing_model)

    async def create_or_update(
        self,
        *,
        data: FeedMessageData,
    ) -> FeedMessageData:
        """创建或更新 Feed 消息

        Args:
            data: Feed 消息数据对象

        Returns:
            创建或更新的 Feed 消息数据
        """
        existing_data = await self.find_by_message_id_header(data.message_id_header)
        if existing_data:
            return await self._update_existing_feed_message(data)

        # 创建新记录
        # 在并发情况下，可能多个请求同时检查记录不存在，然后都尝试插入
        # 捕获 IntegrityError 并重试查询
        try:
            return await self.create(data=data)
        except IntegrityError as e:
            # 如果是 UNIQUE 约束错误，说明记录在检查后、插入前被其他请求创建了
            # 重新查询并返回现有记录
            if "UNIQUE constraint failed" in str(e) and "message_id_header" in str(e):
                logger.debug(
                    f"Concurrent insert detected for message_id_header={data.message_id_header}, "
                    f"retrying query"
                )
                existing_data = await self.find_by_message_id_header(
                    data.message_id_header
                )
                if existing_data:
                    return await self._update_existing_feed_message(data)
            # 如果是其他 IntegrityError，重新抛出
            raise

    async def find_by_series_message_id(
        self, series_message_id: str
    ) -> list[FeedMessageData]:
        """查找系列的所有 PATCH

        Args:
            series_message_id: 系列 message_id
        Returns:
            系列的所有 PATCH 数据列表，按 patch_index 和 received_at 排序
        """
        result = await self.session.execute(
            select(FeedMessageModel)
            .where(FeedMessageModel.series_message_id == series_message_id)
            .order_by(FeedMessageModel.patch_index, FeedMessageModel.received_at)
        )
        models = result.scalars().all()
        return [self._model_to_data(model) for model in models]

    async def find_replies_to(
        self, message_id_header: str, limit: int = 10
    ) -> list[FeedMessageData]:
        """查找回复某个消息的所有 REPLY

        使用 LIKE 查询，因为 in_reply_to_header 可能包含：
        - 尖括号：<message_id>
        - 多个 message_id（邮件头可能包含多个 In-Reply-To）

        Args:
            message_id_header: 被回复的消息 ID
            limit: 最多返回的 REPLY 数量

        Returns:
            REPLY 消息数据列表，按时间正序排序（最早的在前）
        """
        result = await self.session.execute(
            select(FeedMessageModel)
            .where(
                or_(
                    FeedMessageModel.in_reply_to_header
                    == message_id_header,  # 精确匹配
                    FeedMessageModel.in_reply_to_header.like(
                        f"%{message_id_header}%"
                    ),  # 模糊匹配
                )
            )
            .order_by(FeedMessageModel.received_at.asc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [self._model_to_data(model) for model in models]

    async def find_series_patches(
        self, series_message_id: str
    ) -> list[FeedMessageData]:
        """查找系列的所有 PATCH

        Args:
            series_message_id: 系列 message_id

        Returns:
            系列的所有 PATCH 数据列表，按 patch_index 和 received_at 排序
        """
        result = await self.session.execute(
            select(FeedMessageModel)
            .where(
                or_(
                    FeedMessageModel.message_id_header == series_message_id,
                    FeedMessageModel.series_message_id == series_message_id,
                )
            )
            .where(FeedMessageModel.is_patch.is_(True))  # 只查询 PATCH
            .order_by(FeedMessageModel.patch_index, FeedMessageModel.received_at)
        )
        models = result.scalars().all()
        return [self._model_to_data(model) for model in models]
