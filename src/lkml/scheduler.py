"""调度器模块（邮件监控调度）"""

import asyncio
import time
import uuid
from typing import Awaitable, Callable, Optional

from nonebot.log import logger

from .config import get_config
from .feed.types import MonitoringResult, SubsystemUpdate


class LKMLScheduler:
    """LKML 定时任务调度器"""

    def __init__(
        self,
        message_sender: Optional[
            Callable[[str, SubsystemUpdate], Awaitable[None]]
        ] = None,
    ):
        """初始化调度器

        Args:
            message_sender: 消息发送回调函数，接收 (subsystem, update_data) 参数
        """
        self.message_sender = message_sender
        self.is_running = False
        self.task = None
        self.run_id: Optional[str] = None
        self.cycle_index: int = 0

    async def send_feed_updates(self, monitoring_result: MonitoringResult) -> None:
        """发送feed更新到各个平台"""
        if not self.message_sender:
            logger.warning("No message sender configured, skipping send")
            return

        try:
            for result in monitoring_result.results:
                logger.info(f"Sending feed updates for {result.subsystem}")
                if result.new_count == 0 and result.reply_count == 0:
                    logger.info(f"No new messages for {result.subsystem}")
                    continue

                # 转换为SubsystemUpdate格式
                update_data = SubsystemUpdate(
                    new_count=result.new_count,
                    reply_count=result.reply_count,
                    entries=result.entries,
                    subscribed_users=result.subscribed_users,
                    title=result.title,
                )

                # 通过回调发送到各个平台
                await self.message_sender(result.subsystem, update_data)
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to send feed updates: {e}")

    async def monitoring_task(self) -> None:
        """监控任务主循环"""
        logger.info(f"Starting LKML monitoring task [run_id={self.run_id}]")

        while self.is_running:
            try:
                self.cycle_index += 1
                cycle_start = time.time()
                logger.info(
                    f"[run_id={self.run_id} cycle={self.cycle_index}] "
                    "About to run feed monitoring..."
                )
                # 运行feed监控
                monitoring_result = await self.monitor.run_monitoring()
                cycle_ms = int((time.time() - cycle_start) * 1000)
                stats = monitoring_result.statistics
                logger.info(
                    f"[run_id={self.run_id} cycle={self.cycle_index}] "
                    f"Completed: processed "
                    f"{stats.processed_subsystems}/"
                    f"{stats.total_subsystems} subsystems, "
                    f"{stats.total_new_count} new, "
                    f"{stats.total_reply_count} replies, "
                    f"took {cycle_ms} ms"
                )

                # 发送更新
                await self.send_feed_updates(monitoring_result)

                # 等待下次检查（使用配置的周期）
                config = get_config()
                interval = config.monitoring_interval
                logger.info(
                    f"[run_id={self.run_id} cycle={self.cycle_index}] "
                    f"Waiting {interval}s until next cycle"
                )
                await asyncio.sleep(interval)

            except (RuntimeError, ValueError, AttributeError) as e:
                logger.error(f"Error in monitoring task: {e}", exc_info=True)
                # 出错时等待1分钟后重试
                await asyncio.sleep(60)

    async def start(self) -> None:
        """启动定时任务"""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return

        # 如果没有任何子系统，跳过启动
        try:
            subsystems = get_config().get_supported_subsystems()
            if not subsystems:
                logger.warning(
                    "No subsystems configured. Scheduler will not start. "
                    "Configure LKML_MANUAL_SUBSYSTEMS or provide vger subsystems."
                )
                return
        except (AttributeError, ValueError, RuntimeError):
            logger.warning(
                "Failed to read subsystems from config; scheduler not started."
            )
            return

        self.is_running = True
        self.run_id = uuid.uuid4().hex[:8]
        self.cycle_index = 0
        self.task = asyncio.create_task(self.monitoring_task())
        logger.info(f"LKML scheduler started [run_id={self.run_id}]")

    async def stop(self) -> None:
        """停止定时任务"""
        if not self.is_running:
            logger.warning("Scheduler is not running")
            return

        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("LKML scheduler stopped")

    async def run_once(self) -> MonitoringResult:
        """手动运行一次监控任务"""
        logger.info("Running LKML monitoring once")
        monitoring_result = await self.monitor.run_monitoring()
        await self.send_feed_updates(monitoring_result)
        return monitoring_result


# 调度器单例管理器（避免使用全局变量）
class _SchedulerManager:
    """调度器管理器（单例模式）"""

    _instance: Optional["_SchedulerManager"] = None
    _scheduler: Optional[LKMLScheduler] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_scheduler(self, scheduler: LKMLScheduler) -> None:
        """设置调度器实例"""
        self._scheduler = scheduler

    def get_scheduler(self) -> LKMLScheduler:
        """获取调度器实例"""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized. Call set_scheduler() first.")
        return self._scheduler


_scheduler_manager = _SchedulerManager()


def set_scheduler(scheduler: LKMLScheduler) -> None:
    """设置调度器实例

    Args:
        scheduler: 调度器实例
    """
    _scheduler_manager.set_scheduler(scheduler)


def get_scheduler() -> LKMLScheduler:
    """获取调度器实例

    Returns:
        调度器实例

    Raises:
        RuntimeError: 如果调度器未初始化
    """
    return _scheduler_manager.get_scheduler()
