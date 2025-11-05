"""LKML 统一服务门面"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .monitoring_service import monitoring_service
from .query_service import query_service
from .subsystem_service import subsystem_service

if TYPE_CHECKING:
    from ..scheduler import LKMLScheduler


class LKMLService:
    """LKML 统一服务门面

    此类作为统一入口，将请求转发到具体的服务类。
    """

    # 委托到子系统服务
    async def subscribe_subsystem(
        self, operator_id: str, operator_name: str, subsystem_name: str
    ) -> bool:
        """订阅子系统"""
        return await subsystem_service.subscribe_subsystem(
            operator_id, operator_name, subsystem_name
        )

    async def unsubscribe_subsystem(
        self, operator_id: str, operator_name: str, subsystem_name: str
    ) -> bool:
        """取消订阅子系统"""
        return await subsystem_service.unsubscribe_subsystem(
            operator_id, operator_name, subsystem_name
        )

    async def get_subscribed_subsystems(self) -> list[str]:
        """获取已订阅的子系统列表"""
        return await subsystem_service.get_subscribed_subsystems()

    # 委托到监控服务
    async def start_monitoring(
        self,
        operator_id: str,
        operator_name: str,
        scheduler: LKMLScheduler,
    ) -> bool:
        """启动监控"""
        return await monitoring_service.start_monitoring(
            operator_id, operator_name, scheduler
        )

    async def stop_monitoring(
        self,
        operator_id: str,
        operator_name: str,
        scheduler: LKMLScheduler,
    ) -> bool:
        """停止监控"""
        return await monitoring_service.stop_monitoring(
            operator_id, operator_name, scheduler
        )

    # 委托到查询服务
    async def get_latest_news(
        self, subsystem_name: Optional[str] = None, count: int = 5
    ) -> list[dict[str, str | int | None]]:
        """获取最新新闻"""
        return await query_service.get_latest_news(subsystem_name, count)

    async def get_operation_logs(
        self, limit: int = 50
    ) -> list[dict[str, str | int | None]]:
        """获取操作日志"""
        return await query_service.get_operation_logs(limit)


# 全局服务实例
lkml_service = LKMLService()
