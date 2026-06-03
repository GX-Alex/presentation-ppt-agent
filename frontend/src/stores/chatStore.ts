/**
 * 聊天状态管理 — Zustand 全局 Store。
 * 所有 WebSocket 消息统一写入 Store，UI 组件纯消费只读状态。
 * Sprint 2: PPT 大纲、幻灯片、预览状态管理。
 * Sprint 3: WYSIWYG 编辑、版本历史、导出状态管理。
 */
import { create } from "zustand";

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  type?: string; // text | thinking | plan | slide | status | error | outline
  artifactType?: string; // drawio | document | webpage | code — persisted artifact type for chip display
  timestamp: number;
}

// ── SubAgent 执行状态 ──────────────────────────────────
export type StepStatus = "pending" | "running" | "completed" | "failed";

export interface ExecutionStep {
  id: string;
  type: "thinking" | "tool_call" | "subagent_dispatch" | "content" | "status";
  status: StepStatus;
  title: string;
  content?: string;
  toolName?: string;
  startTime?: number;
  duration?: number;
  subAgents?: SubAgentState[];
}

export interface SubAgentState {
  agentId: string;
  agentType: string;
  task: string;
  status: StepStatus;
  currentRound: number;
  maxRounds: number;
  steps: ExecutionStep[];
  result?: string;
  duration?: number;
}

export type ConnectionStatus = "disconnected" | "connecting" | "connected";

export type PptState =
  | "idle"
  | "outline_pending"
  | "outline_ready"
  | "generating"
  | "completed"
  | "editing";

/** 大纲中单页的数据 */
export interface ChartPlan {
  needed: boolean;
  chart_type: string;
  title?: string;
  data_fields: string[];
  insight: string;
}

export interface EvidenceSource {
  material_id: string;
  label: string;
  source_type: string;
  url?: string;
  excerpt?: string;
  error?: string;
}

export interface SlideMetadata {
  section_role: "main" | "appendix";
  is_appendix: boolean;
  core_conclusion: string;
  chart_plan: ChartPlan;
  evidence_refs: string[];
  evidence_sources?: EvidenceSource[];
}

export interface OutlineItem {
  index: number;
  title: string;
  type: string;
  bullets: string[];
  metadata?: SlideMetadata;
  speaker_notes: string;
}

/** 已生成的幻灯片数据 */
export interface SlideData {
  id?: string; // 数据库中的 slide_id（WYSIWYG 保存时使用）
  index: number;
  html: string;
  metadata?: SlideMetadata;
  speaker_notes: string;
}

/** 版本记录 */
export interface SlideVersion {
  id: string;
  version: number;
  html: string;
  source: string; // wysiwyg | ai | fork
  created_at: string;
}

/** 导出状态 */
export type ExportStatus = "idle" | "exporting" | "done" | "error";

/** 广义工件类型 */
export type ArtifactType = "none" | "ppt" | "drawio" | "document" | "webpage" | "code" | "webdeck";

export interface ArtifactData {
  id: string;
  type: ArtifactType;
  title: string;
  content: string; // 具体类型的数据 (HTML/XML/Markdown)
}

/** Sprint 4: Token 用量信息 */
export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  contextWindow: number;
  usageRatio: number;
  alert: boolean;
  alertMessage: string;
}

/** Sprint 4: 记忆捕获事件 */
export interface MemoryCaptured {
  category: string;
  action: string;
  content: string;
  timestamp: number;
}

interface ChatStore {
  // ── 流式输出 (Streaming) ──
  streamingMessage: ChatMessage | null;
  startStream: (taskId: string) => void;
  appendStreamContent: (delta: string) => void;
  finalizeStream: (messageId: string, fullContent: string, tokenUsage?: { prompt: number; completion: number; total: number }, artifactType?: string) => void;
  cancelStream: () => void;

  // ── 通用工件区 (Artifact) ──
  currentArtifactType: ArtifactType;
  setCurrentArtifactType: (type: ArtifactType) => void;
  artifactContent: string | null;
  setArtifactContent: (content: string | null) => void;
  // HTML 产物单独保留，复合任务中被其他产物覆盖后仍可下载
  htmlArtifactContent: string | null;
  setHtmlArtifactContent: (content: string | null) => void;

  // 连接状态
  connectionStatus: ConnectionStatus;
  setConnectionStatus: (status: ConnectionStatus) => void;

  // 处理中状态（agent_loop 正在运行时为 true）
  isProcessing: boolean;
  setIsProcessing: (v: boolean) => void;
  processingTaskIds: string[];
  startTaskProcessing: (taskId: string) => void;
  finishTaskProcessing: (taskId: string) => void;

  // 当前任务
  taskId: string | null;
  intent: string | null;
  setTask: (taskId: string, intent?: string) => void;

