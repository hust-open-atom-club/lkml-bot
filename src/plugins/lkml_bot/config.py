"""插件配置管理模块（包含机器人特定配置）"""

import os
from typing import Optional

from lkml.config import LKMLConfig as BaseLKMLConfig


class PluginConfig(BaseLKMLConfig):
    """插件层配置（扩展基础配置，添加机器人特定配置）"""

    # Discord 配置（机器人特定）
    discord_webhook_url: str = ""
    discord_bot_token: str = ""  # Discord Bot Token（用于 Thread 操作）
    platform_channel_id: str = ""  # Discord 频道 ID（用于发送消息和创建 Thread）
    bot_mention_name: str = "@lkml-bot"  # Bot 在消息中的提及名称

    # Thread 相关配置
    thread_subscription_timeout_hours: int = 24  # 订阅卡片过期时间（小时）
    thread_pool_max_size: int = 50  # Thread 池最大大小
    card_builder_interval_minutes: int = 5  # 卡片构建间隔（分钟）

    @classmethod
    def from_env(cls, database_url=None) -> "PluginConfig":
        """从环境变量创建配置

        注意：os 在顶层导入，因为需要读取环境变量。

        Args:
            database_url: 数据库URL（可选）
        """
        # 先创建基础配置（已经处理了所有基础配置的环境变量和默认值）
        base_config = BaseLKMLConfig.from_env()

        # 获取 Discord 相关配置
        discord_webhook_url = os.getenv("LKML_DISCORD_WEBHOOK_URL", "")
        discord_bot_token = os.getenv("LKML_DISCORD_BOT_TOKEN", "")
        platform_channel_id = os.getenv("LKML_DISCORD_CHANNEL_ID", "")
        bot_mention_name = os.getenv("LKML_BOT_MENTION_NAME", "@lkml-bot")

        # Thread 相关配置
        thread_subscription_timeout_hours = int(
            os.getenv("LKML_THREAD_SUBSCRIPTION_TIMEOUT_HOURS", "24")
        )
        thread_pool_max_size = int(os.getenv("LKML_THREAD_POOL_MAX_SIZE", "50"))
        card_builder_interval_minutes = int(
            os.getenv("LKML_CARD_BUILDER_INTERVAL_MINUTES", "5")
        )

        return cls(
            database_url=base_config.database_url,
            manual_subsystems=base_config.manual_subsystems,
            max_news_count=base_config.max_news_count,
            monitoring_interval=base_config.monitoring_interval,
            last_update_dt_override_iso=base_config.last_update_dt_override_iso,
            discord_webhook_url=discord_webhook_url,
            discord_bot_token=discord_bot_token,
            platform_channel_id=platform_channel_id,
            bot_mention_name=bot_mention_name,
            thread_subscription_timeout_hours=thread_subscription_timeout_hours,
            thread_pool_max_size=thread_pool_max_size,
            card_builder_interval_minutes=card_builder_interval_minutes,
        )


# 配置单例实例（使用模块级变量存储）
# 注意：使用 global 语句是单例模式的常见实现方式
_config_instance: Optional[PluginConfig] = None


def get_config() -> PluginConfig:
    """获取配置实例（单例模式）

    注意：使用 global 语句是单例模式的常见实现方式。
    """
    global _config_instance  # pylint: disable=global-statement  # noqa: PLW0603
    if _config_instance is None:
        _config_instance = PluginConfig.from_env()
    return _config_instance
