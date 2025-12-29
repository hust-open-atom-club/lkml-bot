"""数据库模块（数据库接口和实现）

定义了数据库访问的抽象接口和具体实现，提供统一的数据库会话管理。
"""

from abc import ABC, abstractmethod
from typing import Optional
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import logging

logger = logging.getLogger(__name__)

# 延迟导入 Service 类以避免循环导入
# Service 类只在 with_services 方法中使用，不会在模块级别导入

__all__ = [
    "Database",
    "LKMLDatabase",
    "SessionProvider",
    "set_database",
    "get_database",
    "get_session_provider",
    "get_patch_card_service",
    "get_thread_service",
]


class Database(ABC):  # pylint: disable=too-few-public-methods
    """数据库接口

    定义数据库访问的抽象接口，支持不同的数据库实现。
    这是抽象基类，只定义核心接口方法。
    """

    @abstractmethod
    async def get_db_session(self):
        """获取数据库会话（返回异步上下文管理器）

        Returns:
            异步上下文管理器，用于获取数据库会话

        注意：子类实现为 async 方法是合理的，因为需要异步创建会话。
        """


# 数据库单例管理器（避免使用全局变量）
class _DatabaseManager:
    """数据库管理器（单例模式）"""

    _instance: Optional["_DatabaseManager"] = None
    _database: Optional[Database] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def set_database(self, database: Database) -> None:
        """设置数据库实例"""
        self._database = database

    def get_database(self) -> Database:
        """获取数据库实例"""
        if self._database is None:
            raise RuntimeError("Database not initialized. Call set_database() first.")
        return self._database


_database_manager = _DatabaseManager()


def set_database(database: Database) -> None:
    """设置数据库实例

    Args:
        database: 数据库实现实例
    """
    _database_manager.set_database(database)


def get_database() -> Database:
    """获取数据库实例

    Returns:
        数据库实例

    Raises:
        RuntimeError: 如果数据库未初始化
    """
    return _database_manager.get_database()


class LKMLDatabase(Database):  # pylint: disable=too-few-public-methods
    """LKML 数据库实现

    使用 SQLAlchemy 实现异步数据库访问，支持自动建表。
    主要提供数据库会话管理，方法数量是合理的。
    """

    def __init__(self, database_url: str, base):
        """初始化数据库连接

        Args:
            database_url: 数据库连接 URL
            base: SQLAlchemy 的 Base 类
        """
        self.database_url = database_url
        self.base = base
        self._engine = None
        self._session_factory = None
        self._tables_created = False

    def _init_engine(self):
        """初始化数据库引擎（懒加载模式）"""
        if self._engine is None:
            # 为 SQLite 配置连接参数以改善并发处理
            connect_args = {}
            if "sqlite" in self.database_url:
                connect_args = {
                    "timeout": 30.0,  # 增加等待锁的超时时间（秒）
                    "check_same_thread": False,  # 允许在不同线程中使用
                }

            self._engine = create_async_engine(
                self.database_url,
                echo=False,
                future=True,
                connect_args=connect_args if connect_args else None,
                pool_pre_ping=True,  # 连接前检查连接是否有效
                # 设置连接池参数以减少并发冲突
                pool_size=5,  # 连接池大小
                max_overflow=10,  # 最大溢出连接数
            )
            self._session_factory = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )

    async def _ensure_tables(self):
        """确保数据库表已创建

        首次调用时自动创建表结构，然后执行数据库迁移。
        """
        if not self._tables_created:
            self._init_engine()
            async with self._engine.begin() as conn:
                # 使用 checkfirst=True 检查表是否存在，避免重复创建
                await conn.run_sync(
                    lambda sync_conn: self.base.metadata.create_all(
                        sync_conn, checkfirst=True
                    )
                )

            # 执行数据库迁移
            try:
                from .migrations import run_database_migrations

                success = await run_database_migrations(self._engine)
                if not success:
                    logger.warning("Some database migrations failed, but continuing...")
            except (RuntimeError, ValueError, AttributeError, ImportError) as e:
                logger.error(f"Failed to run database migrations: {e}", exc_info=True)
                # 迁移失败不影响表创建，继续执行

            self._tables_created = True

    @asynccontextmanager
    async def get_db_session(self):  # type: ignore[override]
        """获取数据库会话

        Yields:
            数据库会话对象，使用完毕后自动提交或回滚
        """
        from nonebot.exception import FinishedException

        self._init_engine()
        await self._ensure_tables()
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except FinishedException:
                # FinishedException 是 NoneBot 框架的正常流程异常，用于结束消息处理
                # 在抛出前先提交数据库更改，不要回滚
                try:
                    await session.commit()
                except (RuntimeError, ValueError) as commit_error:
                    logger.warning(
                        f"Failed to commit after FinishedException: {commit_error}"
                    )
                    await session.rollback()
                raise
            except (
                BaseException
            ) as e:  # 捕获其他所有异常（包括 KeyboardInterrupt）以进行回滚
                logger.error(
                    f"Database session commit failed, rolling back: {e}", exc_info=True
                )
                await session.rollback()
                raise
            finally:
                await session.close()


