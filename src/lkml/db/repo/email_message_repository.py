"""邮件消息仓储类"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import select
from ..models import EmailMessage, Subsystem


@dataclass
class EmailMessageData:  # pylint: disable=too-many-instance-attributes
    """邮件消息数据对象（减少函数参数数量）"""

    subsystem: Subsystem
    message_id: Optional[str]
    subject: str
    sender: str
    sender_email: str
    content: Optional[str]
    url: Optional[str]
    received_at: object
    message_id_header: Optional[str] = None
    in_reply_to_header: Optional[str] = None


class EmailMessageRepository:
    """邮件消息仓储类，提供邮件消息的数据访问操作"""

    async def find_by_message_id(
        self, session, message_id: str
    ) -> Optional[EmailMessage]:
        """根据消息ID查找邮件消息

        Args:
            session: 数据库会话
            message_id: 消息唯一标识

        Returns:
            邮件消息对象，如果不存在则返回 None
        """
        result = await session.execute(
            select(EmailMessage).where(EmailMessage.message_id == message_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session,
        *,
        data: EmailMessageData,
    ) -> EmailMessage:
        """创建邮件消息

        Args:
            session: 数据库会话
            data: 邮件消息数据对象

        Returns:
            创建的邮件消息对象
        """
        message_data = {
            "message_id": data.message_id,
            "subject": data.subject,
            "sender": data.sender,
            "sender_email": data.sender_email,
            "content": data.content,
            "url": data.url,
            "subsystem_name": data.subsystem.name,
            "received_at": data.received_at,
            "message_id_header": data.message_id_header,
            "in_reply_to_header": data.in_reply_to_header,
        }
        entity = EmailMessage(**message_data)
        session.add(entity)
        await session.flush()
        return entity

    async def bulk_create(self, session, entities: Iterable[EmailMessage]) -> None:
        """批量创建邮件消息

        Args:
            session: 数据库会话
            entities: 邮件消息对象集合
        """
        session.add_all(list(entities))
        await session.flush()


# 单例实例（全局实例，用于方便访问）
EMAIL_MESSAGE_REPO = EmailMessageRepository()
