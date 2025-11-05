"""Feed相关功能模块"""

# pylint: disable=undefined-all-variable
# 注意：__all__ 中的名称已从 .types 导入，静态分析可能无法识别

from .types import (
    FeedEntry,
    FeedProcessResult,
    SubsystemUpdate,
    SubsystemMonitoringResult,
    MonitoringResult,
)

# Feed 类型名称列表（用于 __all__，避免与 lkml.__init__.py 中的重复）
_FEED_TYPE_NAMES = [
    "FeedEntry",
    "FeedProcessResult",
    "SubsystemUpdate",
    "SubsystemMonitoringResult",
    "MonitoringResult",
]

__all__ = _FEED_TYPE_NAMES  # pylint: disable=undefined-all-variable
