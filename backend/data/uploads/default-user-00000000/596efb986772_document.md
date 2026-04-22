# PresentationAgent 智能工作区平台
## 技术架构深度分析报告

---

## 一、项目定位

**PresentationAgent** 是一个基于 AI Agent 的智能工作区平台，通过统一的中间件链引擎驱动四大核心能力，为用户提供从需求到产物的全链路智能服务。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户交互层 (Next.js 14)                        │
│     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│     │  Web Deck   │  │   Draw.io    │  │ Web Sandbox  │  │智能文档     ││
│     │  演示文稿    │  │  流程图      │  │  Web 应用    │  │ Markdown    ││
│     └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                         ┌───────────┴───────────┐
                         │   Agent 运行时引擎     │
                         │   中间件链 (14层)     │
                         └───────────┬───────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
            ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
            │  LLM Provider│  │Native Render│  │ State Store │
            │  (litellm)   │  │ (PptxGenJS) │  │  (持久化)   │
            └─────────────┘  └─────────────┘  └─────────────┘
```

---

## 二、核心架构总览

### 2.1 系统技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **前端框架** | Next.js 14 + React 19 | App Router, TypeScript |
| **状态管理** | Zustand 5.0 | deckStore + chatStore |
| **样式方案** | Tailwind CSS 3.4 | 原子化 CSS |
| **后端框架** | FastAPI + SQLAlchemy | 异步非阻塞 |
| **Agent 引擎** | 自研中间件链 | 14 层可插拔 |
| **LLM 集成** | litellm | 多模型统一接口 |
| **通信协议** | WebSocket + REST | 实时 + 轮询 |
| **部署方式** | Docker Compose | 三服务编排 |

### 2.2 微服务架构

```yaml
services:
  # AI 推理服务（内存密集型）
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - NATIVE_RENDERER_URL=http://native-renderer:4100
      - MODEL_CONTEXT_WINDOW=128000
    deploy:
      resources:
        limits:
          memory: 2G

  # 原生渲染服务（CPU 密集型）
  native-renderer:
    build: ./native_renderer
    ports: ["4100:4100"]
    deploy:
      resources:
        limits:
          memory: 512M

  # 前端服务
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on:
      backend:
        condition: service_healthy
```

---

## 三、Agent 运行时引擎

### 3.1 动态 Agent 构建（AgentFactory）

AgentFactory 是整个系统的核心调度器，根据用户意图动态组装 AgentContext：

```python
class AgentFactory:
    def create(
        self,
        task: Task,
        user_message: str,
        session: AsyncSession,
        send_fn: Callable,
        model: str | None = None,
        intent_override: str | None = None,
    ) -> tuple[AgentContext, MiddlewareChain]:
        # 1. 检测意图 (intent)
        # 2. 选择中间件链
        # 3. 组装工具集
        # 4. 定制系统提示词
