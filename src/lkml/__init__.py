"""LKML 业务逻辑包（独立于机器人框架）"""

# pylint: disable=undefined-all-variable
# 注意：__all__ 中的某些名称通过 __getattr__ 动态提供，在静态分析时未定义是正常的

from .db import Base, Subsystem, EmailMessage, OperationLog


# 从 feed 模块导入类型名称列表（避免重复定义）
from .feed import _FEED_TYPE_NAMES


# 使用 __getattr__ 实现延迟导入（避免循环导入）
# 注意：所有导入都在函数内部，这是延迟导入的必要实现方式
def __getattr__(name: str):
    """延迟导入相关的内容以避免循环导入

    此函数通过字典映射减少返回语句数量，同时保持代码清晰。
    """
    # 服务类映射
    service_map = {
        "LKMLService": "service.LKMLService",
        "SubsystemService": "service.SubsystemService",
        "MonitoringService": "service.MonitoringService",
        "QueryService": "service.QueryService",
    }

    if name in service_map:
        module_path = service_map[name]
        module = __import__(f"lkml.{module_path}", fromlist=[name])
        return getattr(module, name)

    # Feed 监控器和调度器
    if name == "LKMLFeedMonitor":
        # pylint: disable=import-outside-toplevel  # noqa: E402
        from .feed.feed_monitor import (
            LKMLFeedMonitor,
        )

        return LKMLFeedMonitor
    if name == "LKMLScheduler":
        # pylint: disable=import-outside-toplevel  # noqa: E402
        from .scheduler import (
            LKMLScheduler,
        )

        return LKMLScheduler

    # Feed types - 从 feed 模块统一导入，避免重复
    if name in _FEED_TYPE_NAMES:
        from .feed import (  # pylint: disable=import-outside-toplevel  # noqa: E402
            FeedEntry,
            FeedProcessResult,
            SubsystemUpdate,
            SubsystemMonitoringResult,
            MonitoringResult,
        )

        type_map = {
            "FeedEntry": FeedEntry,
            "FeedProcessResult": FeedProcessResult,
            "SubsystemUpdate": SubsystemUpdate,
            "SubsystemMonitoringResult": SubsystemMonitoringResult,
            "MonitoringResult": MonitoringResult,
        }
        return type_map[name]

    if name == "get_vger_subsystems":
        # pylint: disable=import-outside-toplevel  # noqa: E402
        from .feed.vger_subsystems import (
            get_vger_subsystems,
        )

        return get_vger_subsystems

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# 这些名称通过 __getattr__ 动态提供，所以需要在运行时检查
__all__ = [  # pylint: disable=undefined-all-variable
    "Base",
    "Subsystem",
    "EmailMessage",
    "OperationLog",
    "LKMLService",
    "SubsystemService",
    "MonitoringService",
    "QueryService",
    "LKMLFeedMonitor",
    "LKMLScheduler",
    *_FEED_TYPE_NAMES,
    "get_vger_subsystems",
]
