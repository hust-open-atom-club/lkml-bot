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
    message_id: Optional[str] = None  # Message-ID 头部
    in_reply_to: Optional[str] = None  # In-Reply-To 头部


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


@dataclass
class PatchInfo:
    """PATCH 信息"""

    is_patch: bool = False
    version: Optional[str] = None  # 版本号，如 "v5"
    index: Optional[int] = None  # 序号，如 1
    total: Optional[int] = None  # 总数，如 4
    is_cover_letter: bool = False  # 是否是 0/n 封面信


@dataclass
class MessageClassification:
    """消息分类结果"""

    is_patch: bool = False
    is_reply: bool = False
    is_series_patch: bool = False
    patch_info: Optional[PatchInfo] = None
    series_message_id: Optional[str] = None
    has_error: bool = False
    error_message: Optional[str] = None