```

### 3.2 14 层中间件链

中间件链是 Agent 运行时最具扩展性的设计，每层职责单一：

```
┌────────────────────────────────────────────────────────────────┐
│                    Middleware 执行顺序                          │
├──────────┬──────────────────────────────────────┬───────────────┤
│ 层级     │ 中间件名称                            │ 核心功能       │
├──────────┼──────────────────────────────────────┼───────────────┤
│ 1        │ MemoryCaptureMiddleware              │ 记忆检索注入   │
│ 2        │ AttachmentInjectionMiddleware        │ 附件解析      │
│ 3        │ ToolErrorMiddleware                  │ 错误处理      │
│ 4        │ IntentDetectionMiddleware            │ 意图检测      │
│ 5        │ TokenBudgetMiddleware                │ Token 预算    │
│ 6        │ LoopDetectionMiddleware              │ 循环检测      │
│ 7        │ CheckpointMiddleware                 │ 检查点保存    │
│ 8        │ SubagentOrchestrationMiddleware      │ 子Agent编排   │
│ 9        │ BriefEnrichmentMiddleware            │ Brief自动补充 │
│ 10       │ WebDeckContextMiddleware             │ WebDeck上下文 │
│ 11       │ PPTEventMiddleware                   │ PPT专用事件   │
└──────────┴──────────────────────────────────────┴───────────────┘
```

### 3.3 意图系统（Intent Detection）

| 意图 | 触发关键词 | 中间件扩展 | 工具集 |
|------|-----------|-----------|--------|
| `ppt` | PPT、演示、幻灯片 | +PPTEventMiddleware | edit_deck_page, dispatch_subagent |
| `research` | 研究、分析、报告 | - | web_search, fetch_url, parse_document |
| `code_analysis` | 代码、代码审查 | - | parse_document, run_code |
| `chat` | 普通对话 | - | 基本工具 |
| `webpage` | 网页、Web应用 | - | run_code |
| `drawio` | 流程图、架构图 | - | edit_deck_page |
| `document` | 文档、报告 | - | 基本工具 |

### 3.4 工具系统

```python
# 核心工具集（15个）
TOOLS = [
    # 核心编排
    "edit_deck_page",      # 编辑 Web Deck 页面
    "dispatch_subagent",   # 并发分派子 Agent
    "load_skill",           # 加载专业 Skill
    
    # 执行工具
    "run_code",            # 执行代码脚本（Node.js/Python/Shell）
    
    # 信息工具
    "web_search",          # 联网搜索
    "fetch_url",           # 网页抓取
    "parse_document",      # 文档解析（PDF/DOCX/PPTX）
    
    # 资产工具
    "image_search",        # 免费图片搜索（Pexels）
    
    # 记忆工具
    "save_to_memory",      # 长期记忆保存
    "search_memory",       # 长期记忆检索
]
```

---

## 四、智能工作区四大核心能力

### 4.1 Web Deck — 智能演示文稿

Web Deck 是 PresentationAgent 的核心能力，提供从 Brief 到 PPTX 的完整链路。

#### 4.1.1 编排架构（Director-Planner-Scheduler）

```
┌─────────────────────────────────────────────────────────────────┐
│                    WebDeck 编排流程                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   User Brief ──→ ┌─────────┐                                     │
│                  │ Director│ ──→ 创建项目 (status: planning)      │
│                  └────┬────┘                                     │
│                       │                                          │
│                       ▼                                          │
│                  ┌─────────┐     ┌──────────────┐                │
│                  │ Planner │ ──→ │ DeckManifest │                │
│                  └────┬────┘     │ (页面结构定义) │                │
│                       │          └──────────────┘                │
│                       ▼                                          │
│                  ┌──────────────┐                                │
│                  │LaneScheduler │ ──→ 并行调度 Lane              │
│                  └──────┬───────┘                                │
│                         │                                        │
│          ┌──────────────┼──────────────┐                          │
│          ▼              ▼              ▼                          │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐                    │
│   │  narrative│  │   chart   │  │   asset   │  ...              │
│   │   Lane    │  │   Lane    │  │   Lane    │                    │
│   └─────┬─────┘  └─────┬─────┘  └─────┬─────┘                    │
│         └──────────────┴──────────────┘                          │
│                         │                                        │
│                         ▼                                        │
│                  ┌─────────────┐                                  │
│                  │  Reviewer   │ ──→ 页级质检                     │
│                  └──────┬──────┘                                  │
│                         │                                        │
│                         ▼                                        │
│                  Deck HTML ──→ Native Renderer ──→ PPTX           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 4.1.2 状态机（DeckStatus）

```typescript
enum DeckStatus {
  draft = "draft",           // 草稿
  planning = "planning",      // 规划中
  plan_ready = "plan_ready",  // 规划就绪（待用户确认）
  generating = "generating",   // 生成中
  reviewing = "reviewing",     // 审核中
  completed = "completed",   // 完成
  failed = "failed"           // 失败
}
```

#### 4.1.3 双渲染引擎

