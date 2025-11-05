"""查询服务"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from nonebot.log import logger

from ..config import get_config
from ..db.database import get_database
from ..db.models import EmailMessage, OperationLog, Subsystem


class QueryService:
    """数据查询服务"""

    async def get_latest_news(
        self, subsystem_name: Optional[str] = None, count: int = 5
    ) -> list[dict[str, str | int | None]]:
        """获取最新新闻

        Args:
            subsystem_name: 子系统名称（可选）
            count: 返回数量

        Returns:
            最新新闻列表
        """
        try:
            config = get_config()
            database = get_database()
            async with database.get_db_session() as session:
                # 构建查询条件
                query = select(EmailMessage).join(Subsystem).where(Subsystem.subscribed)

                if subsystem_name:
                    query = query.where(Subsystem.name == subsystem_name)

                max_count = config.max_news_count
                query = query.order_by(EmailMessage.received_at.desc()).limit(
                    min(count, max_count)
                )

                result = await session.execute(query)
                messages = result.scalars().all()

                return [
                    {
                        "id": msg.id,
                        "subject": msg.subject,
                        "sender": msg.sender,
                        "sender_email": msg.sender_email,
                        "subsystem": msg.subsystem.name,
                        "received_at": msg.received_at.isoformat(),
                        "content": (
                            msg.content[:200] + "..."
                            if msg.content and len(msg.content) > 200
                            else msg.content
                        ),
                    }
                    for msg in messages
                ]
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to get latest news: {e}")
            return []

    async def get_operation_logs(
        self, limit: int = 50
    ) -> list[dict[str, str | int | None]]:
        """获取操作日志

        Args:
            limit: 返回数量限制

        Returns:
            操作日志列表
        """
        try:
            database = get_database()
            async with database.get_db_session() as session:
                result = await session.execute(
                    select(OperationLog)
                    .order_by(OperationLog.created_at.desc())
                    .limit(limit)
                )
                logs = result.scalars().all()

                return [
                    {
                        "id": log.id,
                        "operator_id": log.operator_id,
                        "operator_name": log.operator_name,
                        "action": log.action,
                        "target_name": log.target_name,
                        "subsystem_name": log.subsystem_name,
                        "details": log.details,
                        "created_at": log.created_at.isoformat(),
                    }
                    for log in logs
                ]
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to get operation logs: {e}")
            return []


# 全局服务实例
query_service = QueryService()
