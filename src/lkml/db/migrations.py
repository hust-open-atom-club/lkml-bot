"""数据库迁移模块

在程序启动时自动执行数据库迁移脚本。
"""

import logging
from pathlib import Path
from typing import List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class MigrationRunner:
    """数据库迁移执行器"""

    def __init__(self, engine: AsyncEngine, migrations_dir: Optional[Path] = None):
        """初始化迁移执行器

        Args:
            engine: SQLAlchemy 异步引擎
            migrations_dir: 迁移脚本目录，默认为项目根目录下的 migrations 目录
        """
        self.engine = engine
        if migrations_dir is None:
            # 默认迁移目录：项目根目录下的 migrations
            project_root = Path(__file__).parent.parent.parent.parent
            migrations_dir = project_root / "migrations"
        self.migrations_dir = migrations_dir

    async def ensure_migrations_table(self):
        """确保迁移记录表存在"""
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(50) PRIMARY KEY,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
                )
            )

    async def get_applied_migrations(self) -> List[str]:
        """获取已执行的迁移版本列表

        Returns:
            已执行的迁移版本列表
        """
        await self.ensure_migrations_table()
        async with self.engine.begin() as conn:
            result = await conn.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            )
            return [row[0] for row in result.fetchall()]

    async def mark_migration_applied(self, version: str):
        """标记迁移已执行

        Args:
            version: 迁移版本号
        """
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO schema_migrations (version) VALUES (:version)"
                ),
                {"version": version},
            )

    def get_migration_files(self) -> List[tuple[str, Path]]:
        """获取所有迁移脚本文件

        Returns:
            (版本号, 文件路径) 元组列表，按版本号排序
        """
        if not self.migrations_dir.exists():
            logger.warning(f"Migrations directory not found: {self.migrations_dir}")
            return []

        migrations = []
        for file_path in sorted(self.migrations_dir.glob("*.sql")):
            # 文件名格式: 001_description.sql
            filename = file_path.name
            if filename.startswith("."):
                continue
            try:
                version = filename.split("_", 1)[0]
                migrations.append((version, file_path))
            except (ValueError, IndexError):
                logger.warning(f"Invalid migration filename: {filename}")
                continue

        return sorted(migrations, key=lambda x: x[0])

    async def execute_migration(self, version: str, file_path: Path) -> bool:
        """执行单个迁移脚本

        Args:
            version: 迁移版本号
            file_path: 迁移脚本文件路径

        Returns:
            是否执行成功
        """
        try:
            logger.info(f"Executing migration {version}: {file_path.name}")
            sql_content = file_path.read_text(encoding="utf-8")

            # 移除注释行（以 -- 开头的行）
            lines = []
            for line in sql_content.split("\n"):
                stripped = line.strip()
                if stripped and not stripped.startswith("--"):
                    lines.append(line)
                elif not stripped:
                    lines.append("")  # 保留空行以保持格式

            sql_content = "\n".join(lines)

            # 按分号分割 SQL 语句（简单处理，假设 SQL 语句格式正确）
            statements = [
                stmt.strip()
                for stmt in sql_content.split(";")
                if stmt.strip() and not stmt.strip().startswith("--")
            ]

            # 执行所有 SQL 语句
            async with self.engine.begin() as conn:
                for statement in statements:
                    if statement:
                        try:
                            await conn.execute(text(statement))
                        except (RuntimeError, ValueError) as e:
                            # 某些语句可能因为已存在而失败（如 CREATE INDEX IF NOT EXISTS）
                            # 或者因为不存在而失败（如 DROP COLUMN 时列已不存在）
                            # 检查是否是"已存在"或"不存在"的错误
                            error_msg = str(e).lower()
                            if (
                                "already exists" in error_msg
                                or "duplicate" in error_msg
                                or "no such column" in error_msg
                                or "no such index" in error_msg
                            ):
                                logger.debug(
                                    f"Statement already applied or resource not found (ignoring): {statement[:50]}..."
                                )
                            else:
                                raise

            await self.mark_migration_applied(version)
            logger.info(f"Migration {version} applied successfully")
            return True

        except (RuntimeError, ValueError, AttributeError, IOError) as e:
            logger.error(f"Failed to execute migration {version}: {e}", exc_info=True)
            return False

    async def run_migrations(self) -> bool:
        """执行所有未应用的迁移

        Returns:
            是否所有迁移都执行成功
        """
        await self.ensure_migrations_table()
        applied = await self.get_applied_migrations()
        migrations = self.get_migration_files()

        if not migrations:
            logger.info("No migration files found")
            return True

        logger.info(
            f"Found {len(migrations)} migration files, {len(applied)} already applied"
        )

        success = True
        for version, file_path in migrations:
            if version in applied:
                logger.debug(f"Migration {version} already applied, skipping")
                continue

            if not await self.execute_migration(version, file_path):
                success = False
                logger.error(f"Migration {version} failed, stopping")
                break

        return success


async def run_database_migrations(engine: AsyncEngine) -> bool:
    """运行数据库迁移（便捷函数）

    Args:
        engine: SQLAlchemy 异步引擎

    Returns:
        是否所有迁移都执行成功
    """
    runner = MigrationRunner(engine)
    return await runner.run_migrations()
