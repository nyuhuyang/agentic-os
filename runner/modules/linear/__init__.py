"""Linear 集成模块 + 本地任务跟踪降级方案。

当 LINEAR_API_KEY 可用时，该模块连接到 Linear GraphQL API。
当不可用时，自动降级到本地 `state/tasks.json` 文件跟踪。

模块名: "linear"
"""
