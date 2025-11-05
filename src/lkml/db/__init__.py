"""数据库模块

包含数据库接口、实现和数据模型：
- database: 数据库接口和实现
- models: SQLAlchemy 数据模型
- repo: 仓储层实现
"""

from .database import Database, LKMLDatabase, get_database, set_database
from .models import Base, EmailMessage, OperationLog, Subsystem
from .repo import (
    EMAIL_MESSAGE_REPO,
    EmailMessageData,
    EmailMessageRepository,
    SUBSYSTEM_REPO,
    SubsystemRepository,
    _REPO_EXPORT_NAMES,
)

__all__ = [
    "Database",
    "LKMLDatabase",
    "get_database",
    "set_database",
    "Base",
    "Subsystem",
    "EmailMessage",
    "OperationLog",
    *_REPO_EXPORT_NAMES,
]
