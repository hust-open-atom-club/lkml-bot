"""Thread 内容处理和回复层级构建模块（内部模块）

提供邮件内容清理、提取、回复层级构建、PATCH 分类、系列查询、订阅辅助等功能。
这些功能是 lkml 域的核心功能，不依赖于任何特定的渲染平台。

注意：此模块不应被外部直接使用。请使用 lkml.service.thread_service 来访问这些功能。
"""

# 内部模块，不对外暴露
# 所有功能应通过 lkml.service.thread_service 访问

__all__ = []
