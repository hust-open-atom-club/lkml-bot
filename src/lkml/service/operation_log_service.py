"""操作日志辅助模块"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import OperationLog


@dataclass
class OperationParams:
    """操作日志参数对象（减少函数参数数量）"""

    operator_id: str
    operator_name: str
    action: str
    subsystem_name: Optional[str] = None
    details: Optional[str] = None


async def log_operation(
    session: AsyncSession,
    params: OperationParams,
) -> None:
    """记录操作日志

    Args:
        session: 数据库会话
        params: 操作日志参数对象
    """
    # 如果 subsystem_name 为 None，使用默认名称
    target_name = params.subsystem_name if params.subsystem_name is not None else "lkml"

    log = OperationLog(
        operator_id=params.operator_id,
        operator_name=params.operator_name,
        action=params.action,
        target_name=target_name,
        details=params.details,
    )
    session.add(log)
    await session.flush()
