"""子系统仓储类"""

from __future__ import annotations

from sqlalchemy import select
from ..models import Subsystem


class SubsystemRepository:
    """子系统仓储类，提供子系统的数据访问操作"""

    async def get_or_create(self, session, name: str) -> Subsystem:
        """获取或创建子系统

        Args:
            session: 数据库会话
            name: 子系统名称

        Returns:
            子系统对象
        """
        result = await session.execute(select(Subsystem).where(Subsystem.name == name))
        subsystem = result.scalar_one_or_none()
        if subsystem is None:
            subsystem = Subsystem(name=name, subscribed=True)
            session.add(subsystem)
            await session.flush()
        return subsystem

    async def list_names(self, session) -> list[str]:
        """列出所有子系统名称

        Args:
            session: 数据库会话

        Returns:
            子系统名称列表
        """
        result = await session.execute(select(Subsystem.name))
        return [row[0] for row in result.all()]


# 单例实例（全局实例，用于方便访问）
SUBSYSTEM_REPO = SubsystemRepository()
