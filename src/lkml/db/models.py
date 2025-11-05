"""LKML领域模型"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

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

    # 关系
    email_messages = relationship("EmailMessage", back_populates="subsystem")


class EmailMessage(Base):  # pylint: disable=too-few-public-methods
    """邮件消息模型

    存储从邮件列表抓取的单封邮件信息。
    这是 SQLAlchemy ORM 模型，主要作为数据容器，不需要太多公共方法。
    """

    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)
    subsystem_id = Column(Integer, ForeignKey("subsystems.id"), nullable=False)
    message_id = Column(
        String(500), unique=True, nullable=True, index=True
    )  # 消息唯一标识
    subject = Column(String(500), nullable=False)
    sender = Column(String(200), nullable=False)
    sender_email = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    url = Column(String(1000), nullable=True)  # 消息链接
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # 原始邮件头部关键信息（若可从 feed 获取）
    message_id_header = Column(String(500), nullable=True, index=True)
    in_reply_to_header = Column(String(500), nullable=True, index=True)

    # 关系
    subsystem = relationship("Subsystem", back_populates="email_messages")


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
