"""邮件监控编排器（与调度器同目录层级，但置于 feed 包）

负责协调多个子系统的监控任务，聚合结果并统一管理。
"""

from datetime import datetime
from typing import List, Optional, Tuple

from nonebot.log import logger

from ..config import Config
from ..db.database import Database
from .feed import FeedProcessor
from .types import (
    FeedProcessResult,
    MonitoringResult,
    MonitoringStatistics,
    SubsystemMonitoringResult,
)


class LKMLFeedMonitor:  # pylint: disable=too-few-public-methods
    """循环各子系统、调用处理逻辑并聚合结果

    负责遍历所有配置的子系统，调用 FeedProcessor 处理每个子系统的 feed，
    并将所有结果聚合为一个 MonitoringResult 对象。
    主要职责是编排监控流程，核心公共方法是 run_monitoring。
    """

    def __init__(
        self, *, config: Config, processor: FeedProcessor, database: Database = None
    ) -> None:
        """初始化监控器

        Args:
            config: 配置实例
            processor: Feed 处理器
            database: 数据库实例（可选，用于查询订阅状态）
        """
        self.config = config
        self.processor = processor
        self.database = database

    def _create_empty_result(self, start_time: datetime) -> MonitoringResult:
        """创建空的监控结果"""
        statistics = MonitoringStatistics(
            total_subsystems=0,
            processed_subsystems=0,
            total_new_count=0,
            total_reply_count=0,
            error_count=0,
        )
        return MonitoringResult(
            statistics=statistics,
            results=[],
            start_time=start_time,
            end_time=datetime.now(),
            errors=None,
        )

    async def _process_subsystem(
        self, subsystem_name: str
    ) -> Tuple[FeedProcessResult, Optional[str]]:
        """处理单个子系统，返回结果和错误信息"""
        feed_url = f"https://lore.kernel.org/{subsystem_name}/new.atom"
        try:
            result = await self.processor.process_feed(subsystem_name, feed_url)
            return (result, None)
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            error_msg = f"Failed to process feed for {subsystem_name} ({feed_url}): {e}"
            logger.error(error_msg, exc_info=True)
            empty_result = FeedProcessResult(
                subsystem=subsystem_name, new_count=0, reply_count=0, entries=[]
            )
            return (empty_result, error_msg)

    def _convert_to_subsystem_results(
        self, results: List[FeedProcessResult]
    ) -> List[SubsystemMonitoringResult]:
        """将 FeedProcessResult 列表转换为 SubsystemMonitoringResult 列表"""
        return [
            SubsystemMonitoringResult(
                subsystem=result.subsystem,
                new_count=result.new_count,
                reply_count=result.reply_count,
                entries=result.entries,
                subscribed_users=[],
                title=f"{result.subsystem} 邮件列表",
            )
            for result in results
        ]

    async def run_monitoring(self) -> MonitoringResult:
        """运行一次监控任务

        Returns:
            监控结果，包含所有子系统的处理结果和统计信息
        """
        start_time = datetime.now()
        config = self.config

        supported_subsystems = config.get_supported_subsystems()
        if not supported_subsystems:
            logger.warning(
                "No supported subsystems found. Check vger cache and manual configuration."
            )

        subscribed_subsystems = await self._get_subscribed_subsystems()
        if not subscribed_subsystems:
            logger.info("No subscribed subsystems found, skipping feed monitoring")
            return self._create_empty_result(start_time)

        logger.info(f"Supported subsystems: {supported_subsystems}")
        logger.info(f"Subscribed subsystems to monitor: {subscribed_subsystems}")

        results: list[FeedProcessResult] = []
        errors: list[str] = []
        total_new_count = 0
        total_reply_count = 0

        for subsystem_name in subscribed_subsystems:
            result, error = await self._process_subsystem(subsystem_name)
            results.append(result)
            total_new_count += result.new_count
            total_reply_count += result.reply_count
            if error:
                errors.append(error)

        end_time = datetime.now()
        subsystem_results = self._convert_to_subsystem_results(results)

        statistics = MonitoringStatistics(
            total_subsystems=len(subscribed_subsystems),
            processed_subsystems=len(subsystem_results),
            total_new_count=total_new_count,
            total_reply_count=total_reply_count,
            error_count=len(errors) if errors else 0,
        )
        return MonitoringResult(
            statistics=statistics,
            results=subsystem_results,
            start_time=start_time,
            end_time=end_time,
            errors=errors if errors else None,
        )

    async def _get_subscribed_subsystems(self) -> list[str]:
        """获取已订阅的子系统列表

        Returns:
            已订阅的子系统名称列表
        """
        if not self.database:
            logger.warning("Database not available, cannot query subscribed subsystems")
            return []

        try:
            # pylint: disable=import-outside-toplevel  # noqa: PLC0415
            from sqlalchemy import (
                select,
            )
            from ..db.models import (
                Subsystem,
            )

            async with self.database.get_db_session() as session:
                result = await session.execute(
                    select(Subsystem.name).where(Subsystem.subscribed)
                )
                return [row[0] for row in result.fetchall()]
        except ImportError as e:
            if "greenlet" in str(e).lower():
                logger.error(
                    "Failed to get subscribed subsystems: greenlet library is required. "
                    "Please install it with: pip install greenlet"
                )
            else:
                logger.error(f"Failed to get subscribed subsystems: {e}", exc_info=True)
            return []
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to get subscribed subsystems: {e}", exc_info=True)
            return []


# 由上层注入配置与依赖创建实例
