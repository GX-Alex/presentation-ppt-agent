# Project Instructions

## 代码修改后必须执行 Code Review

每次完成一批代码修改后，**必须**使用 `superpowers:code-reviewer` 进行代码审查，然后根据反馈修复所有 Critical 和 Important 级别的问题，再汇报完成。

**触发时机：**
- 完成一个 Bug 修复任务后
- 完成一个功能特性后
- 完成重构或较大范围的改动后
- 在向 main 分支合并前

**流程：**
1. 完成代码修改
2. 调用 `superpowers:code-reviewer` skill 进行审查（中文回复）
3. 修复所有 Critical 问题（必须）和 Important 问题（应当）
4. Minor 问题记录备注，可延后处理
5. 确认修复完成后汇报结果
