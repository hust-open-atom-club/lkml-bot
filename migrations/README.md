# 数据库迁移说明

## 概述

数据库迁移系统会在程序启动时自动执行，确保数据库结构始终与代码模型保持一致。

## 迁移脚本命名规则

迁移脚本文件命名格式：`{版本号}_{描述}.sql`

- 版本号：3位数字，从 001 开始递增
- 描述：简短描述，使用下划线分隔
- 示例：`001_add_indexes_to_feed_messages.sql`

## 迁移执行时机

迁移在数据库初始化时自动执行，具体时机：
1. 首次创建数据库表结构后
2. 每次程序启动时（检查并执行未应用的迁移）

## 迁移记录

已执行的迁移会记录在 `schema_migrations` 表中：
- `version`: 迁移版本号
- `applied_at`: 执行时间

## 当前迁移列表

### 001_add_indexes_to_feed_messages.sql
为 `feed_messages` 表添加索引：
- `message_id` 唯一索引
- `message_id_header` 唯一索引
- 常用查询字段索引（subsystem_name, received_at, is_patch, is_reply, is_series_patch, series_message_id）

### 002_add_indexes_to_patch_card_filters.sql
为 `patch_card_filters` 表添加索引：
- `name` 唯一索引
- `enabled` 索引

### 003_create_filter_config_table.sql
创建 `filter_config` 表：
- 存储全局过滤配置
- 迁移旧的 `exclusive` 字段到全局配置

### 004_remove_exclusive_from_patch_card_filters.sql
从 `patch_card_filters` 表删除 `exclusive` 字段：
- 删除 `exclusive` 列及其索引
- 该字段已迁移到全局配置 `filter_config` 表中

### 005_add_to_cc_list_to_patch_cards.sql
为 `patch_cards` 表添加 `to_cc_list` 字段：
- 添加 `to_cc_list` 列（JSON 类型，可为空）
- 用于存储 To 和 CC 列表（合并去重）

## 添加新迁移

1. 在 `migrations/` 目录下创建新的 SQL 文件
2. 文件名格式：`{下一个版本号}_{描述}.sql`
3. 确保 SQL 语句是幂等的（可以安全地重复执行）
4. 使用 `IF NOT EXISTS` 或 `OR IGNORE` 等语句避免重复执行错误

## 注意事项

- 迁移脚本应该是幂等的，可以安全地重复执行
- 使用 `CREATE INDEX IF NOT EXISTS`、`CREATE TABLE IF NOT EXISTS` 等语句
- 避免使用 `DROP` 语句（除非必要）
- 迁移失败不会阻止程序启动，但会记录错误日志

