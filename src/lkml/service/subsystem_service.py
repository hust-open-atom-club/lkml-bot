"""子系统服务"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nonebot.log import logger

from ..config import get_config
from ..db.database import get_database
from ..db.models import Subsystem
from .operation_log_service import OperationParams, log_operation


class SubsystemService:
    """子系统订阅管理服务"""

    async def subscribe_subsystem(
        self, operator_id: str, operator_name: str, subsystem_name: str
    ) -> bool:
        """订阅子系统

        Args:
            operator_id: 操作者ID
            operator_name: 操作者名称
            subsystem_name: 子系统名称

        Returns:
            是否成功
        """
        try:
            config = get_config()
            database = get_database()
            async with database.get_db_session() as session:
                # 检查子系统是否支持
                supported_subsystems = config.get_supported_subsystems()
                if subsystem_name not in supported_subsystems:
                    return False

                # 获取或创建子系统
                subsystem = await self._get_or_create_subsystem(session, subsystem_name)

                # 检查是否已经订阅
                if subsystem.subscribed:
                    return True  # 已经订阅

                # 更新订阅状态
                subsystem.subscribed = True  # type: ignore[assignment]
                await session.commit()

                # 记录操作日志
                await log_operation(  # pylint: disable=duplicate-code
                    session,
                    OperationParams(
                        operator_id=operator_id,
                        operator_name=operator_name,
                        action="subscribe",
                        subsystem_name=subsystem_name,
                    ),
                )

                logger.info(f"Operator {operator_name} subscribed to {subsystem_name}")
                return True
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to subscribe subsystem: {e}")
            return False

    async def unsubscribe_subsystem(
        self, operator_id: str, operator_name: str, subsystem_name: str
    ) -> bool:
        """取消订阅子系统

        Args:
            operator_id: 操作者ID
            operator_name: 操作者名称
            subsystem_name: 子系统名称

        Returns:
            是否成功
        """
        try:
            database = get_database()
            async with database.get_db_session() as session:
                # 获取子系统
                subsystem_result = await session.execute(
                    select(Subsystem).where(Subsystem.name == subsystem_name)
                )
                subsystem = subsystem_result.scalar_one_or_none()

                if not subsystem:
                    return False

                # 更新订阅状态
                subsystem.subscribed = False  # type: ignore[assignment]
                await session.commit()

                # 记录操作日志
                await log_operation(  # pylint: disable=duplicate-code
                    session,
                    OperationParams(
                        operator_id=operator_id,
                        operator_name=operator_name,
                        action="unsubscribe",
                        subsystem_name=subsystem_name,
                    ),
                )

                logger.info(
                    f"Operator {operator_name} unsubscribed from {subsystem_name}"
                )
                return True
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to unsubscribe subsystem: {e}")
            return False

    async def get_subscribed_subsystems(self) -> list[str]:
        """获取已订阅的子系统列表

        Returns:
            已订阅的子系统名称列表
        """
        try:
            database = get_database()
            async with database.get_db_session() as session:
                result = await session.execute(
                    select(Subsystem.name).where(Subsystem.subscribed)
                )
                return [row[0] for row in result.fetchall()]
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to get subscribed subsystems: {e}")
            return []

    async def _get_or_create_subsystem(
        self, session: AsyncSession, subsystem_name: str
    ) -> Subsystem:
        """获取或创建子系统

        Args:
            session: 数据库会话
            subsystem_name: 子系统名称

        Returns:
            子系统对象
        """
        result = await session.execute(
            select(Subsystem).where(Subsystem.name == subsystem_name)
        )
        subsystem = result.scalar_one_or_none()

        if not subsystem:
            subsystem = Subsystem(name=subsystem_name, subscribed=False)
            session.add(subsystem)
            await session.flush()  # 获取ID

        return subsystem


# 全局服务实例
subsystem_service = SubsystemService()