  // 消息列表
  messages: ChatMessage[];
  addMessage: (msg: ChatMessage) => void;
  clearMessages: () => void;
  /** 从服务端历史消息批量加载（用于刷新恢复） */
  loadMessages: (msgs: ChatMessage[]) => void;

  // PPT 状态机
  pptState: PptState;
  currentPage: number;
  totalPages: number;
  setPptState: (state: PptState) => void;
  setGeneratingProgress: (current: number, total: number) => void;

  // PPT 数据 (Sprint 2 新增)
  presentationId: string | null;
  presentationTitle: string | null;
  themeId: string;
  outline: OutlineItem[];
  slides: SlideData[];
  currentSlideIndex: number;

  /** 设置大纲数据（收到 outline 事件时调用） */
  setOutline: (data: {
    presentationId: string;
    title: string;
    themeId: string;
    outline: OutlineItem[];
  }) => void;
  /** 添加单页幻灯片（收到 slide_ready 事件时逐页调用） */
  addSlide: (slide: SlideData) => void;
  /** 批量设置幻灯片（恢复数据时使用） */
  setSlides: (slides: SlideData[]) => void;
  /** 设置当前预览的幻灯片索引 */
  setCurrentSlideIndex: (index: number) => void;
  /** 重置 PPT 相关状态 */
  resetPpt: () => void;

  // ── Sprint 3: 编辑 + 版本 + 导出 ──

  /** 是否处于编辑模式 */
  isEditing: boolean;
  setIsEditing: (editing: boolean) => void;
  /** 更新当前幻灯片 HTML（WYSIWYG 保存后刷新 store） */
  updateSlideHtml: (index: number, html: string) => void;
  /** 撤销栈（存储当前幻灯片的 HTML 快照） */
  undoStack: string[];
  redoStack: string[];
  pushUndo: (html: string) => void;
  undo: () => void;
  redo: () => void;
  clearUndoRedo: () => void;
  /** 版本历史 */
  slideVersions: SlideVersion[];
  setSlideVersions: (versions: SlideVersion[]) => void;
  /** 版本面板可见性 */
  showVersionPanel: boolean;
  setShowVersionPanel: (show: boolean) => void;
  /** 导出状态 */
  exportStatus: ExportStatus;
  exportFormat: string | null;
  setExportStatus: (status: ExportStatus, format?: string) => void;

  // ── Sprint 4: Skill + 记忆 + Token 监控 ──

  /** 开发者模式 */
  devMode: boolean;
  setDevMode: (on: boolean) => void;
  /** Token 用量 */
  tokenUsage: TokenUsage | null;
  setTokenUsage: (usage: TokenUsage) => void;
  /** 记忆自动捕获记录 */
  memoryCaptured: MemoryCaptured[];
  addMemoryCaptured: (mem: MemoryCaptured) => void;
  /** 活跃 Skill 名称列表 */
  activeSkills: string[];
  addActiveSkill: (name: string) => void;
  removeActiveSkill: (name: string) => void;
  /** 记忆数量 */
  memoryCount: number;
  setMemoryCount: (count: number) => void;

  // ── SubAgent 执行步骤 ──
  executionSteps: ExecutionStep[];
  addExecutionStep: (step: ExecutionStep) => void;
  updateExecutionStep: (id: string, updates: Partial<ExecutionStep>) => void;
  clearExecutionSteps: () => void;
  addSubAgentToStep: (stepId: string, subAgent: SubAgentState) => void;
  updateSubAgent: (agentId: string, updates: Partial<SubAgentState>) => void;
  bulkCompleteExecutionSteps: () => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  // ── 流式输出 (Streaming) ──
  streamingMessage: null,
  startStream: (taskId) =>
    set({
      streamingMessage: {
        id: `streaming-${taskId}`,
        role: "assistant",
        content: "",
        type: "text",
        timestamp: Date.now(),
      },
    }),
  appendStreamContent: (delta) =>
    set((state) => {
      if (!state.streamingMessage) return state;
      return {
        streamingMessage: {
          ...state.streamingMessage,
          content: state.streamingMessage.content + delta,
        },
      };
    }),
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  finalizeStream: (messageId, fullContent, _tokenUsage, artifactType) =>
    set((state) => {
      if (!state.streamingMessage) return state;
      const finalMsg: ChatMessage = {
        id: messageId || state.streamingMessage.id,
        role: "assistant",
        content: fullContent,
        type: "text",
        artifactType,
        timestamp: state.streamingMessage.timestamp,
      };
      return {
        streamingMessage: null,
        messages: [...state.messages, finalMsg],
      };
    }),
  cancelStream: () => set({ streamingMessage: null }),