```
┌─────────────────────────────────────────────────────────┐
│                   Dual Render Pipeline                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   HTML 语义分析                                          │
│   ┌─────────────────────────────────────────────────┐  │
│   │  识别布局类型: card / two-column / table / ...  │  │
│   └─────────────────────────────────────────────────┘  │
│                       │                                 │
│                       ▼                                 │
│   ┌─────────────────────┐                             │
│   │    DeckSpec 规范     │                             │
│   │ {layout, elements}   │                             │
│   └─────────────────────┘                             │
│                       │                                 │
│         ┌─────────────┴─────────────┐                 │
│         ▼                           ▼                 │
│   ┌──────────────┐          ┌──────────────┐          │
│   │  Web Deck   │          │  PPTX        │          │
│   │  HTML/CSS   │          │  PptxGenJS   │          │
│   │  实时预览    │          │  可下载文件   │          │
│   └──────────────┘          └──────────────┘          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

#### 4.1.4 前端组件架构

```typescript
// deckStore - 状态管理
interface DeckStore {
  projectId: string | null;
  manifest: DeckManifest | null;
  deckStatus: DeckStatus;
  pages: DeckPageData[];
  currentPageIndex: number;
  // ...
}

// 核心组件
components/webdeck/
├── DeckViewer.tsx        // 主查看器（状态驱动 UI）
├── DeckPagePreview.tsx  // 页面预览（HTML 渲染 + 导航）
├── DeckBriefForm.tsx    // Brief 表单
├── DeckTocPanel.tsx     // 目录面板
└── DeckLanePanel.tsx    // Lane 进度
```

---

### 4.2 Draw.io — 流程图与架构图

Draw.io 集成提供交互式图表编辑能力。

#### 4.2.1 嵌入模式实现

```typescript
export function DrawIoViewer({ embedded = false }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  
  // 使用 draw.io embed URL
  const drawIoUrl = useMemo(() => getDrawIoEmbedUrl(), []);
  
  // 消息通信协议
  const handleMessage = (e: MessageEvent) => {
    const msg = parseDrawIoMessage(e.data);
    
    if (msg.event === "init") {
      // 初始化完成，加载 XML
      iframeRef.current?.contentWindow?.postMessage({
        action: "load",
        xml: artifactContent || BLANK_XML
      }, "*");
    }
    
    if (msg.event === "autosave" || msg.event === "save") {
      // 自动保存 / 用户保存
      setArtifactContent(msg.xml);
    }
  };
  
  return (
    <iframe
      ref={iframeRef}
      src={drawIoUrl}
      postMessage={{ action: "configure", config: { compressXml: false } }}
    />
  );
}
```

#### 4.2.2 消息协议

| 事件 | 方向 | 说明 |
|------|------|------|
| `configure` | Iframe → React | 初始化配置请求 |
| `init` | Iframe → React | 编辑器就绪 |
| `autosave` | Iframe → React | 自动保存 XML |
| `save` | Iframe → React | 用户手动保存 |
| `exit` | Iframe → React | 用户退出编辑器 |
| `load` | React → Iframe | 加载 XML 内容 |
| `status` | React → Iframe | 状态反馈 |

#### 4.2.3 XML 数据格式

```xml
<mxfile>
  <diagram id="blank" name="Page-1">
    <mxGraphModel 
      dx="1000" dy="1000" 
      grid="1" gridSize="10"
      pageScale="1" pageWidth="827" pageHeight="1169">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- 图表内容 -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

---

### 4.3 Web Sandbox — Web 应用预览

Web Sandbox 提供即时的 Web 应用预览能力，支持 HTML/CSS/JS 混合代码。

#### 4.3.1 沙盒实现

```typescript
export function WebSandboxViewer() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  
  // 优先使用 htmlArtifactContent（跨复合任务保留）
  const htmlArtifactContent = useChatStore((s) => s.htmlArtifactContent);
  const artifactContent = useChatStore((s) => s.artifactContent);
  const content = htmlArtifactContent || artifactContent;
  
  // 代码变更时触发重新渲染
  useEffect(() => {
    setRenderCounter((c) => c + 1);
  }, [content]);
  
  return (
    <div className="browser-chrome">
      {/* 浏览器导航条模拟 */}
      <div className="nav-bar">
        <div className="traffic-lights" />
        <div className="address-bar">localhost:3000 / Web 沙盒预览</div>
        <button onClick={() => setRenderCounter(c => c + 1)}>刷新</button>
      </div>
      
      <iframe
        key={renderCounter}  // 强制完全重新加载
        ref={iframeRef}
        srcDoc={htmlContent}
        sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
        title="Web Sandbox"
      />
    </div>
  );
}
```

