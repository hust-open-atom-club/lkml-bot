"""服务模块

包含所有业务逻辑服务：
- operation_log_service: 操作日志辅助模块
- subsystem_service: 子系统订阅管理服务
- monitoring_service: 监控控制服务
- query_service: 数据查询服务
- thread_service: Thread 管理服务
- patch_card_service: PATCH 卡片管理服务
- feed_message_service: Feed 消息处理服务
- service: 统一服务门面
"""

from .monitoring_service import MonitoringService, monitoring_service
from .operation_log_service import log_operation
from .patch_card_service import PatchCardService
from .types import (
    PatchCard,
    FeedMessage,
    PatchThread,
    ThreadOverviewData,
)
from .query_service import QueryService, query_service
from .service import LKMLService, lkml_service
from .subsystem_service import SubsystemService, subsystem_service

from .thread_service import (
    ThreadService,
    parse_reply_time,
)
from .feed_message_service import FeedMessageService


# 延迟导入工厂函数以避免循环导入
# 这些函数在 database 模块中定义，但通过 service 模块导出以保持向后兼容
def _lazy_import_factory_functions():
    """延迟导入工厂函数以避免循环导入"""
    from ..db.database import (
        get_patch_card_service as _db_get_patch_card_service,
        get_thread_service as _db_get_thread_service,
    )

    return _db_get_patch_card_service, _db_get_thread_service


# 在模块级别提供这些函数，但使用延迟导入
# pylint: disable=redefined-outer-name
_patch_card_service_factory, _thread_service_factory = _lazy_import_factory_functions()
get_patch_card_service = _patch_card_service_factory
get_thread_service = _thread_service_factory

__all__ = [
    "LKMLService",
    "lkml_service",
    "SubsystemService",
    "subsystem_service",
    "MonitoringService",
    "monitoring_service",
    "QueryService",
    "query_service",
    "ThreadService",
    "get_thread_service",
    "PatchCardService",
    "get_patch_card_service",
    "FeedMessageService",
    "log_operation",
    "PatchCard",
    "FeedMessage",
    "PatchThread",
    "ThreadOverviewData",
    # 回复处理辅助函数
    "parse_reply_time",
]
