"""过滤配置仓储类"""

import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FilterConfigModel

logger = logging.getLogger(__name__)


@dataclass
class FilterConfigData:
    """过滤配置数据类"""

    id: int
    key: str
    value: any  # 配置值（JSON 格式）
    description: Optional[str] = None
    updated_at: Optional[object] = None


class FilterConfigRepository:
    """过滤配置仓储类，提供过滤配置的数据访问操作"""

    def __init__(self, session: AsyncSession):
        """初始化仓储

        Args:
            session: 数据库会话
        """
        self.session = session

    def _model_to_data(self, model: FilterConfigModel) -> FilterConfigData:
        """将模型转换为数据类

        Args:
            model: FilterConfigModel 实例

        Returns:
            FilterConfigData 实例
        """
        return FilterConfigData(
            id=model.id,
            key=model.key,
            value=model.value,
            description=model.description,
            updated_at=model.updated_at,
        )

    async def get(self, key: str, default=None) -> any:
        """获取配置值

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值，如果不存在则返回默认值
        """
        import json

        result = await self.session.execute(
            select(FilterConfigModel).where(FilterConfigModel.key == key)
        )
        model = result.scalar_one_or_none()
        if not model:
            return default
        # 如果值是字符串且看起来像 JSON 布尔值，尝试解析
        if isinstance(model.value, str) and model.value in ("false", "true"):
            try:
                return json.loads(model.value)
            except (json.JSONDecodeError, ValueError):
                pass
        return model.value

    async def set(
        self, key: str, value: any, description: Optional[str] = None
    ) -> FilterConfigData:
        """设置配置值

        Args:
            key: 配置键
            value: 配置值
            description: 配置描述

        Returns:
            配置数据
        """
        from sqlalchemy import text

        result = await self.session.execute(
            select(FilterConfigModel).where(FilterConfigModel.key == key)
        )
        model = result.scalar_one_or_none()

        # 对于布尔值，使用原生 SQL 直接存储 JSON 布尔值字符串
        # 原因：SQLite 的 JSON 列在 SQLAlchemy 中可能无法正确序列化布尔值
        if isinstance(value, bool):
            json_str = "false" if not value else "true"
            if model:
                await self.session.execute(
                    text(
                        "UPDATE filter_config SET value = :json_str, updated_at = CURRENT_TIMESTAMP WHERE key = :key"
                    ),
                    {"key": key, "json_str": json_str},
                )
                if description is not None:
                    await self.session.execute(
                        text(
                            "UPDATE filter_config SET description = :description, "
                            "updated_at = CURRENT_TIMESTAMP WHERE key = :key"
                        ),
                        {"key": key, "description": description},
                    )
            else:
                await self.session.execute(
                    text(
                        "INSERT INTO filter_config (key, value, description, updated_at) "
                        "VALUES (:key, :json_str, :description, CURRENT_TIMESTAMP)"
                    ),
                    {"key": key, "json_str": json_str, "description": description},
                )
            await self.session.flush()
            # 注意：上下文管理器会在退出时自动提交
            # 重新查询以获取更新后的模型
            result = await self.session.execute(
                select(FilterConfigModel).where(FilterConfigModel.key == key)
            )
            model = result.scalar_one_or_none()
        else:
            # 非布尔值使用 update() 语句更新，这是 SQLAlchemy 2.0 推荐的方式
            if model:
                # 使用 update() 语句直接更新
                # 注意：使用 update() 语句时，onupdate 不会自动触发，需要显式设置 updated_at
                update_values = {"value": value, "updated_at": datetime.utcnow()}
                if description is not None:
                    update_values["description"] = description

                result = await self.session.execute(
                    update(FilterConfigModel)
                    .where(FilterConfigModel.key == key)
                    .values(**update_values)
                )
                await self.session.flush()
            else:
                # 创建新记录
                model = FilterConfigModel(
                    key=key,
                    value=value,
                    description=description,
                )
                self.session.add(model)
                await self.session.flush()

            # 重新查询以获取更新后的模型
            result = await self.session.execute(
                select(FilterConfigModel).where(FilterConfigModel.key == key)
            )
            model = result.scalar_one_or_none()
            if not model:
                logger.error(f"FilterConfig {key} not found after update/create")
                raise RuntimeError(
                    f"Failed to retrieve filter_config after operation: {key}"
                )

        return self._model_to_data(model)

    async def get_exclusive_mode(self) -> bool:
        """获取独占模式配置

        Returns:
            是否启用独占模式，默认 False
        """
        value = await self.get("exclusive_mode", False)
        # get() 方法已经处理了字符串到布尔值的转换
        return bool(value)

    async def set_exclusive_mode(self, enabled: bool) -> FilterConfigData:
        """设置独占模式配置

        Args:
            enabled: 是否启用独占模式

        Returns:
            配置数据
        """
        return await self.set(
            "exclusive_mode",
            enabled,
            "独占模式：True=只允许匹配的创建，False=所有都创建但高亮匹配的",
        )
