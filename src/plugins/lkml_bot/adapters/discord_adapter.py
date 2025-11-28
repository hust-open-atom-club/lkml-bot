"""Discord 消息适配器

负责将邮件列表更新消息发送到 Discord 平台。
"""

try:
    import httpx  # pylint: disable=unused-import
except ImportError:
    httpx = None  # pylint: disable=unused-variable

from nonebot.log import logger

from lkml.feed import SubsystemUpdate

from ..config import get_config
from ..renders import DiscordRenderer
from .message_adapter import MessageAdapter


class DiscordAdapter(MessageAdapter):
    """Discord 消息适配器

    实现 MessageAdapter 接口，通过 Discord 发送消息。
    支持 Thread 模式：PATCH 发送订阅卡片，REPLY 发送到对应 Thread。
    """

    def __init__(self, database=None):
        """初始化 Discord 适配器

        Args:
            database: 数据库实例
        """
        self.config = get_config()
        self.renderer = DiscordRenderer()
        self.database = database

    async def send_subsystem_update(
        self, subsystem: str, update_data: SubsystemUpdate
    ) -> None:
        """通过 Discord 发送消息

        注意：PATCH 和 REPLY 消息已由 FeedMessageService 处理

        Args:
            subsystem: 子系统名称
            update_data: 更新数据
        """
        try:
            # 如果没有更新，直接返回
            if update_data.new_count == 0 and update_data.reply_count == 0:
                logger.info(f"No updates for {subsystem}")
                return

            # 记录更新信息
            for entry in update_data.entries:
                if entry.content.is_patch:
                    logger.debug(
                        f"PATCH message saved to database, card built by FeedMessageService: {entry.subject}"
                    )
                elif entry.content.is_reply:
                    logger.debug(
                        f"REPLY message processed by FeedMessageService: {entry.subject}"
                    )
                else:
                    logger.debug(f"Other message: {entry.subject}")

        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.error(f"Failed to send message to Discord: {e}", exc_info=True)
            # 不抛出异常，避免影响主流程
