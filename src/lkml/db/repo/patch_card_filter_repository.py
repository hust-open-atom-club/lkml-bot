"""PATCH 卡片过滤规则仓储类"""

import logging
from typing import List, Optional
from dataclasses import dataclass

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PatchCardFilterModel

logger = logging.getLogger(__name__)


@dataclass
class PatchCardFilterData:
    """PATCH 卡片过滤规则数据类

    每个过滤器就是一个规则组，规则组内不同条件使用 AND 逻辑，
    多个规则组（过滤器）之间使用 OR 逻辑。
    """

    id: int
    name: str
    enabled: bool
    filter_conditions: dict  # 过滤条件，不同 key 之间使用 AND 逻辑
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[object] = None
    updated_at: Optional[object] = None


class PatchCardFilterRepository:
    """PATCH 卡片过滤规则仓储类，提供过滤规则的数据访问操作"""

    def __init__(self, session: AsyncSession):
        """初始化仓储

        Args:
            session: 数据库会话
        """
        self.session = session

    def _model_to_data(self, model: PatchCardFilterModel) -> PatchCardFilterData:
        """将模型转换为数据类

        Args:
            model: PatchCardFilterModel 实例

        Returns:
            PatchCardFilterData 实例
        """
        import json

        # 处理 filter_conditions：如果是字符串，尝试解析为 JSON
        filter_conditions = model.filter_conditions
        if isinstance(filter_conditions, str):
            try:
                filter_conditions = json.loads(filter_conditions)
            except (json.JSONDecodeError, ValueError):
                # 如果解析失败，使用空字典
                filter_conditions = {}

        return PatchCardFilterData(
            id=model.id,
            name=model.name,
            enabled=model.enabled,
            filter_conditions=filter_conditions or {},
            description=model.description,
            created_by=model.created_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _data_to_model(self, data: PatchCardFilterData) -> PatchCardFilterModel:
        """将数据类转换为模型

        Args:
            data: PatchCardFilterData 实例

        Returns:
            PatchCardFilterModel 实例
        """
        return PatchCardFilterModel(
            id=data.id,
            name=data.name,
            enabled=data.enabled,
            filter_conditions=data.filter_conditions,
            description=data.description,
            created_by=data.created_by,
        )

    async def create(self, data: PatchCardFilterData) -> PatchCardFilterData:
        """创建过滤规则

        Args:
            data: 过滤规则数据

        Returns:
            创建的过滤规则数据
        """
        import json
        from sqlalchemy import text

        # 显式序列化 JSON 数据，确保 SQLite 能正确存储
        # SQLite 的 JSON 列在 SQLAlchemy 中可能无法正确序列化复杂对象
        filter_conditions_json = json.dumps(data.filter_conditions, ensure_ascii=False)

        # 使用原生 SQL 插入，确保 JSON 数据正确存储
        await self.session.execute(
            text(
                """
                INSERT INTO patch_card_filters (
                    name, enabled, filter_conditions, description, created_by,
                    created_at, updated_at
                )
                VALUES (
                    :name, :enabled, :filter_conditions, :description, :created_by,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
            """
            ),
            {
                "name": data.name,
                "enabled": data.enabled,
                "filter_conditions": filter_conditions_json,
                "description": data.description,
                "created_by": data.created_by,
            },
        )
        await self.session.flush()

        # 重新查询以获取插入的记录
        result = await self.session.execute(
            select(PatchCardFilterModel).where(PatchCardFilterModel.name == data.name)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise RuntimeError(f"Failed to retrieve inserted filter: {data.name}")

        return self._model_to_data(model)

    async def find_by_id(self, filter_id: int) -> Optional[PatchCardFilterData]:
        """根据 ID 查找过滤规则

        Args:
            filter_id: 过滤规则 ID

        Returns:
            过滤规则数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchCardFilterModel).where(PatchCardFilterModel.id == filter_id)
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def find_by_name(self, name: str) -> Optional[PatchCardFilterData]:
        """根据名称查找过滤规则

        Args:
            name: 过滤规则名称

        Returns:
            过滤规则数据，如果不存在则返回 None
        """
        result = await self.session.execute(
            select(PatchCardFilterModel).where(PatchCardFilterModel.name == name)
        )
        model = result.scalar_one_or_none()
        return self._model_to_data(model) if model else None

    async def find_all(self, enabled_only: bool = False) -> List[PatchCardFilterData]:
        """查找所有过滤规则

        Args:
            enabled_only: 是否只返回启用的规则

        Returns:
            过滤规则数据列表
        """
        query = select(PatchCardFilterModel)
        if enabled_only:
            query = query.where(PatchCardFilterModel.enabled.is_(True))
        query = query.order_by(PatchCardFilterModel.created_at.desc())

        result = await self.session.execute(query)
        models = result.scalars().all()
        return [self._model_to_data(model) for model in models]

    async def update(
        self, filter_id: int, data: PatchCardFilterData
    ) -> Optional[PatchCardFilterData]:
        """更新过滤规则

        Args:
            filter_id: 过滤规则 ID
            data: 更新的数据

        Returns:
            更新后的过滤规则数据，如果不存在则返回 None
        """
        import json
        from sqlalchemy import text

        result = await self.session.execute(
            select(PatchCardFilterModel).where(PatchCardFilterModel.id == filter_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None

        # 显式序列化 JSON 数据，确保 SQLite 能正确存储
        filter_conditions_json = json.dumps(data.filter_conditions, ensure_ascii=False)

        # 使用原生 SQL 更新，确保 JSON 数据正确存储
        await self.session.execute(
            text(
                """
                UPDATE patch_card_filters 
                SET name = :name, enabled = :enabled, filter_conditions = :filter_conditions, 
                    description = :description, updated_at = CURRENT_TIMESTAMP
                WHERE id = :filter_id
            """
            ),
            {
                "filter_id": filter_id,
                "name": data.name,
                "enabled": data.enabled,
                "filter_conditions": filter_conditions_json,
                "description": data.description,
            },
        )
        await self.session.flush()

        # 重新查询以获取更新后的记录
        result = await self.session.execute(
            select(PatchCardFilterModel).where(PatchCardFilterModel.id == filter_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise RuntimeError(f"Failed to retrieve updated filter: {filter_id}")

        return self._model_to_data(model)

    async def delete(self, filter_id: int) -> bool:
        """删除过滤规则

        Args:
            filter_id: 过滤规则 ID

        Returns:
            是否删除成功
        """
        result = await self.session.execute(
            delete(PatchCardFilterModel).where(PatchCardFilterModel.id == filter_id)
        )
        await self.session.flush()
        return result.rowcount > 0

    async def toggle_enabled(self, filter_id: int, enabled: bool) -> bool:
        """切换过滤规则的启用状态

        Args:
            filter_id: 过滤规则 ID
            enabled: 是否启用

        Returns:
            是否更新成功
        """
        result = await self.session.execute(
            select(PatchCardFilterModel).where(PatchCardFilterModel.id == filter_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return False

        model.enabled = enabled
        await self.session.flush()
        return True
