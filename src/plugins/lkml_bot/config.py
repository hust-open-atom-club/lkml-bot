"""插件配置管理模块（包含机器人特定配置）"""

import os
from typing import Optional

from lkml.config import LKMLConfig as BaseLKMLConfig


class PluginConfig(BaseLKMLConfig):
    """插件层配置（扩展基础配置，添加机器人特定配置）"""

    # Discord 配置（机器人特定）
    discord_webhook_url: str = ""

    @classmethod
    def from_env(cls, database_url=None) -> "PluginConfig":
        """从环境变量创建配置

        注意：os 在顶层导入，因为需要读取环境变量。

        Args:
            database_url: 数据库URL（可选）
        """
        # 先创建基础配置（已经处理了所有基础配置的环境变量和默认值）
        base_config = BaseLKMLConfig.from_env()

        # 获取 Discord webhook URL（从环境变量读取，可在 .env 文件中配置）
        discord_webhook_url = os.getenv("LKML_DISCORD_WEBHOOK_URL", "")

        return cls(
            database_url=base_config.database_url,
            manual_subsystems=base_config.manual_subsystems,
            max_news_count=base_config.max_news_count,
            monitoring_interval=base_config.monitoring_interval,
            last_update_dt_override_iso=base_config.last_update_dt_override_iso,
            discord_webhook_url=discord_webhook_url,
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