#### 4.3.2 安全策略

```html
<sandbox="
  allow-scripts      -- 允许执行 JavaScript
  allow-forms        -- 允许表单提交
  allow-same-origin  -- 允许同源请求
  allow-popups       -- 允许弹出窗口
">
```

#### 4.3.3 渲染流程

```
用户输入需求
     │
     ▼
Agent 生成 HTML/JS/CSS 代码
     │
     ▼
生成 <general-artifact type="webpage">
     │
     ▼
WebSandboxViewer 解析 artifact
     │
     ▼
iframe srcDoc 注入代码
     │
     ▼
沙盒环境渲染预览
```

---

### 4.4 智能文档 — Markdown 渲染

智能文档支持 Markdown 渲染，适合生成研究报告、技术文档等。

#### 4.4.1 文档渲染实现

```typescript
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function DocumentViewer() {
  const artifactContent = useChatStore((s) => s.artifactContent);
  
  return (
    <div className="prose prose-slate max-w-none">
      <ReactMarkdown 
        remarkPlugins={[remarkGfm]}
        components={{
          // 自定义渲染规则
          h1: ({ children }) => <h1 className="text-3xl font-bold">{children}</h1>,
          code: ({ children }) => <code className="bg-gray-100 rounded px-1">{children}</code>,
        }}
      >
        {artifactContent}
      </ReactMarkdown>
    </div>
  );
}
```

#### 4.4.2 支持的 Markdown 特性

| 特性 | 说明 |
|------|------|
| GFM 表格 | 支持 GitHub Flavored Markdown 表格 |
| 代码块 | 语法高亮支持 |
| 任务列表 | - [ ] 待办项 |
| 链接/图片 | 自动转换 |
| 脚注 | GFM 脚注语法 |

---

## 五、工作区状态管理

### 5.1 chatStore — 统一状态管理

```typescript
interface ChatStore {
  // 当前 Artifact 类型
  currentArtifactType: ArtifactType;
  
  // 产物内容
  artifactContent: string;        // 主产物
  htmlArtifactContent: string;    // HTML 产物（跨复合任务保留）
  
  // 对话历史
  messages: Message[];
  
  // 处理状态
  isProcessing: boolean;
  tokenCount: number;
  
  // Actions
  setCurrentArtifactType: (type: ArtifactType) => void;
  setArtifactContent: (content: string) => void;
  appendMessage: (msg: Message) => void;
}
```

### 5.2 Artifact 类型映射

```typescript
type ArtifactType = 
  | "webdeck"   // 演示文稿
  | "ppt"       // PPT 预览
  | "drawio"    // 流程图
  | "webpage"   // Web 页面
  | "document"  // 文档
  | "code";     // 代码
```

### 5.3 WorkspacePanel — 工作区主面板

```typescript
export function WorkspacePanel() {
  const currentArtifactType = useChatStore((s) => s.currentArtifactType);

  return (
    <>
      {currentArtifactType === "drawio" && <DrawIoViewer embedded />}
      {currentArtifactType === "ppt" && <PptViewer />}
      {currentArtifactType === "code" && <CodeViewer />}
      {currentArtifactType === "document" && <DocumentViewer />}
      {currentArtifactType === "webpage" && <WebSandboxViewer />}
      {currentArtifactType === "webdeck" && <DeckViewer />}
    </>
  );
}
```

---

## 六、产物生成协议

### 6.1 Artifact 标签格式

AI Agent 通过输出特定标签声明产物类型：

```
<general-artifact type="webpage">
<!DOCTYPE html>
<html>
  <head>...</head>
  <body>...</body>
</html>