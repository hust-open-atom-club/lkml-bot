"""监控服务"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.log import logger

from ..db.database import get_database
from .operation_log_service import OperationParams, log_operation

if TYPE_CHECKING:
    from ..scheduler import LKMLScheduler


class MonitoringService:
    """监控控制服务"""

    async def start_monitoring(
        self,
        operator_id: str,
        operator_name: str,
        scheduler: LKMLScheduler,
    ) -> bool:
        """启动监控

        Args:
            operator_id: 操作者ID
            operator_name: 操作者名称
            scheduler: 调度器实例

        Returns:
            是否成功
        """
        try:
            if scheduler.is_running:
                return False  # 已经在运行

            await scheduler.start()

            # 记录操作日志
            database = get_database()
            async with database.get_db_session() as session:
                await log_operation(  # pylint: disable=duplicate-code
                    session,
                    OperationParams(
                        operator_id=operator_id,
                        operator_name=operator_name,
                        action="start_monitor",
                    ),
                )

            logger.info(f"Operator {operator_name} started monitoring")
            return True
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to start monitoring: {e}")
            return False

    async def stop_monitoring(
        self,
        operator_id: str,
        operator_name: str,
        scheduler: LKMLScheduler,
    ) -> bool:
        """停止监控

        Args:
            operator_id: 操作者ID
            operator_name: 操作者名称
            scheduler: 调度器实例

        Returns:
            是否成功
        """
        try:
            if not scheduler.is_running:
                return False  # 已经停止

            await scheduler.stop()

            # 记录操作日志
            database = get_database()
            async with database.get_db_session() as session:
                await log_operation(  # pylint: disable=duplicate-code
                    session,
                    OperationParams(
                        operator_id=operator_id,
                        operator_name=operator_name,
                        action="stop_monitor",
                    ),
                )

            logger.info(f"Operator {operator_name} stopped monitoring")
            return True
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to stop monitoring: {e}")
            return False


# 全局服务实例
monitoring_service = MonitoringService()
