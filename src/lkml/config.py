"""配置模块（配置接口和实现）"""

from typing import List, Optional, Protocol, Callable
from nonebot.log import logger
from pydantic import BaseModel

__all__ = ["Config", "LKMLConfig", "set_config", "get_config"]


class Config(Protocol):
    """配置接口（使用 Protocol 避免与 Pydantic 字段冲突）

    注意：Protocol 中的 `...` 是必需的占位符，表示抽象方法。
    """

    @property
    def database_url(self) -> str:
        """数据库连接URL"""
        ...  # pylint: disable=unnecessary-ellipsis  # Protocol 必需，表示抽象属性

    def get_supported_subsystems(self) -> List[str]:
        """获取支持的子系统列表（动态合并 vger 缓存和手动配置）"""
        ...  # pylint: disable=unnecessary-ellipsis  # Protocol 必需，表示抽象方法

    @property
    def max_news_count(self) -> int:
        """最大新闻数量"""
        ...  # pylint: disable=unnecessary-ellipsis  # Protocol 必需，表示抽象属性

    @property
    def monitoring_interval(self) -> int:
        """监控任务执行周期（秒）"""
        ...  # pylint: disable=unnecessary-ellipsis  # Protocol 必需，表示抽象属性


# 配置单例管理器（避免使用全局变量）
class _ConfigManager:
    """配置管理器（单例模式）"""

    _instance: Optional["_ConfigManager"] = None
    _config: Optional[Config] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_config(self, config: Config) -> None:
        """设置配置实例"""
        self._config = config

    def get_config(self) -> Config:
        """获取配置实例"""
        if self._config is None:
            raise RuntimeError("Config not initialized. Call set_config() first.")
        return self._config


_config_manager = _ConfigManager()


def set_config(config: Config) -> None:
    """设置配置实例"""
    _config_manager.set_config(config)


def get_config() -> Config:
    """获取配置实例"""
    config = _config_manager.get_config()
    # 验证配置对象的完整性
    # 注意：使用 getattr 安全获取属性，避免属性不存在时的错误
    database_url = getattr(config, "database_url", None)
    max_news_count = getattr(config, "max_news_count", None)
    monitoring_interval = getattr(config, "monitoring_interval", None)

    if database_url is None:
        raise RuntimeError(
            "Config.database_url is None. Configuration may not be properly initialized."
        )
    if max_news_count is None:
        raise RuntimeError(
            "Config.max_news_count is None. Configuration may not be properly initialized."
        )
    if monitoring_interval is None:
        raise RuntimeError(
            "Config.monitoring_interval is None. Configuration may not be properly initialized."
        )
    return config


