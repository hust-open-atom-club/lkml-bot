-- 迁移 001: 为 feed_messages 表添加索引
-- 执行时间: 2024

-- message_id 唯一索引（允许多个 NULL）
CREATE UNIQUE INDEX IF NOT EXISTS ux_feed_messages_message_id
    ON feed_messages (message_id);

-- message_id_header 唯一索引
CREATE UNIQUE INDEX IF NOT EXISTS ux_feed_messages_message_id_header
    ON feed_messages (message_id_header);

-- 常用查询字段索引
CREATE INDEX IF NOT EXISTS ix_feed_messages_subsystem_name
    ON feed_messages (subsystem_name);

CREATE INDEX IF NOT EXISTS ix_feed_messages_received_at
    ON feed_messages (received_at);

CREATE INDEX IF NOT EXISTS ix_feed_messages_is_patch
    ON feed_messages (is_patch);

CREATE INDEX IF NOT EXISTS ix_feed_messages_is_reply
    ON feed_messages (is_reply);

CREATE INDEX IF NOT EXISTS ix_feed_messages_is_series_patch
    ON feed_messages (is_series_patch);

CREATE INDEX IF NOT EXISTS ix_feed_messages_series_message_id
    ON feed_messages (series_message_id);

