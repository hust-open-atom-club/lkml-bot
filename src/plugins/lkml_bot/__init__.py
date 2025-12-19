"""LKML Bot NoneBot plugin

说明：本插件负责装配 LKML 领域层依赖（配置、数据库、监控器、调度器）并注册命令。
命令均基于 @ 提及(to_me) 触发：
  - `.commands.help`
  - `.commands.subscribe`
  - `.commands.unsubscribe`
  - `.commands.start_monitor`
  - `.commands.stop_monitor`
  - `.commands.run_monitor`
"""

import sys
import logging
from pathlib import Path

from nonebot import get_driver
from nonebot.log import logger, LoguruHandler

# 1) 环境与路径
# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # dotenv 未安装，跳过
    pass

# 将 src 目录添加到 Python 路径，以便导入 lkml
src_path = Path(__file__).parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# 2) 基础设施装配（配置、数据库）
# 注意：这些导入在 sys.path 修改之后，是必要的，因此使用 pylint 注释禁用相关警告
# 第一方导入（必须在本地导入之前）
# pylint: disable=wrong-import-position
from lkml.config import set_config  # noqa: E402
from lkml.db import set_database, LKMLDatabase, Base  # noqa: E402
from lkml.feed.feed import FeedProcessor  # noqa: E402
from lkml.feed.feed_monitor import LKMLFeedMonitor  # noqa: E402
from lkml.feed.vger_subsystems import (
    get_vger_subsystems,
    start_daily_update_task,
    update_vger_subsystems_cache,
)  # noqa: E402
from lkml.scheduler import LKMLScheduler  # noqa: E402

# 本地导入
from .config import get_config  # noqa: E402
from .message_sender import get_message_sender  # noqa: E402
from .shared import set_database as set_plugin_database  # noqa: E402

# pylint: enable=wrong-import-position

# 初始化数据库
plugin_config = get_config()
database = LKMLDatabase(plugin_config.database_url, Base)

# 设置基础设施（PluginConfig 已经实现了 Config 接口）
set_config(plugin_config)
set_database(database)
set_plugin_database(database)  # 也在插件层设置数据库

# 3) 注册子系统来源（数据来源由实现决定）
try:
    plugin_config.set_vger_subsystems_getter(get_vger_subsystems)
except (AttributeError, ValueError) as e:
    logger.warning(f"Failed to register vger subsystems getter: {e}")

# 4) 创建监控与调度实例（使用适配器的消息发送器）
message_sender = get_message_sender(database=database)

# 使用渲染器与客户端（统一的多平台发送服务）
# pylint: disable=wrong-import-position
from .renders.patch_card.renderer import PatchCardRenderer
from .renders.thread.renderer import ThreadOverviewRenderer
from .renders.patch_card import FeishuPatchCardRenderer
from .renders.thread.feishu_render import FeishuThreadOverviewRenderer
from .client.discord_client import DiscordClient
from .client.feishu_client import FeishuClient
from .multi_platform_sender import MultiPlatformPatchCardSender

patch_card_renderer = PatchCardRenderer(config=plugin_config)
feishu_patch_card_renderer = FeishuPatchCardRenderer(config=plugin_config)
thread_overview_renderer = ThreadOverviewRenderer(config=plugin_config)
feishu_thread_overview_renderer = FeishuThreadOverviewRenderer(config=plugin_config)

# 平台客户端实例（每个平台一套）
discord_client = DiscordClient(config=plugin_config)
feishu_client = FeishuClient(config=plugin_config)

# 多平台 PatchCard 发送服务（Discord + Feishu）
from .shared import set_patch_card_sender
from .multi_platform_thread_sender import MultiPlatformThreadSender

patch_card_sender = MultiPlatformPatchCardSender(
    discord_client=discord_client,
    discord_renderer=patch_card_renderer,
    feishu_client=feishu_client,
    feishu_renderer=feishu_patch_card_renderer,
)

# 多平台 Thread 发送服务（Discord + Feishu）
thread_sender = MultiPlatformThreadSender(
    discord_client=discord_client,
    discord_renderer=thread_overview_renderer,
    feishu_client=feishu_client,
    feishu_renderer=feishu_thread_overview_renderer,
)

# 注册到 shared 模块，供命令模块使用
from .shared import set_thread_sender

set_patch_card_sender(patch_card_sender)
set_thread_sender(thread_sender)


async def send_update_callback(subsystem: str, update_data):
    """消息发送回调"""
    await message_sender.send_subsystem_update(subsystem, update_data)


