-- 迁移 005: 为 patch_cards 表添加 to_cc_list 字段
-- 执行时间: 2024
-- 说明: 添加 to_cc_list 字段用于存储 To 和 CC 列表（合并去重）

-- 添加 to_cc_list 字段
-- 注意：如果字段已存在，SQLite 会报错，但迁移系统会捕获并忽略 "duplicate" 或 "already exists" 错误
ALTER TABLE patch_cards ADD COLUMN to_cc_list JSON;

