"""Feed类型定义

定义了 Feed 处理过程中使用的数据结构，包括邮件条目、处理结果、监控结果等。
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class FeedEntryMetadata:
    """Feed 条目的元数据信息"""

    sender: Optional[str] = None
    sender_email: Optional[str] = None
    content: Optional[str] = None
    link: Optional[str] = None
    message_id: Optional[str] = None


@dataclass
class FeedEntryContent:
    """Feed 条目的内容信息"""

    summary: Optional[str] = None
    received_at: Optional[str] = None
    is_reply: bool = False
    is_patch: bool = False


@dataclass
class FeedEntry:
    """Feed 条目

    表示单个邮件列表中的一封邮件信息。
    """

    id: Optional[int] = None
    subject: str = ""
    author: str = ""
    email: Optional[str] = None
    url: Optional[str] = None
    content: FeedEntryContent = field(default_factory=FeedEntryContent)
    metadata: FeedEntryMetadata = field(default_factory=FeedEntryMetadata)


@dataclass
class FeedProcessResult:
    """Feed 处理结果

    表示处理单个子系统 feed 的结果。
    """

    subsystem: str
    new_count: int = 0
    reply_count: int = 0
    entries: List[FeedEntry] = field(default_factory=list)


@dataclass
class SubsystemUpdate:
    """邮件列表/子系统更新信息

    表示单个子系统的更新信息，用于发送通知。
    """

    new_count: int = 0
    reply_count: int = 0
    entries: List[FeedEntry] = field(default_factory=list)
    subscribed_users: List[str] = field(default_factory=list)
    title: str = ""


@dataclass
class SubsystemMonitoringResult:
    """子系统监控结果

    表示单个子系统的监控结果。
    """

    subsystem: str
    new_count: int = 0
    reply_count: int = 0
    entries: List[FeedEntry] = field(default_factory=list)
    subscribed_users: List[str] = field(default_factory=list)
    title: str = ""


@dataclass
class MonitoringStatistics:
    """监控统计信息"""

    total_subsystems: int = 0
    processed_subsystems: int = 0
    total_new_count: int = 0
    total_reply_count: int = 0
    error_count: int = 0


@dataclass
class MonitoringResult:
    """监控结果

    表示一次完整的监控任务的所有结果。
    """

    statistics: MonitoringStatistics = field(default_factory=MonitoringStatistics)
    results: List[SubsystemMonitoringResult] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    errors: Optional[List[str]] = None
