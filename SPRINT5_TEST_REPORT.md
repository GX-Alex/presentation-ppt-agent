# Sprint 5 测试报告

## 概述
**Sprint 5: 文件上传与解析 + 搜索**  
**状态**: ✅ 全部通过 (52/52)  
**日期**: 2025-01-XX

## 测试结果汇总

| 模块 | 测试数 | 通过 | 状态 |
|------|--------|------|------|
| Sprint 5 依赖检查 | 6 | 6 | ✅ |
| 文件服务 — 安全校验 | 17 | 17 | ✅ |
| ZIP 安全解压 | 1 | 1 | ✅ |
| Tool 自动发现 | 10 | 10 | ✅ |
| parse_document 模块 | 4 | 4 | ✅ |
| parse_project 模块 | 3 | 3 | ✅ |
| read_project_file 模块 | 2 | 2 | ✅ |
| fetch_url + SSRF 防护 | 5 | 5 | ✅ |
| image_search 模块 | 2 | 2 | ✅ |
| Files API 路由 | 1 | 1 | ✅ |
| 前端 TypeScript 编译 | 1 | 1 | ✅ |
| **总计** | **52** | **52** | **✅** |

## 新增文件清单

### 后端 — 服务层
| 文件 | 说明 |
|------|------|
| `app/services/file_service.py` | 文件上传服务：安全校验、磁盘存储、Asset 记录创建、ZIP 安全解压 |

### 后端 — API
| 文件 | 说明 |
|------|------|
| `app/api/files.py` | 重写 — 完整多文件上传 API，含安全校验 |

### 后端 — Tools (5 个新增)
| 文件 | Tool 名称 | 说明 |
|------|-----------|------|
| `app/tools/parse_document.py` | `parse_document` | 文档解析（PDF/DOCX/PPTX/XLSX/TXT/MD/CSV） |
| `app/tools/parse_project.py` | `parse_project` | 项目 ZIP 解析（安全解压+文件树+类型检测） |
| `app/tools/read_project_file.py` | `read_project_file` | 读取解压项目中的单个文件 |
| `app/tools/fetch_url.py` | `fetch_url` | URL 抓取 + SSRF 防护（trafilatura 正文提取） |
| `app/tools/image_search.py` | `image_search` | Pexels API 图片搜索 |

### 前端
| 文件 | 说明 |
|------|------|
| `components/chat/FileUpload.tsx` | 📎 附件上传组件：文件选择、拖拽上传、进度显示 |
| `components/chat/ChatInput.tsx` | 重写 — 集成附件按钮、URL 自动识别、已上传文件指示 |

### 测试
| 文件 | 说明 |
|------|------|
| `quick_test_sprint5.py` | Sprint 5 全流程验证测试脚本 |

## 安全特性

### 文件上传安全校验
- **扩展名白名单**: 32 种允许的文件类型，拒绝 .exe/.bat/.dll/.php 等危险扩展
- **无扩展名拒绝**: 未指定扩展名的文件直接拒绝
- **大小限制**: 50MB 上限
- **文件名清理**: 移除路径穿越字符（`../../`），移除前导点号（`.hidden`）
- **Zip Slip 防护**: ZIP 内条目路径穿越检测（`../../etc/passwd`）

### SSRF 防护
- **协议限制**: 仅允许 http/https
- **私有地址屏蔽**: 10.x / 172.16-31.x / 192.168.x / 127.x / 169.254.x
- **元数据服务屏蔽**: 169.254.169.254 (AWS/GCP/Azure)
- **IPv6 屏蔽**: ::1 回环 / fc00::/7 唯一本地 / fe80::/10 链路本地
- **域名黑名单**: localhost, metadata.google.internal

## Tool 注册验证
自动发现 11 个 Tool（legacy 两个 PPT 工具已删除，主链改为 `generate_ppt_deck`）:
```
edit_slide, fetch_url, generate_ppt_deck, image_search,
load_skill, parse_document, parse_project, read_project_file,
save_to_memory, search_memory, web_search
```

## 前端编译验证
- TypeScript `tsc --noEmit`: ✅ 无错误
- FileUpload 组件: 📎 附件按钮 + 文件数量徽标 + 拖拽覆盖层 + 文件列表面板
- ChatInput 组件: URL 自动识别 + 已上传文件标签 + 附件信息随消息发送
