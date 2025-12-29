-- 迁移 004: 从 patch_card_filters 表删除 exclusive 字段
-- 执行时间: 2024
-- 说明: exclusive 字段已迁移到全局配置 filter_config 表中

-- 先删除 exclusive 字段的索引（必须在使用 DROP COLUMN 之前删除）
-- 注意：如果索引不存在，此语句不会报错（IF EXISTS）
DROP INDEX IF EXISTS ix_patch_card_filters_exclusive;

-- 删除 exclusive 列（SQLite 3.35.0+ 支持）
-- 注意：如果列不存在，SQLite 会报错，迁移系统会正确处理错误
-- 如果 SQLite 版本低于 3.35.0，此操作会失败，需要使用创建新表的方式
ALTER TABLE patch_card_filters DROP COLUMN exclusive;

