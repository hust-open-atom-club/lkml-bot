"""PATCH 卡片过滤服务

提供过滤规则的业务逻辑层接口。
"""

import logging
import re
from typing import List, Optional

from ..db.repo import (
    PatchCardFilterRepository,
    PatchCardFilterData,
)
from .types import FeedMessage

logger = logging.getLogger(__name__)


class PatchCardFilterService:
    """PATCH 卡片过滤服务类"""

    def __init__(
        self,
        filter_repo: PatchCardFilterRepository,
        patch_card_repo=None,
        filter_config_repo=None,
        feed_message_repo=None,
    ):
        """初始化服务

        Args:
            filter_repo: 过滤规则仓储实例
            patch_card_repo: PatchCard 仓储实例（可选，用于获取 CC 列表）
            filter_config_repo: 过滤配置仓储实例（可选，用于获取全局配置）
            feed_message_repo: FeedMessage 仓储实例（可选，用于查找 root patch URL）
        """
        self.filter_repo = filter_repo
        self.patch_card_repo = patch_card_repo
        self.filter_config_repo = filter_config_repo
        self.feed_message_repo = feed_message_repo

    async def should_create_patch_card(
        self, feed_message: FeedMessage, _patch_info
    ) -> tuple[bool, list[str]]:
        """判断是否应该创建 Patch Card 并返回匹配的过滤规则

        在默认 filter（单 Patch 和 Series Patch 的 Cover Letter）基础上，
        应用所有启用的过滤规则。

        逻辑：
        - 每个过滤器就是一个规则组，组内不同条件使用 AND 逻辑
        - 多个规则组（过滤器）之间使用 OR 逻辑
        - 如果全局配置启用独占模式，则必须匹配至少一个规则才能创建
        - 如果全局配置未启用独占模式，则所有符合条件的都创建，但标记匹配的规则
        - 如果没有过滤规则，默认允许创建

        Args:
            feed_message: Feed 消息对象
            patch_info: PATCH 信息对象

        Returns:
            (should_create, matched_filter_names) 元组
            - should_create: True 表示应该创建，False 表示不应该创建
            - matched_filter_names: 匹配的过滤规则名称列表
        """
        # 获取所有启用的过滤规则
        all_filters = await self.filter_repo.find_all(enabled_only=True)

        # 如果没有过滤规则，默认允许创建（保持原有行为）
        if not all_filters:
            return (True, [])

        matched_filters = []

        # 获取全局独占模式配置
        exclusive_mode = False
        if self.filter_config_repo:
            exclusive_mode = await self.filter_config_repo.get_exclusive_mode()

        # 检查所有过滤器（每个过滤器就是一个规则组，组间 OR 逻辑）
        for filter_data in all_filters:
            if await self._matches_filter(feed_message, _patch_info, filter_data):
                matched_filters.append(filter_data.name)
                logger.debug(
                    f"Feed message matches filter '{filter_data.name}': "
                    f"{feed_message.message_id_header}"
                )

        # 如果启用了独占模式
        if exclusive_mode:
            # 必须匹配至少一个规则才能创建
            if matched_filters:
                return (True, matched_filters)
            logger.debug(
                f"Feed message does not match any filter (exclusive mode enabled): "
                f"{feed_message.message_id_header}"
            )
            return (False, [])

        # 如果未启用独占模式，有匹配的规则则允许创建并标记
        if matched_filters:
            return (True, matched_filters)

        # 没有匹配的规则，默认允许创建（保持原有行为）
        return (True, [])

    def _parse_regex_pattern(self, pattern_str: str) -> tuple[str | None, bool]:
        """解析正则表达式模式

        Args:
            pattern_str: 模式字符串

        Returns:
            (pattern, case_insensitive) 元组
            - pattern: 提取的正则表达式模式，如果不是正则则返回 None
            - case_insensitive: 是否不区分大小写
        """
        if not pattern_str.startswith("/"):
            return (None, False)

        if pattern_str.endswith("/i"):
            return (pattern_str[1:-2], True)  # 不区分大小写
        if pattern_str.endswith("/"):
            return (pattern_str[1:-1], False)  # 区分大小写

        return (None, False)

    def _match_single_pattern(self, val: str, pattern_str: str) -> bool:
        """匹配单个模式

        Args:
            val: 要匹配的值
            pattern_str: 模式字符串

        Returns:
            True 表示匹配，False 表示不匹配
        """
        pattern, case_insensitive = self._parse_regex_pattern(pattern_str)
        if pattern is not None:
            flags = re.IGNORECASE if case_insensitive else 0
            return bool(re.search(pattern, val, flags))
        # 普通字符串匹配（不区分大小写）
        return pattern_str.lower() in val.lower()

    def _match_value(self, val: str, cond) -> bool:
        """匹配单个值是否满足条件

        Args:
            val: 要匹配的值
            cond: 条件（字符串、列表或正则）

        Returns:
            True 表示匹配，False 表示不匹配
        """
        if not val:
            return False

        if isinstance(cond, str):
            return self._match_single_pattern(val, cond)

        if isinstance(cond, list):
            return any(
                self._match_single_pattern(val, c) for c in cond if isinstance(c, str)
            )

        return True

    async def _match_cc_condition(self, feed_message: FeedMessage, condition) -> bool:
        """匹配 CC 列表条件

        Args:
            feed_message: Feed 消息对象
            condition: 条件值

        Returns:
            True 表示匹配，False 表示不匹配
        """
        # 判断是否会创建 PatchCard（cover letter 或单 patch）
        will_create_patch_card = (
            feed_message.is_cover_letter
            or (feed_message.patch_index is not None and feed_message.patch_index == 0)
            or not (
                feed_message.is_series_patch
                or (feed_message.patch_total and feed_message.patch_total > 1)
            )
        )

        # 对于 cover letter 或单 patch，直接使用当前消息的 URL
        root_url = feed_message.url if will_create_patch_card else None
        email_text = None

        # 对于系列 patch 的子 patch，尝试获取 root patch 的信息
        if not root_url and feed_message.series_message_id:
            # 先尝试从已存在的 root patch card 获取
            if self.patch_card_repo:
                root_patch_card = await self.patch_card_repo.find_by_message_id_header(
                    feed_message.series_message_id
                )
                if root_patch_card and root_patch_card.to_cc_list:
                    email_text = " ".join(root_patch_card.to_cc_list)

            # 如果 patch card 不存在，从 feed_message 查找 root patch 的 URL
            if not email_text:
                if self.feed_message_repo:
                    root_feed_message = (
                        await self.feed_message_repo.find_by_message_id_header(
                            feed_message.series_message_id
                        )
                    )
                    if root_feed_message and root_feed_message.url:
                        root_url = root_feed_message.url
                    else:
                        logger.debug(
                            f"CC filter: root patch feed_message not found for series patch, "
                            f"cannot match CC list: {feed_message.message_id_header}"
                        )
                else:
                    logger.debug(
                        f"CC filter: feed_message_repo not available, "
                        f"cannot match CC list for series patch: {feed_message.message_id_header}"
                    )

        # 如果已经通过 root patch card 获取到了 email_text，直接匹配
        if email_text:
            return self._match_value(email_text, condition)

        # 如果没有 root URL，无法匹配
        if not root_url:
            return False

        # 抓取 To 和 CC 列表
        from ..feed.cc_fetcher import fetch_cc_list_from_url

        to_cc_list = await fetch_cc_list_from_url(root_url)
        if to_cc_list:
            email_text = " ".join(to_cc_list)
            return self._match_value(email_text, condition)

        return False

    async def _match_condition(
        self, feed_message: FeedMessage, filter_type: str, condition
    ) -> bool:
        """检查单个条件是否匹配

        Args:
            feed_message: Feed 消息对象
            filter_type: 过滤类型（author, author_email, subsys, etc.）
            condition: 条件值（字符串、列表或正则）

        Returns:
            True 表示匹配，False 表示不匹配
        """
        # 处理需要特殊逻辑的类型
        if filter_type == "keywords":
            if feed_message.content:
                return self._match_value(feed_message.content, condition)
            return False

        if filter_type in ("cclist", "cc"):
            return await self._match_cc_condition(feed_message, condition)

        # 处理简单的字段匹配类型
        field_value_map = {
            "author": feed_message.author,
            "author_email": feed_message.author_email,
            "subsys": feed_message.subsystem_name,
            "subsystem": feed_message.subsystem_name,
            "subject": feed_message.subject,
        }

        field_value = field_value_map.get(filter_type)
        if field_value is not None:
            return self._match_value(field_value, condition)

        return False

    async def _matches_filter(
        self, feed_message: FeedMessage, _patch_info, filter_data: PatchCardFilterData
    ) -> bool:
        """检查 Feed 消息是否匹配过滤规则

        Args:
            feed_message: Feed 消息对象
            patch_info: PATCH 信息对象
            filter_data: 过滤规则数据

        Returns:
            True 表示匹配，False 表示不匹配
        """
        conditions = filter_data.filter_conditions
        matched = True

        for filter_type, condition in conditions.items():
            if not await self._match_condition(feed_message, filter_type, condition):
                matched = False
                break

        return bool(matched)

    def _merge_list_with_list(self, existing_list: list, new_list: list) -> list:
        """合并两个列表，去重

        Args:
            existing_list: 现有列表
            new_list: 新列表

        Returns:
            合并后的列表
        """
        merged_list = existing_list.copy()
        for nv in new_list:
            normalized_nv = self._normalize_pattern(nv)
            if not any(
                self._normalize_pattern(p) == normalized_nv for p in merged_list
            ):
                merged_list.append(nv)
        return merged_list

    def _merge_single_with_list(self, existing_value, new_list: list) -> list:
        """将单个值与列表合并

        Args:
            existing_value: 现有单个值
            new_list: 新列表

        Returns:
            合并后的列表
        """
        normalized_existing = self._normalize_pattern(existing_value)
        return [existing_value] + [
            nv for nv in new_list if self._normalize_pattern(nv) != normalized_existing
        ]

    def _merge_single_with_single(self, existing_value, new_value):
        """合并两个单个值

        Args:
            existing_value: 现有值
            new_value: 新值

        Returns:
            合并后的值（可能是单个值或列表）
        """
        if self._normalize_pattern(existing_value) != self._normalize_pattern(
            new_value
        ):
            return [existing_value, new_value]
        return existing_value

    def _merge_filter_conditions(
        self, existing_conditions: dict, new_conditions: dict
    ) -> dict:
        """合并过滤条件

        Args:
            existing_conditions: 现有条件
            new_conditions: 新条件

        Returns:
            合并后的条件
        """
        merged_conditions = existing_conditions.copy()

        for filter_type, new_value in new_conditions.items():
            if filter_type in merged_conditions:
                existing_value = merged_conditions[filter_type]
                if isinstance(existing_value, list):
                    if isinstance(new_value, list):
                        merged_conditions[filter_type] = self._merge_list_with_list(
                            existing_value, new_value
                        )
                    else:
                        # 新值是单个值，追加到列表（去重）
                        normalized_new = self._normalize_pattern(new_value)
                        if not any(
                            self._normalize_pattern(p) == normalized_new
                            for p in existing_value
                        ):
                            merged_conditions[filter_type] = existing_value + [
                                new_value
                            ]
                else:
                    if isinstance(new_value, list):
                        merged_conditions[filter_type] = self._merge_single_with_list(
                            existing_value, new_value
                        )
                    else:
                        merged_conditions[filter_type] = self._merge_single_with_single(
                            existing_value, new_value
                        )
            else:
                merged_conditions[filter_type] = new_value

        return merged_conditions

    async def create_filter(
        self,
        name: str,
        filter_conditions: dict,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        enabled: bool = True,
    ) -> PatchCardFilterData:
        """创建或合并过滤规则（同名时合并条件，去重追加）"""
        existing = await self.filter_repo.find_by_name(name)
        if existing:
            merged_conditions = self._merge_filter_conditions(
                existing.filter_conditions, filter_conditions
            )

            data = PatchCardFilterData(
                id=existing.id,
                name=name,
                enabled=enabled,
                filter_conditions=merged_conditions,
                description=(
                    description if description is not None else existing.description
                ),
                created_by=(
                    created_by if created_by is not None else existing.created_by
                ),
            )
            return await self.filter_repo.update(existing.id, data)
        data = PatchCardFilterData(
            id=0,
            name=name,
            enabled=enabled,
            filter_conditions=filter_conditions,
            description=description,
            created_by=created_by,
        )
        return await self.filter_repo.create(data)

    async def list_filters(
        self, enabled_only: bool = False
    ) -> List[PatchCardFilterData]:
        """列出所有过滤规则

        Args:
            enabled_only: 是否只返回启用的规则

        Returns:
            过滤规则列表
        """
        return await self.filter_repo.find_all(enabled_only=enabled_only)

    async def get_filter(
        self, filter_id: Optional[int] = None, name: Optional[str] = None
    ) -> Optional[PatchCardFilterData]:
        """获取过滤规则

        Args:
            filter_id: 过滤规则 ID
            name: 过滤规则名称

        Returns:
            过滤规则数据，如果不存在则返回 None
        """
        if filter_id:
            return await self.filter_repo.find_by_id(filter_id)
        if name:
            return await self.filter_repo.find_by_name(name)
        return None

    async def delete_filter(
        self, filter_id: Optional[int] = None, name: Optional[str] = None
    ) -> bool:
        """删除过滤规则

        Args:
            filter_id: 过滤规则 ID
            name: 过滤规则名称

        Returns:
            是否删除成功
        """
        if name:
            filter_data = await self.filter_repo.find_by_name(name)
            if not filter_data:
                return False
            filter_id = filter_data.id

        if filter_id:
            return await self.filter_repo.delete(filter_id)
        return False

    async def toggle_filter(
        self,
        filter_id: Optional[int] = None,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        """切换过滤规则的启用状态

        Args:
            filter_id: 过滤规则 ID
            name: 过滤规则名称
            enabled: 是否启用（如果为 None，则切换状态）

        Returns:
            是否更新成功
        """
        filter_data = None
        if name:
            filter_data = await self.filter_repo.find_by_name(name)
        elif filter_id:
            filter_data = await self.filter_repo.find_by_id(filter_id)

        if not filter_data:
            return False

        if enabled is None:
            enabled = not filter_data.enabled

        return await self.filter_repo.toggle_enabled(filter_data.id, enabled)

    @staticmethod
    def get_supported_filter_types() -> dict:
        """获取支持的过滤类型列表

        Returns:
            支持的过滤类型字典，key 为类型名称，value 为描述
        """
        return {
            "author": "作者名称（字符串或列表，支持正则）",
            "author_email": "作者邮箱（字符串或列表，支持正则）",
            "subsys | subsystem": "子系统名称（字符串或列表，支持正则）",
            "subject": "主题（字符串或列表，支持正则）",
            "keywords": "内容关键词（字符串或列表，支持正则，从邮件内容中匹配）",
            "cclist | cc": "To/CC 列表（字符串或列表，支持正则，从 root patch 的 To 和 CC 列表中匹配）",
        }

    async def create_rule_group(
        self,
        name: str,
        filter_conditions: dict,
        created_by: Optional[str] = None,
        enabled: bool = True,
    ) -> PatchCardFilterData:
        """创建规则组（就是一个过滤器，组内条件使用 AND 逻辑）

        Args:
            name: 规则组名称
            filter_conditions: 过滤条件字典，key 为过滤类型，value 为模式
            created_by: 创建者
            enabled: 是否启用

        Returns:
            创建的过滤器
        """
        return await self.create_filter(
            name=name,
            filter_conditions=filter_conditions,
            description=None,
            created_by=created_by,
            enabled=enabled,
        )

    async def list_rule_groups(self) -> List[str]:
        """列出所有规则组名称（就是所有过滤器名称）

        Returns:
            规则组名称列表
        """
        filters = await self.filter_repo.find_all()
        return [f.name for f in filters]

    async def get_rule_group(self, name: str) -> Optional[PatchCardFilterData]:
        """获取规则组（就是获取过滤器）

        Args:
            name: 规则组名称

        Returns:
            过滤器数据，如果不存在则返回 None
        """
        return await self.get_filter(name=name)

    async def delete_rule_group(self, name: str) -> bool:
        """删除规则组（就是删除过滤器）

        Args:
            name: 规则组名称

        Returns:
            是否删除成功
        """
        return await self.delete_filter(name=name)

    async def clear_rule_groups(self) -> int:
        """清空所有规则组（就是清空所有过滤器）

        Returns:
            删除的规则组数量
        """
        filters = await self.filter_repo.find_all()
        count = 0
        for filter_data in filters:
            if await self.filter_repo.delete(filter_data.id):
                count += 1
        return count

    async def add_condition_to_rule_group(
        self, name: str, filter_type: str, pattern
    ) -> Optional[PatchCardFilterData]:
        """向规则组的指定类型添加条件值

        Args:
            name: 规则组名称
            filter_type: 过滤类型
            pattern: 要添加的模式值

        Returns:
            更新后的过滤器数据，如果规则组不存在则返回 None
        """
        filter_data = await self.get_filter(name=name)
        if not filter_data:
            return None

        # 浅拷贝条件字典（因为我们总是创建新列表，不会直接修改原列表）
        conditions = filter_data.filter_conditions.copy()

        # 如果类型已存在，将值追加到列表
        if filter_type in conditions:
            existing = conditions[filter_type]
            if isinstance(existing, list):
                # 如果已经是列表，追加新值（如果不存在）
                # 使用规范化后的字符串比较，确保引号处理一致
                normalized_pattern = self._normalize_pattern(pattern)
                pattern_in_list = any(
                    self._normalize_pattern(p) == normalized_pattern for p in existing
                )
                if not pattern_in_list:
                    # 创建新列表，避免修改原始列表引用
                    conditions[filter_type] = existing + [pattern]
                else:
                    # 即使已存在，也返回当前数据（不更新）
                    return filter_data
            else:
                # 如果还不是列表，转为列表
                # 使用规范化后的字符串比较
                normalized_pattern = self._normalize_pattern(pattern)
                if self._normalize_pattern(existing) != normalized_pattern:
                    conditions[filter_type] = [existing, pattern]
                else:
                    # 值已存在，无需修改
                    return filter_data
        else:
            # 类型不存在，直接添加
            conditions[filter_type] = pattern

        # 更新过滤器
        data = PatchCardFilterData(
            id=filter_data.id,
            name=filter_data.name,
            enabled=filter_data.enabled,
            filter_conditions=conditions,
            description=filter_data.description,
            created_by=filter_data.created_by,
        )
        updated_data = await self.filter_repo.update(filter_data.id, data)
        if not updated_data:
            logger.error(f"Failed to update filter '{name}': update returned None")
        return updated_data

    async def remove_types_from_rule_group(
        self, name: str, filter_types: List[str]
    ) -> Optional[PatchCardFilterData]:
        """从规则组删除指定的类型

        Args:
            name: 规则组名称
            filter_types: 要删除的类型列表

        Returns:
            更新后的过滤器数据，如果规则组不存在则返回 None
        """
        filter_data = await self.get_filter(name=name)
        if not filter_data:
            return None

        conditions = filter_data.filter_conditions.copy()

        # 删除指定的类型
        removed_count = 0
        for filter_type in filter_types:
            if filter_type in conditions:
                del conditions[filter_type]
                removed_count += 1

        if removed_count == 0:
            return None

        # 注意：删除类型不应该删除整个规则组，即使条件字典为空
        # 删除整个规则组应该使用 rule del <name> 命令
        # 如果条件为空，保留规则组但条件字典为空（允许用户后续添加条件）

        # 更新过滤器
        data = PatchCardFilterData(
            id=filter_data.id,
            name=filter_data.name,
            enabled=filter_data.enabled,
            filter_conditions=conditions,
            description=filter_data.description,
            created_by=filter_data.created_by,
        )
        return await self.filter_repo.update(filter_data.id, data)

    def _normalize_pattern(self, pattern) -> str:
        """规范化模式值，去除引号以便比较

        Args:
            pattern: 模式值（可能是字符串或其他类型）

        Returns:
            规范化后的字符串（去除首尾引号和空格）
        """
        s = str(pattern).strip()
        # 去除首尾的引号（单引号或双引号）
        if (s.startswith('"') and s.endswith('"')) or (
            s.startswith("'") and s.endswith("'")
        ):
            s = s[1:-1].strip()
        return s

    async def remove_condition_from_rule_group(
        self, name: str, filter_type: str, pattern
    ) -> Optional[PatchCardFilterData]:
        """从规则组的指定类型删除条件值

        Args:
            name: 规则组名称
            filter_type: 过滤类型
            pattern: 要删除的模式值

        Returns:
            更新后的过滤器数据，如果规则组不存在或条件不存在则返回 None
        """
        filter_data = await self.get_filter(name=name)
        if not filter_data:
            return None

        # 浅拷贝条件字典（因为我们总是创建新列表，不会直接修改原列表）
        conditions = filter_data.filter_conditions.copy()

        if filter_type not in conditions:
            return None

        existing = conditions[filter_type]

        # 规范化要删除的模式值
        normalized_pattern = self._normalize_pattern(pattern)

        if isinstance(existing, list):
            # 从列表中删除匹配的值（使用规范化后的字符串比较）
            # 查找匹配的项
            matched_items = [
                x for x in existing if self._normalize_pattern(x) == normalized_pattern
            ]
            if matched_items:
                # 创建新列表，排除匹配的项
                new_list = [
                    x
                    for x in existing
                    if self._normalize_pattern(x) != normalized_pattern
                ]
                if len(new_list) == 0:
                    # 如果列表为空，删除整个类型
                    del conditions[filter_type]
                else:
                    conditions[filter_type] = new_list
            else:
                return None
        else:
            # 单个值，如果匹配则删除整个类型（使用规范化后的字符串比较）
            if self._normalize_pattern(existing) == normalized_pattern:
                del conditions[filter_type]
            else:
                return None

        # 注意：删除条件值不应该删除整个规则组，即使条件字典为空
        # 删除整个规则组应该使用 rule del <name> 命令
        # 如果条件为空，保留规则组但条件字典为空（允许用户后续添加条件）

        # 更新过滤器
        data = PatchCardFilterData(
            id=filter_data.id,
            name=filter_data.name,
            enabled=filter_data.enabled,
            filter_conditions=conditions,
            description=filter_data.description,
            created_by=filter_data.created_by,
        )
        return await self.filter_repo.update(filter_data.id, data)
