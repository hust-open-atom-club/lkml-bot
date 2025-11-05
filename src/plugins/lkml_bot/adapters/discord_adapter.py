"""Discord 消息适配器

负责将邮件列表更新消息发送到 Discord 平台。
"""

try:
    import httpx
except ImportError:
    httpx = None

from nonebot.log import logger

from lkml.feed import SubsystemUpdate
from ..config import get_config
from ..renders import DiscordRenderer
from .message_adapter import MessageAdapter


class DiscordAdapter(MessageAdapter):  # pylint: disable=too-few-public-methods
    """Discord 消息适配器

    实现 MessageAdapter 接口，通过 Discord Webhook 发送消息。
    核心职责是实现消息发送，方法数量是合理的。
    """

    def __init__(self):
        """初始化 Discord 适配器"""
        self.config = get_config()
        self.renderer = DiscordRenderer()

    async def send_subsystem_update(
        self, subsystem: str, update_data: SubsystemUpdate
    ) -> None:
        """通过 Discord Webhook 发送消息

        Args:
            subsystem: 子系统名称
            update_data: 更新数据
        """
        try:
            webhook_url = self.config.discord_webhook_url
            if not webhook_url:
                logger.debug(
                    "Discord webhook URL not configured, skipping Discord send"
                )
                return

            if not httpx:
                logger.error(
                    "httpx is not installed, cannot send Discord webhook messages"
                )
                return

            # 如果没有更新，直接返回
            if update_data.new_count == 0 and update_data.reply_count == 0:
                logger.info(f"No updates for {subsystem}")
                return

            # 使用渲染器构建 Embed 数据
            embed = self.renderer.render(subsystem, update_data)

            # 准备发送的数据
            data = {"embeds": [embed]}

            # 发送 webhook 请求
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=data)
                if response.status_code in {200, 204}:
                    logger.info(
                        f"Successfully sent message via Discord webhook for {subsystem}"
                    )
                else:
                    logger.error(
                        f"Failed to send Discord webhook message: "
                        f"status {response.status_code}, {response.text}"
                    )
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.error(f"Failed to send message to Discord: {e}", exc_info=True)
            # 不抛出异常，避免影响主流程
