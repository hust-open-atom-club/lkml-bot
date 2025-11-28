"""消息发送器（组合多个适配器）

负责将邮件列表更新消息发送到各个平台，通过不同的适配器实现。
"""

from nonebot.log import logger

from lkml.feed import SubsystemUpdate
from .adapters.discord_adapter import DiscordAdapter
from .renders import DiscordRenderer


class MessageSender:  # pylint: disable=too-few-public-methods
    """消息发送器，负责将更新发送到各个平台

    组合多个消息适配器（如 DiscordAdapter），统一管理消息发送逻辑。
    核心职责是协调多个适配器发送消息，方法数量是合理的。
    """

    def __init__(self, database=None):
        """初始化消息发送器

        Args:
            database: 数据库实例（可选）
        """
        self.renderer = DiscordRenderer()
        self.discord_adapter = DiscordAdapter(database=database)
        self.database = database
        # 可以在这里添加更多适配器

    async def send_subsystem_update(
        self, subsystem: str, update_data: SubsystemUpdate
    ) -> None:
        """发送子系统更新

        Args:
            subsystem: 子系统名称
            update_data: 更新数据
        """
        try:
            logger.info(
                f"Sending update for {subsystem}: "
                f"{update_data.new_count} new messages, "
                f"{update_data.reply_count} replies"
            )

            # 如果没有更新，直接返回
            if update_data.new_count == 0 and update_data.reply_count == 0:
                logger.info(f"No updates for {subsystem}")
                return

            # 构建消息内容（用于日志）
            message_text = self.renderer.render_text(subsystem, update_data)

            # 发送到各个平台
            await self.discord_adapter.send_subsystem_update(subsystem, update_data)

            # 记录日志
            logger.info(f"Message for {subsystem}:\n{message_text}")

            # 如果有订阅的用户，需要通知他们
            if update_data.subscribed_users:
                logger.info(
                    f"Subscribed users for {subsystem}: {update_data.subscribed_users}"
                )
                # TODO: 向每个用户发送消息

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to send subsystem update for {subsystem}: {e}", exc_info=True
            )
            raise


# 全局消息发送器实例（延迟初始化，需要在有 database 时重新创建）
message_sender = None


def get_message_sender(database=None) -> MessageSender:
    """获取消息发送器实例

    Args:
        database: 数据库实例（可选）

    Returns:
        消息发送器实例
    """
    global message_sender  # pylint: disable=global-statement
    if message_sender is None or (database and message_sender.database is None):
        message_sender = MessageSender(database=database)
    return message_sender
