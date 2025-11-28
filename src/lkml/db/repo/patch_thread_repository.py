"""PATCH Thread 仓库

负责 PATCH Thread 的数据库操作。
这是平台无关的仓库，可以用于任何支持 Thread 功能的平台。
"""

import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..models import PatchThreadModel

logger = logging.getLogger(__name__)


@dataclass
class PatchThreadData:
    """PATCH Thread 数据（Repository 层）"""

    patch_card_message_id_header: str
    thread_id: str
    thread_name: str
    is_active: bool = True
    overview_message_id: Optional[str] = None
    sub_patch_messages: Optional[dict] = None  # {patch_index: message_id}
    created_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None


class PatchThreadRepository:
    """PATCH Thread 仓库"""

    def __init__(self, session: AsyncSession):
        """初始化仓库

        Args:
            session: 数据库会话（由 DB 层创建并维护）
        """
        self.session = session

    @staticmethod
    def _model_to_data(model: PatchThreadModel) -> PatchThreadData:
        """将 Model 转换为 Data

        Args:
            model: PatchThreadModel 对象

        Returns:
            PatchThreadData 对象
        """
        return PatchThreadData(
            patch_card_message_id_header=model.patch_card_message_id_header,
            thread_id=model.thread_id,
            thread_name=model.thread_name,
            is_active=model.is_active,
            overview_message_id=model.overview_message_id,
            sub_patch_messages=model.sub_patch_messages,
            created_at=model.created_at,
            archived_at=model.archived_at,
        )

    async def create(self, data: PatchThreadData) -> PatchThreadData:
        """创建 PATCH Thread 记录

        Args:
            data: PATCH Thread 数据

        Returns:
            创建的 PATCH Thread 对象
        """
        thread = PatchThreadModel(
            patch_card_message_id_header=data.patch_card_message_id_header,
            thread_id=data.thread_id,
            thread_name=data.thread_name,
        )
        self.session.add(thread)
        await self.session.flush()
        logger.debug(f"Created PATCH Thread: {data.thread_id}")
        return self._model_to_data(thread)

    async def find_by_thread_id(self, thread_id: str) -> Optional[PatchThreadData]:
        """根据 thread_id 查找 PATCH Thread

        Args:
            thread_id: Thread ID

        Returns:
            PATCH Thread 数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchThreadModel).where(PatchThreadModel.thread_id == thread_id)
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def find_by_message_id_header(
        self, message_id_header: str
    ) -> Optional[PatchThreadData]:
        """根据 PATCH 卡片的 message_id_header 查找 Thread

        Args:
            message_id_header: PATCH 卡片的 message_id_header

        Returns:
            PATCH Thread 数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchThreadModel).where(
                PatchThreadModel.patch_card_message_id_header == message_id_header
            )
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def update_overview_message_id(
        self, thread_id: str, overview_message_id: str
    ) -> bool:
        """更新 Thread 的 Overview 消息 ID

        Args:
            thread_id: Thread ID
            overview_message_id: Overview 消息 ID

        Returns:
            是否更新成功
        """
        result = await self.session.execute(
            update(PatchThreadModel)
            .where(PatchThreadModel.thread_id == thread_id)
            .values(overview_message_id=overview_message_id)
        )
        if result.rowcount > 0:
            logger.debug(
                f"Updated Thread overview_message_id: {thread_id}, message_id={overview_message_id}"
            )
            return True
        logger.warning(f"Thread not found for overview_message_id update: {thread_id}")
        return False

    async def update_patch_card_message_id_header(
        self, thread_id: str, patch_card_message_id_header: str
    ) -> bool:
        """更新 Thread 的 patch_card_message_id_header

        Args:
            thread_id: Thread ID
            patch_card_message_id_header: 新的 patch_card_message_id_header

        Returns:
            是否更新成功
        """
        result = await self.session.execute(
            update(PatchThreadModel)
            .where(PatchThreadModel.thread_id == thread_id)
            .values(patch_card_message_id_header=patch_card_message_id_header)
        )
        if result.rowcount > 0:
            logger.debug(
                f"Updated Thread patch_card_message_id_header: {thread_id}, "
                f"message_id_header={patch_card_message_id_header}"
            )
            return True
        logger.warning(
            f"Thread not found for patch_card_message_id_header update: {thread_id}"
        )
        return False

    async def update_sub_patch_messages(
        self, thread_id: str, sub_patch_messages: dict
    ) -> bool:
        """更新 Thread 的 sub_patch_messages

        Args:
            thread_id: Thread ID
            sub_patch_messages: 子 PATCH 消息映射 {patch_index: message_id}

        Returns:
            是否更新成功
        """
        result = await self.session.execute(
            update(PatchThreadModel)
            .where(PatchThreadModel.thread_id == thread_id)
            .values(sub_patch_messages=sub_patch_messages)
        )
        if result.rowcount > 0:
            logger.debug(
                f"Updated Thread sub_patch_messages: {thread_id}, count={len(sub_patch_messages)}"
            )
            return True
        logger.warning(f"Thread not found for sub_patch_messages update: {thread_id}")
        return False

    async def delete(self, thread_id: str) -> bool:
        """删除 Thread 记录

        Args:
            thread_id: Thread ID

        Returns:
            是否删除成功
        """
        result = await self.session.execute(
            select(PatchThreadModel).where(PatchThreadModel.thread_id == thread_id)
        )
        thread = result.scalar_one_or_none()
        if thread:
            await self.session.delete(thread)
            await self.session.flush()
            logger.debug(f"Deleted PATCH Thread: {thread_id}")
            return True
        return False

    async def mark_as_inactive(self, thread_id: str) -> bool:
        """将 Thread 标记为不活跃

        Args:
            thread_id: Thread ID

        Returns:
            是否更新成功
        """
        result = await self.session.execute(
            update(PatchThreadModel)
            .where(PatchThreadModel.thread_id == thread_id)
            .values(is_active=False)
        )
        if result.rowcount > 0:
            logger.debug(f"Marked Thread as inactive: {thread_id}")
            return True
        logger.warning(f"Thread not found for mark_as_inactive: {thread_id}")
        return False

    async def count_active_threads(self) -> int:
        """统计活跃的 Thread 数量

        Returns:
            活跃 Thread 的数量
        """
        from sqlalchemy import func

        # pylint: disable=not-callable
        # func.count is callable in SQLAlchemy, this is a false positive
        result = await self.session.execute(
            select(func.count(PatchThreadModel.id)).where(
                PatchThreadModel.is_active.is_(True)
            )
        )
        count = result.scalar_one()
        return count or 0