# 创建 FeedMessageService（使用统一的多平台发送服务）
# pylint: disable=wrong-import-position,wrong-import-order
from lkml.service.feed_message_service import FeedMessageService

feed_message_service = FeedMessageService(
    patch_card_sender=patch_card_sender,
    thread_sender=thread_sender,
)

processor = FeedProcessor(
    database=database,
    thread_manager=None,  # 不再需要 ThreadManager
    feed_message_service=feed_message_service,
)
monitor = LKMLFeedMonitor(config=plugin_config, processor=processor, database=database)
scheduler = LKMLScheduler(
    message_sender=send_update_callback,
)
scheduler.monitor = monitor

# 将调度器注册到 lkml 层
# pylint: disable=wrong-import-order,wrong-import-position,import-outside-toplevel
from lkml.scheduler import (
    set_scheduler,
)

set_scheduler(scheduler)

# 5) 导入命令模块，确保处理器在导入时完成注册
# pylint: disable=wrong-import-position
from .commands import help as help_command  # noqa: F401, E402
from .commands import subscribe  # noqa: F401, E402
from .commands import unsubscribe  # noqa: F401, E402
from .commands import start_monitor  # noqa: F401, E402
from .commands import stop_monitor  # noqa: F401, E402
from .commands import run_monitor  # noqa: F401, E402
from .commands import watch  # noqa: F401, E402
from .commands import filter as filter_command  # noqa: F401, E402

# 重建卡片功能已移除
# from .commands import rebuild_thread  # noqa: F401, E402
# from .commands import rebuild_series  # noqa: F401, E402

# 导入交互端点（注册 FastAPI 路由）- 保留以备将来使用
# interaction_endpoint 已删除（改用命令订阅模式）

# pylint: enable=wrong-import-position

__all__ = [
    "help_command",
    "subscribe",
    "unsubscribe",
    "start_monitor",
    "stop_monitor",
    "run_monitor",
    "watch",
    "filter_command",
]


# 6) 配置标准 Python logging 转发到 NoneBot 的 loguru
# 在插件加载时配置，确保 NoneBot 已初始化
def _setup_logging_bridge():
    """配置标准 Python logging 转发到 loguru"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # 避免重复添加 handler
    if not any(isinstance(h, LoguruHandler) for h in root_logger.handlers):
        root_logger.addHandler(LoguruHandler())
        logger.info("✓ Configured LoguruHandler for standard Python logging")

        # 测试日志桥接是否工作
        test_logger = logging.getLogger("lkml.service.thread_service")
        test_logger.info("✓ Logging bridge test: standard logging -> loguru is working")
    else:
        logger.debug("LoguruHandler already configured")


# 立即配置日志桥接
_setup_logging_bridge()

# 7) 机器人生命周期：启动/停止钩子
driver = get_driver()


@driver.on_startup
async def auto_start_monitoring():
    """在 bot 启动时自动启动监控任务并初始化 vger 子系统缓存"""
    try:
        # 初始化 vger 子系统缓存
        logger.info("Initializing vger subsystems cache on bot startup")
        cache_updated = await update_vger_subsystems_cache()
        if cache_updated:
            logger.info("Vger subsystems cache initialized successfully")
        else:
            logger.warning(
                "Failed to initialize vger subsystems cache, will retry later"
            )

        # 启动每日自动更新任务
        start_daily_update_task()
        logger.info("Daily vger subsystems cache update task scheduled")
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to initialize vger subsystems cache: {e}", exc_info=True)

    try:
        # pylint: disable=import-outside-toplevel  # noqa: E402
        from lkml.scheduler import get_scheduler

        current_scheduler = get_scheduler()
        if not current_scheduler.is_running:
            logger.info("Auto-starting LKML monitoring scheduler on bot startup")
            await current_scheduler.start()
        else:
            logger.info("LKML monitoring scheduler is already running")
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to auto-start monitoring scheduler: {e}", exc_info=True)


@driver.on_shutdown
async def auto_stop_monitoring():
    """在 bot 关闭时停止监控任务"""
    try:
        # pylint: disable=import-outside-toplevel
        from lkml.scheduler import get_scheduler

        current_scheduler = get_scheduler()
        if current_scheduler.is_running:
            logger.info("Stopping LKML monitoring scheduler on bot shutdown")
            await current_scheduler.stop()
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to stop monitoring scheduler: {e}", exc_info=True)