class SessionProvider:
    """Session 提供者（DB 层）

    负责创建 session 并注入到所有 Repository，然后创建 Service 实例。
    Plugins 层通过此提供者获取 Service，不需要知道 session 的存在。
    """

    def __init__(self, database: Database):
        """初始化 Session 提供者

        Args:
            database: 数据库实例
        """
        self.database = database

    @asynccontextmanager
    async def with_services(
        self,
    ):
        """获取 Service 实例的上下文管理器

        内部创建 session，创建 Repository 和 Service 实例。
        Plugins 层使用此方法获取 Service，不需要知道 session 的存在。

        Yields:
            (patch_card_service, thread_service) 元组
        """
        async with self.database.get_db_session() as session:
            # 创建 Repository 和 Service 实例（使用辅助函数以减少重复代码）
            from ..service.helpers import create_repositories_and_services

            (
                _,
                _,
                _,
                patch_card_service,
                thread_service,
            ) = create_repositories_and_services(session)

            yield patch_card_service, thread_service

    @asynccontextmanager
    async def with_patch_card_service(self):
        """获取 PatchCardService 实例的上下文管理器

        Yields:
            PatchCardService 实例
        """
        async with self.with_services() as (patch_card_service, _):
            yield patch_card_service

    @asynccontextmanager
    async def with_thread_service(self):
        """获取 ThreadService 实例的上下文管理器

        Yields:
            ThreadService 实例
        """
        async with self.with_services() as (_, thread_service):
            yield thread_service


# SessionProvider 单例管理器
_session_provider: Optional[SessionProvider] = None


def get_session_provider() -> SessionProvider:
    """获取 SessionProvider 实例

    Returns:
        SessionProvider 实例

    Raises:
        RuntimeError: 如果数据库未初始化
    """
    # Global variable is necessary for singleton pattern
    # pylint: disable=global-statement
    global _session_provider
    if _session_provider is None:
        database = get_database()
        _session_provider = SessionProvider(database)
    return _session_provider


# 工厂函数：供 plugins 层使用，内部管理 SessionProvider


@asynccontextmanager
async def get_patch_card_service():
    """获取 PatchCardService 实例

    内部使用 SessionProvider 创建 session 和 repository，然后创建 Service 实例。
    Plugins 层不需要知道 SessionProvider 的存在。

    Yields:
        PatchCardService 实例（通过 async context manager）
    """
    session_provider = get_session_provider()
    async with session_provider.with_patch_card_service() as patch_card_service:
        yield patch_card_service


@asynccontextmanager
async def get_thread_service():
    """获取 ThreadService 实例

    内部使用 SessionProvider 创建 session 和 repository，然后创建 Service 实例。
    Plugins 层不需要知道 SessionProvider 的存在。

    Yields:
        ThreadService 实例（通过 async context manager）
    """
    session_provider = get_session_provider()
    async with session_provider.with_thread_service() as thread_service:
        yield thread_service
