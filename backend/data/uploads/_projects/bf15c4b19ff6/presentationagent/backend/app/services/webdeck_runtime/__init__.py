"""
Web Deck Orchestration Runtime — 独立于 agent_loop 的页级编排运行时。
负责 deck 级规划、页面级任务编排、子资产编排、多 lane 执行、评审与回退、实时状态推送。

架构参考: high.md §5 / claw-code registry-based lane 模式
"""
