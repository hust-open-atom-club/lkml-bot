"""消息分类器

提供标准化的消息类型判断逻辑，在 feed 处理时就确定消息类型。
避免后续重复分析。
"""

import logging
import re
from typing import Optional

from .types import PatchInfo, MessageClassification

logger = logging.getLogger(__name__)


def classify_message(
    subject: str,
    in_reply_to_header: Optional[str],
    message_id_header: Optional[str] = None,
) -> MessageClassification:
    """标准化的消息分类逻辑

    判断规则：
    1. 如果 subject 以 "Re:" 开头，就必然是 REPLY
    2. 其他情况按 PATCH 去识别：
       - 如果识别失败，记录日志
       - 如果识别成功，区分是 Series Patch 还是 Single Patch
       - Series Patch: patch.total > 1
    3. 识别 CoverLetter：
       - 如果是 Series Patch && in_reply_to_header 没有，则是 CoverLetter

    Args:
        subject: 邮件主题
        in_reply_to_header: In-Reply-To 头部值
        message_id_header: Message-ID 头部值（可选，用于系列 PATCH 识别）

    Returns:
        MessageClassification 对象
    """
    classification = MessageClassification()

    # 1. 如果 subject 以 "Re:" 开头，就必然是 REPLY
    subject_lower = subject.lower()
    has_re_prefix = subject_lower.startswith("re:")

    if has_re_prefix:
        classification.is_reply = True
        return classification

    # 2. 其他情况按 PATCH 去识别
    patch_info = parse_patch_subject(subject)
    if not patch_info or not patch_info.is_patch:
        # 识别失败，记录日志
        logger.warning(
            f"Failed to parse PATCH from subject: {subject[:100]}, "
            f"in_reply_to_header={bool(in_reply_to_header)}, "
            f"message_id={message_id_header}"
        )
        # 如果 PATCH 识别失败，不标记为 REPLY，保持 is_patch=False 和 is_reply=False
        return classification

    # 识别成功，设置为 PATCH
    classification.is_patch = True
    classification.patch_info = patch_info

    # 判断是否为 Series Patch（有 x/y 格式的 PATCH）
    if patch_info.total is not None and patch_info.total >= 1:
        classification.is_series_patch = True

        # 区分 Cover Letter 和子 PATCH
        if not in_reply_to_header:
            # 没有 in_reply_to，这是 Cover Letter（0/n）
            patch_info.is_cover_letter = True
            classification.series_message_id = message_id_header
        else:
            # 有 in_reply_to，这是子 PATCH（1/n, 2/n, ...）
            patch_info.is_cover_letter = False
            classification.series_message_id = in_reply_to_header
    else:
        # 没有 x/y 格式，这是独立的 Single PATCH
        classification.is_series_patch = False
        patch_info.is_cover_letter = False

    return classification


def parse_patch_subject(subject: str) -> PatchInfo:
    """解析 PATCH 主题

    支持的格式：
    - [PATCH] xxx
    - [PATCH v5] xxx
    - [PATCH 1/4] xxx
    - [PATCH v5 1/4] xxx
    - [RFC PATCH v2 3/5] xxx

    Args:
        subject: 邮件主题

    Returns:
        PatchInfo 对象
    """
    info = PatchInfo()

    # 检查是否是 PATCH
    subject_lower = subject.lower()
    # 检查是否包含 "patch" 关键字（在方括号中或作为前缀）
    has_patch_keyword = (
        "patch" in subject_lower and "[" in subject_lower  # [xxx PATCH xxx]
    ) or subject_lower.startswith(
        "patch:"
    )  # patch: xxx

    if not has_patch_keyword:
        return info

    info.is_patch = True

    # 提取包含 PATCH 的方括号内容
    # 匹配 [xxx PATCH xxx] 格式，支持多个方括号
    # 例如: [for-linus][PATCH 0/2], [RFC PATCH], [PATCH v5 1/4]
    bracket_match = re.search(r"\[([^\]]*PATCH[^\]]*)\]", subject, re.IGNORECASE)
    if not bracket_match:
        return info

    bracket_content = bracket_match.group(1)

    # 提取版本号 (v1, v2, v3, ...)
    version_match = re.search(r"\bv(\d+)\b", bracket_content, re.IGNORECASE)
    if version_match:
        info.version = f"v{version_match.group(1)}"

    # 提取序号/总数 (1/4, 0/5, ...)
    index_total_match = re.search(r"\b(\d+)/(\d+)\b", bracket_content)
    if index_total_match:
        index = int(index_total_match.group(1))
        total = int(index_total_match.group(2))
        info.index = index
        info.total = total
        info.is_cover_letter = index == 0

    return info
