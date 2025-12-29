-- 迁移 002: 为 patch_card_filters 表添加索引
-- 执行时间: 2024

-- name 唯一索引
CREATE UNIQUE INDEX IF NOT EXISTS ux_patch_card_filters_name
    ON patch_card_filters (name);

-- enabled 索引
CREATE INDEX IF NOT EXISTS ix_patch_card_filters_enabled
    ON patch_card_filters (enabled);