  // ── 通用工件区 (Artifact) ──
  currentArtifactType: "none", // 默认为空，展示工作区就绪
  setCurrentArtifactType: (type) => set({ currentArtifactType: type }),
  artifactContent: null,
  setArtifactContent: (content) => set({ artifactContent: content }),
  htmlArtifactContent: null,
  setHtmlArtifactContent: (content) => set({ htmlArtifactContent: content }),

  // 连接状态
  connectionStatus: "disconnected",
  setConnectionStatus: (status) => set({ connectionStatus: status }),

  // 处理中状态
  isProcessing: false,
  setIsProcessing: (v) => set({ isProcessing: v }),
  processingTaskIds: [],
  startTaskProcessing: (taskId) =>
    set((state) => {
      const processingTaskIds = state.processingTaskIds.includes(taskId)
        ? state.processingTaskIds
        : [...state.processingTaskIds, taskId];
      return {
        processingTaskIds,
        isProcessing: state.taskId === taskId ? true : state.isProcessing,
      };
    }),
  finishTaskProcessing: (taskId) =>
    set((state) => {
      const processingTaskIds = state.processingTaskIds.filter((id) => id !== taskId);
      return {
        processingTaskIds,
        isProcessing: state.taskId === taskId ? false : state.isProcessing,
      };
    }),

  // 当前任务
  taskId: null,
  intent: null,
  setTask: (taskId, intent) =>
    set((state) => ({
      taskId,
      intent: intent ?? (state.taskId === taskId ? state.intent : null),
      isProcessing: state.processingTaskIds.includes(taskId),
    })),

