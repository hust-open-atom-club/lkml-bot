-- 迁移 003: 创建 filter_config 表
-- 执行时间: 2025

CREATE TABLE IF NOT EXISTS filter_config (
    id          INTEGER PRIMARY KEY,
    key         VARCHAR(100) NOT NULL UNIQUE,
    value       JSON NOT NULL,
    description TEXT,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_filter_config_key
    ON filter_config (key);

