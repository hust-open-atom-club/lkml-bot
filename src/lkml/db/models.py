"""LKML领域模型"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Subsystem(Base):  # pylint: disable=too-few-public-methods
    """子系统模型

    存储邮件列表子系统的信息，用于管理订阅状态。
    这是 SQLAlchemy ORM 模型，主要作为数据容器，不需要太多公共方法。
    """

    __tablename__ = "subsystems"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    subscribed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class FeedMessageModel(Base):  # pylint: disable=too-few-public-methods
    """Feed 消息模型

    存储邮件消息的分类信息和 PATCH 信息，用于快速查询和过滤。
    """

    __tablename__ = "feed_messages"

    id = Column(Integer, primary_key=True, index=True)
    subsystem_name = Column(String(100), nullable=False, index=True)
    message_id = Column(
        String(500), unique=True, nullable=True, index=True
    )  # 消息唯一标识
    message_id_header = Column(
        String(500), nullable=False, unique=True, index=True
    )  # Message-ID Header，用于快速查找
    in_reply_to_header = Column(
        String(500), nullable=True, index=True
    )  # In-Reply-To 头部

    # 邮件基本信息（从 feed 中提取）
    subject = Column(String(500), nullable=False, index=True)  # 邮件主题
    author = Column(String(200), nullable=False)  # 作者
    author_email = Column(String(200), nullable=False)  # 作者邮箱
    content = Column(Text, nullable=True)  # 邮件内容
    url = Column(String(1000), nullable=True)  # 消息链接
    received_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )  # 接收时间

    # 消息类型标识（标准化存储，避免后续分析）
    is_patch = Column(
        Boolean, default=False, nullable=False, index=True
    )  # 是否是 PATCH
    is_reply = Column(
        Boolean, default=False, nullable=False, index=True
    )  # 是否是 REPLY
    is_series_patch = Column(Boolean, default=False, nullable=False)  # 是否是系列 PATCH

    # PATCH 信息（如果是 PATCH，标准化存储）
    patch_version = Column(String(20), nullable=True)  # PATCH 版本（如 v5）
    patch_index = Column(
        Integer, nullable=True, default=0
    )  # PATCH 序号（如 1/4 中的 1），默认 0
    patch_total = Column(
        Integer, nullable=True, default=0
    )  # PATCH 总数（如 1/4 中的 4），默认 0
    is_cover_letter = Column(
        Boolean, default=False, nullable=False
    )  # 是否是 Cover Letter (0/n)

    # 系列 PATCH 的根 message_id（用于关联系列中的 PATCH）
    series_message_id = Column(String(500), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class OperationLog(Base):  # pylint: disable=too-few-public-methods
    """操作日志模型

    记录用户操作历史，如订阅、取消订阅、启动/停止监控等。
    这是 SQLAlchemy ORM 模型，主要作为数据容器，不需要太多公共方法。
    """

    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    operator_id = Column(String(100), nullable=False, index=True)
    operator_name = Column(String(200), nullable=False)
    action = Column(
        String(50), nullable=False, index=True
    )  # subscribe, unsubscribe, start_monitor, etc.
    target_name = Column(
        String(200), nullable=False
    )  # 操作目标名称（子系统名称或其他）
    subsystem_name = Column(String(100), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PatchCardModel(Base):  # pylint: disable=too-few-public-methods
    """PATCH 卡片模型

    存储 PATCH 邮件的卡片信息，用于跟踪哪些 PATCH 已建立 Thread。
    """

    __tablename__ = "patch_cards"

    id = Column(Integer, primary_key=True, index=True)
    message_id_header = Column(
        String(500), unique=True, nullable=False, index=True
    )  # PATCH 的 message_id_header
    subsystem_name = Column(String(100), nullable=False, index=True)
    platform_message_id = Column(
        String(100), nullable=False, index=True
    )  # 平台卡片消息 ID
    platform_channel_id = Column(String(100), nullable=False)  # 平台频道 ID
    subject = Column(String(500), nullable=False)  # PATCH 主题
    author = Column(String(200), nullable=False)  # PATCH 作者
    url = Column(String(1000), nullable=True)  # PATCH 链接
    has_thread = Column(Boolean, default=False, nullable=False)  # 是否已建立 Thread

    # PATCH 系列信息
    is_series_patch = Column(Boolean, default=False, nullable=False)  # 是否是系列 PATCH
    series_message_id = Column(
        String(500), nullable=True, index=True
    )  # 系列 PATCH 的根 message_id（通常是 0/n 的 message_id）
    patch_version = Column(String(20), nullable=True)  # PATCH 版本（如 v5）
    patch_index = Column(
        Integer, nullable=True, default=0
    )  # PATCH 序号（如 1/4 中的 1），默认 0
    patch_total = Column(
        Integer, nullable=True, default=0
    )  # PATCH 总数（如 1/4 中的 4），默认 0

    to_cc_list = Column(
        JSON, nullable=True
    )  # To 和 CC 列表（从 root patch 抓取，JSON 格式存储邮箱列表，合并去重）

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)  # 过期时间（24小时后）


class PatchThreadModel(Base):  # pylint: disable=too-few-public-methods
    """PATCH Thread 模型

    存储 PATCH 对应的 Thread 信息，用于将 REPLY 消息发送到对应的 Thread。
    这是平台无关的模型，可以用于任何支持 Thread 功能的平台。
    """

    __tablename__ = "patch_threads"

    id = Column(Integer, primary_key=True, index=True)
    patch_card_message_id_header = Column(
        String(500), nullable=False, unique=True, index=True
    )  # PATCH 卡片的 message_id_header（用于关联，不使用外键）
    thread_id = Column(
        String(100), unique=True, nullable=False, index=True
    )  # Discord Thread ID
    thread_name = Column(String(500), nullable=False)  # Thread 名称
    is_active = Column(Boolean, default=True, nullable=False)  # Thread 是否活跃
    overview_message_id = Column(
        String(100), nullable=True, index=True
    )  # Thread Overview 消息 ID（用于更新）
    sub_patch_messages = Column(
        JSON, nullable=True
    )  # 子 PATCH 消息映射 {patch_index: message_id}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    archived_at = Column(DateTime, nullable=True)  # Thread 归档时间


class FilterConfigModel(Base):  # pylint: disable=too-few-public-methods
    """过滤配置模型

    存储过滤器的全局配置项。
    """

    __tablename__ = "filter_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, unique=True, index=True)  # 配置键
    value = Column(JSON, nullable=False)  # 配置值（JSON 格式）
    description = Column(Text, nullable=True)  # 配置描述
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class PatchCardFilterModel(Base):  # pylint: disable=too-few-public-methods
    """PATCH 卡片过滤规则模型

    存储过滤规则，用于控制哪些 PATCH 可以创建 Patch Card。
    过滤规则在默认 filter（单 Patch 和 Series Patch 的 Cover Letter）基础上应用。
    """

    __tablename__ = "patch_card_filters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)  # 规则名称
    enabled = Column(Boolean, default=True, nullable=False, index=True)  # 是否启用

    # 过滤条件（JSON 格式存储）
    # 支持的字段：
    # - author: 作者名称（字符串或列表，支持正则）
    # - author_email: 作者邮箱（字符串或列表，支持正则）
    # - subject: 主题（字符串或列表，支持正则）
    # - subsys/subsystem: 子系统名称（字符串或列表，支持正则）
    # - keywords: 内容关键词（字符串或列表，支持正则，从邮件内容中匹配）
    # - cclist/cc: CC 列表（字符串或列表，支持正则，从 root patch 的 CC 列表中匹配）
    # 规则组内不同条件使用 AND 逻辑，多个规则组之间使用 OR 逻辑
    filter_conditions = Column(JSON, nullable=False)  # 过滤条件

    description = Column(Text, nullable=True)  # 规则描述
    created_by = Column(String(200), nullable=True)  # 创建者
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