  // 消息列表
  messages: [],
  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),
  clearMessages: () => set({ messages: [], htmlArtifactContent: null }),
  loadMessages: (msgs) => {
    // 从历史记录重建 executionSteps，避免刷新后执行记录丢失
    const steps: ExecutionStep[] = [];
    const displayMessages: ChatMessage[] = [];
    for (const msg of msgs) {
      if (msg.type === "tool_calls" && msg.role === "assistant") {
        try {
          const data = JSON.parse(msg.content) as {
            tool_calls?: Array<{ id: string; name: string; input?: unknown }>;
            text?: string;
          };
          const toolCalls = data.tool_calls || [];
          if (toolCalls.length > 0) {
            const names = toolCalls.map((tc) => tc.name).join(", ");
            steps.push({
              id: msg.id,
              type: toolCalls.some((tc) => tc.name === "dispatch_subagent")
                ? "subagent_dispatch"
                : "tool_call",
              status: "completed",
              title: names,
              toolName: toolCalls[0]?.name,
              startTime: msg.timestamp,
            });
          }
        } catch {
          // 解析失败跳过
        }
        // tool_calls 记录不进主消息列表
      } else {
        displayMessages.push(msg);
      }
    }
    set({ messages: displayMessages, executionSteps: steps });
  },

  // PPT 状态机
  pptState: "idle",
  currentPage: 0,
  totalPages: 0,
  setPptState: (pptState) => set({ pptState }),
  setGeneratingProgress: (current, total) =>
    set({ currentPage: current, totalPages: total, pptState: "generating" }),

  // PPT 数据 (Sprint 2 新增)
  presentationId: null,
  presentationTitle: null,
  themeId: "tech_dark",
  outline: [],
  slides: [],
  currentSlideIndex: 0,

  setOutline: (data) =>
    set({
      presentationId: data.presentationId,
      presentationTitle: data.title,
      themeId: data.themeId,
      outline: data.outline,
      totalPages: data.outline.length,
      pptState: "outline_ready",
    }),

  addSlide: (slide) =>
    set((state) => {
      const exists = state.slides.find((s) => s.index === slide.index);
      const newSlides = exists
        ? state.slides.map((s) =>
            s.index === slide.index
              ? {
                  ...s,
                  ...slide,
                  metadata: slide.metadata || s.metadata,
                }
              : s
          )
        : [...state.slides, slide].sort((a, b) => a.index - b.index);
      return { slides: newSlides };
    }),

  setSlides: (slides) => set({ slides }),

  setCurrentSlideIndex: (index) => set({ currentSlideIndex: index }),

  resetPpt: () =>
    set({
      pptState: "idle",
      presentationId: null,
      presentationTitle: null,
      themeId: "tech_dark",
      outline: [],
      slides: [],
      currentPage: 0,
      totalPages: 0,
      currentSlideIndex: 0,
      isEditing: false,
      undoStack: [],
      redoStack: [],
      slideVersions: [],
      showVersionPanel: false,
      exportStatus: "idle",
      exportFormat: null,
    }),

  // ── Sprint 3: 编辑 + 版本 + 导出 ──
  isEditing: false,
  setIsEditing: (editing) => set({ isEditing: editing }),

  updateSlideHtml: (index, html) =>
    set((state) => ({
      slides: state.slides.map((s) =>
        s.index === index ? { ...s, html } : s
      ),
    })),

  undoStack: [],
  redoStack: [],

  pushUndo: (html) =>
    set((state) => ({
      undoStack: [...state.undoStack.slice(-49), html], // 最多保留 50 步
      redoStack: [], // 新操作清除 redo
    })),

  undo: () =>
    set((state) => {
      if (state.undoStack.length === 0) return state;
      const previous = state.undoStack[state.undoStack.length - 1];
      const currentSlide = state.slides[state.currentSlideIndex];
      if (!currentSlide) return state;
      return {
        undoStack: state.undoStack.slice(0, -1),
        redoStack: [...state.redoStack, currentSlide.html],
        slides: state.slides.map((s) =>
          s.index === state.currentSlideIndex ? { ...s, html: previous } : s
        ),
      };
    }),

  redo: () =>
    set((state) => {
      if (state.redoStack.length === 0) return state;
      const next = state.redoStack[state.redoStack.length - 1];
      const currentSlide = state.slides[state.currentSlideIndex];
      if (!currentSlide) return state;
      return {
        redoStack: state.redoStack.slice(0, -1),
        undoStack: [...state.undoStack, currentSlide.html],
        slides: state.slides.map((s) =>
          s.index === state.currentSlideIndex ? { ...s, html: next } : s
        ),
      };
    }),

  clearUndoRedo: () => set({ undoStack: [], redoStack: [] }),

  slideVersions: [],
  setSlideVersions: (versions) => set({ slideVersions: versions }),

  showVersionPanel: false,
  setShowVersionPanel: (show) => set({ showVersionPanel: show }),

  exportStatus: "idle",
  exportFormat: null,
  setExportStatus: (status, format) =>
    set({ exportStatus: status, exportFormat: format || null }),

  // ── Sprint 4: Skill + 记忆 + Token 监控 ──
  devMode: false,
  setDevMode: (on) => set({ devMode: on }),

  tokenUsage: null,
  setTokenUsage: (usage) => set({ tokenUsage: usage }),

  memoryCaptured: [],
  addMemoryCaptured: (mem) =>
    set((state) => ({
      memoryCaptured: [...state.memoryCaptured.slice(-49), mem],
    })),

  activeSkills: [],
  addActiveSkill: (name) =>
    set((state) => ({
      activeSkills: state.activeSkills.includes(name)
        ? state.activeSkills
        : [...state.activeSkills, name],
    })),
  removeActiveSkill: (name) =>
    set((state) => ({
      activeSkills: state.activeSkills.filter((s) => s !== name),
    })),

  memoryCount: 0,
  setMemoryCount: (count) => set({ memoryCount: count }),

  // ── SubAgent 执行步骤 ──
  executionSteps: [],
  addExecutionStep: (step) =>
    set((state) => ({
      executionSteps: [...state.executionSteps, step],
    })),
  updateExecutionStep: (id, updates) =>
    set((state) => ({
      executionSteps: state.executionSteps.map((s) =>
        s.id === id ? { ...s, ...updates } : s
      ),
    })),
  clearExecutionSteps: () => set({ executionSteps: [] }),
  addSubAgentToStep: (stepId, subAgent) =>
    set((state) => {
      // 找到最近的 subagent_dispatch 步骤，或创建一个新的
      let found = false;
      const updated = state.executionSteps.map((s) => {
        if (s.id === stepId || (!found && s.type === "subagent_dispatch" && s.status === "running")) {
          found = true;
          return {
            ...s,
            subAgents: [...(s.subAgents || []), subAgent],
          };
        }
        return s;
      });
      if (!found) {
        // 没有找到匹配的步骤，创建一个新的 dispatch 步骤
        updated.push({
          id: `dispatch-${Date.now()}`,
          type: "subagent_dispatch",
          status: "running",
          title: "子 Agent 调度",
          startTime: Date.now(),
          subAgents: [subAgent],
        });
      }
      return { executionSteps: updated };
    }),
  updateSubAgent: (agentId, updates) =>
    set((state) => ({
      executionSteps: state.executionSteps.map((step) => {
        if (!step.subAgents) return step;
        const hasAgent = step.subAgents.some((sa) => sa.agentId === agentId);
        if (!hasAgent) return step;
        return {
          ...step,
          subAgents: step.subAgents.map((sa) =>
            sa.agentId === agentId ? { ...sa, ...updates } : sa
          ),
        };
      }),
    })),
  bulkCompleteExecutionSteps: () => {
    const now = Date.now();
    return set((state) => ({
      executionSteps: state.executionSteps.map((s) =>
        s.status === "running" || s.status === "pending"
          ? { ...s, status: "completed" as const, duration: now - (s.startTime || now) }
          : s
      ),
    }));
  },
}));