class LKMLConfig(BaseModel):
    """LKML 配置实现（与机器人框架无关，实现 Config Protocol）

    支持的子系统由两部分组成：
    1. 从 vger 服务器缓存自动获取的内核子系统（存储在缓存中）
    2. 手动配置的额外子系统（通过 LKML_MANUAL_SUBSYSTEMS 环境变量）
    """

    database_url: str = "sqlite+aiosqlite:///./lkml_bot.db"
    manual_subsystems: List[str] = []  # 手动配置的额外子系统
    max_news_count: int = 20
    monitoring_interval: int = 300  # 监控任务执行周期（秒），默认 5 分钟
    # Debug/开发辅助：ISO8601 字符串覆盖 last_update_dt（如 2025-11-03T12:00:00Z）
    last_update_dt_override_iso: Optional[str] = None
    _vger_subsystems_getter: Optional[Callable[[], List[str]]] = (
        None  # 用于获取 vger 缓存中的子系统
    )

    class Config:  # pylint: disable=too-few-public-methods
        """Pydantic 配置类

        这是 Pydantic 的内部配置类，只包含必要的配置属性。
        Pydantic 要求使用此类来配置模型行为，公共方法数量是合理的。
        """

        arbitrary_types_allowed = True

    def set_vger_subsystems_getter(self, getter: Callable[[], List[str]]) -> None:
        """设置用于获取 vger 子系统缓存的函数

        Bot 的服务器缓存会存储所有从 vger 获取的内核子系统信息（键值对格式）。
        通过此方法注册获取函数，函数应返回从服务器缓存中读取的子系统名称列表。

        Args:
            getter: 返回 vger 子系统列表的函数。函数应该从服务器缓存读取数据并返回子系统名称列表
                   例如: ["lkml", "netdev", "dri-devel", ...]

        示例:
            def get_vger_subsystems_from_cache() -> List[str]:
                # 从服务器缓存获取子系统列表
                # 实现从缓存读取逻辑
                return ["lkml", "netdev", "dri-devel"]

            config.set_vger_subsystems_getter(get_vger_subsystems_from_cache)
        """
        self._vger_subsystems_getter = getter

    def get_supported_subsystems(self) -> List[str]:
        """获取支持的子系统列表（动态合并 vger 缓存和手动配置）

        Returns:
            合并后的子系统列表（去重并排序）
        """
        # 从 vger 缓存获取内核子系统
        vger_subsystems = []
        if self._vger_subsystems_getter:
            try:
                result = self._vger_subsystems_getter()
                # 确保返回的是列表，如果返回 None 则使用空列表
                if result is not None:
                    vger_subsystems = result if isinstance(result, list) else []
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning(f"Failed to get vger subsystems: {e}")

        # 确保 manual_subsystems 不为 None
        manual_subsystems = (
            self.manual_subsystems if self.manual_subsystems is not None else []
        )

        # 合并并去重
        all_subsystems = list(set(vger_subsystems + manual_subsystems))
        return sorted(all_subsystems)

    @staticmethod
    def _parse_manual_subsystems() -> List[str]:
        """从环境变量解析手动配置的子系统"""
        import os  # pylint: disable=import-outside-toplevel

        manual_subsystems_env = os.getenv("LKML_MANUAL_SUBSYSTEMS")
        if manual_subsystems_env and manual_subsystems_env.strip():
            return [s.strip() for s in manual_subsystems_env.split(",") if s.strip()]
        return []

    @staticmethod
    def _get_database_url(database_url: Optional[str]) -> Optional[str]:
        """获取数据库URL（优先参数，其次环境变量）"""
        import os  # pylint: disable=import-outside-toplevel

        if database_url and database_url.strip():
            return database_url
        database_url_env = os.getenv("LKML_DATABASE_URL")
        if database_url_env and database_url_env.strip():
            return database_url_env
        return None

    @staticmethod
    def _get_int_env(env_name: str, default: Optional[int] = None) -> Optional[int]:
        """从环境变量获取整数值"""
        import os  # pylint: disable=import-outside-toplevel

        env_value = os.getenv(env_name)
        if env_value and env_value.strip():
            try:
                return int(env_value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _get_str_env(env_name: str, default: Optional[str] = None) -> Optional[str]:
        """从环境变量获取字符串值"""
        import os  # pylint: disable=import-outside-toplevel

        env_value = os.getenv(env_name)
        if env_value and env_value.strip():
            return env_value.strip()
        return default

    @classmethod
    def from_env(cls, database_url: Optional[str] = None) -> "LKMLConfig":
        """从环境变量创建配置

        注意：如果没有提供环境变量，将使用类字段的默认值。
        这样可以通过设置环境变量来测试不同的配置值。
        """
        # 解析各配置项
        manual_subsystems = cls._parse_manual_subsystems()
        final_database_url = cls._get_database_url(database_url)
        max_news_count = cls._get_int_env("LKML_MAX_NEWS_COUNT")
        monitoring_interval_raw = cls._get_int_env("LKML_MONITORING_INTERVAL")
        monitoring_interval = (
            max(monitoring_interval_raw, 60) if monitoring_interval_raw else None
        )
        last_update_dt_override_iso = cls._get_str_env("LKML_LAST_UPDATE_AT")

        # 构建配置字典
        config_dict = {"manual_subsystems": manual_subsystems}
        if final_database_url:
            config_dict["database_url"] = final_database_url
        if max_news_count is not None:
            config_dict["max_news_count"] = max_news_count
        if monitoring_interval is not None:
            config_dict["monitoring_interval"] = monitoring_interval
        if last_update_dt_override_iso is not None:
            config_dict["last_update_dt_override_iso"] = last_update_dt_override_iso

        return cls(**config_dict)
