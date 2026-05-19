/**
 * Settings page — 模型配置、记忆管理、开发者模式。
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import { useChatStore } from "@/stores/chatStore";
import { Eye, EyeOff, Save, Check, AlertCircle, Cpu, Brain, Code2 } from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

type Tab = "model" | "memory" | "developer";

type MemorySettings = {
  enabled: boolean;
  auto_capture: {
    preference: boolean;
    instruction: boolean;
    fact: boolean;
    feedback: boolean;
  };
};

type MemoryItem = {
  id: string;
  category: "preference" | "fact" | "instruction" | "feedback";
  content: string;
  confidence: number;
  source: string;
  created_at?: string | null;
};

type LLMConfig = {
  provider: string;
  base_url: string;
  model: string;
  api_key_masked: string;
  has_api_key: boolean;
  is_reasoning_model: boolean;
};

// ─── Provider presets ─────────────────────────────────────────────────────────

const PROVIDERS = [
  {
    id: "deepseek",
    name: "DeepSeek",
    abbr: "DS",
    color: "#4D6BFE",
    bg: "#EEF1FF",
    baseUrl: "https://api.deepseek.com",
    models: ["deepseek-chat", "deepseek-v4-pro", "deepseek-reasoner"],
    keyPlaceholder: "sk-xxxxxxxxxxxxxxxxxxxxxxxx",
  },
  {
    id: "openai",
    name: "OpenAI",
    abbr: "OA",
    color: "#10A37F",
    bg: "#E6F7F3",
    baseUrl: "https://api.openai.com/v1",
    models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    keyPlaceholder: "sk-proj-xxxxxxxxxxxxxxxxxxxxxxxx",
  },
  {
    id: "anthropic",
    name: "Anthropic",
    abbr: "AN",
    color: "#D97757",
    bg: "#FDF2EE",
    baseUrl: "https://api.anthropic.com",
    models: ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    keyPlaceholder: "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx",
  },
  {
    id: "minimax",
    name: "MiniMax",
    abbr: "MM",
    color: "#8B5CF6",
    bg: "#F3F0FF",
    baseUrl: "https://api.minimaxi.com/v1",
    models: ["MiniMax-M2.5", "minimax/MiniMax-M2.7"],
    keyPlaceholder: "xxxxxxxxxxxxxxxxxxxxxxxx",
  },
  {
    id: "groq",
    name: "Groq",
    abbr: "GQ",
    color: "#F59E0B",
    bg: "#FFF8E6",
    baseUrl: "https://api.groq.com/openai/v1",
    models: ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    keyPlaceholder: "gsk_xxxxxxxxxxxxxxxxxxxxxxxx",
  },
  {
    id: "custom",
    name: "自定义",
    abbr: "⚙",
    color: "#6B7280",
    bg: "#F3F4F6",
    baseUrl: "",
    models: [],
    keyPlaceholder: "your-api-key",
  },
] as const;

type ProviderId = (typeof PROVIDERS)[number]["id"];

// ─── Main Component ───────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { devMode, setDevMode, memoryCount, tokenUsage, setMemoryCount } = useChatStore();
  const [activeTab, setActiveTab] = useState<Tab>("model");

  // ── LLM Config state ──
  const [provider, setProvider] = useState<ProviderId | "">("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiKeyMasked, setApiKeyMasked] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [configLoading, setConfigLoading] = useState(true);
  const [configSaving, setConfigSaving] = useState(false);
  const [configStatus, setConfigStatus] = useState<"idle" | "saved" | "error">("idle");
  const [isReasoningModel, setIsReasoningModel] = useState(false);

  // ── Memory state ──
  const [memorySettings, setMemorySettings] = useState<MemorySettings>({
    enabled: true,
    auto_capture: { preference: true, instruction: true, fact: false, feedback: false },
  });
  const [memoryLoading, setMemoryLoading] = useState(true);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memoryNotice, setMemoryNotice] = useState("");
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(true);
  const [newMemoryCategory, setNewMemoryCategory] = useState<MemoryItem["category"]>("preference");
  const [newMemoryContent, setNewMemoryContent] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingCategory, setEditingCategory] = useState<MemoryItem["category"]>("preference");
  const [editingContent, setEditingContent] = useState("");

  // ── Load LLM config on mount ──
  useEffect(() => {
    const load = async () => {
      try {
        const resp = await fetch("/api/llm-config");
        if (!resp.ok) return;
        const data: LLMConfig = await resp.json();
        setProvider((data.provider as ProviderId) || "");
        setBaseUrl(data.base_url || "");
        setModelName(data.model || "");
        setApiKeyMasked(data.api_key_masked || "");
        setHasApiKey(data.has_api_key);
        setIsReasoningModel(data.is_reasoning_model ?? false);
      } catch {
        // silently fall back to env-var config
      } finally {
        setConfigLoading(false);
      }
    };
    void load();
  }, []);

  // ── Load memory settings on mount ──
  useEffect(() => {
    const load = async () => {
      try {
        const resp = await fetch("/api/memory/settings");
        if (!resp.ok) throw new Error();
        const data = await resp.json();
        if (data.settings) {
          setMemorySettings((prev) => ({
            ...prev,
            ...data.settings,
            auto_capture: { ...prev.auto_capture, ...(data.settings.auto_capture || {}) },
          }));
        }
        setMemoryCount(data.memory_count || 0);
      } catch {
        setMemoryNotice("记忆设置加载失败，已使用默认值");
      } finally {
        setMemoryLoading(false);
      }
    };
    void load();
  }, [setMemoryCount]);

  const loadMemories = useCallback(async () => {
    setMemoriesLoading(true);
    try {
      const resp = await fetch("/api/memory/");
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      setMemories(data.memories || []);
      setMemoryCount(data.total || 0);
    } catch {
      setMemoryNotice("加载记忆列表失败");
    } finally {
      setMemoriesLoading(false);
    }
  }, [setMemoryCount]);

  useEffect(() => { void loadMemories(); }, [loadMemories]);

  // ── Provider selection ──
  const handleProviderSelect = (pid: ProviderId) => {
    setProvider(pid);
    const preset = PROVIDERS.find((p) => p.id === pid);
    if (!preset) return;
    setBaseUrl(preset.baseUrl);
    if (preset.models.length > 0) setModelName(preset.models[0]);
  };

  const activePreset = PROVIDERS.find((p) => p.id === provider);

  // ── Save LLM config ──
  const handleSaveConfig = async () => {
    setConfigSaving(true);
    setConfigStatus("idle");
    try {
      const resp = await fetch("/api/llm-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, base_url: baseUrl, model: modelName, api_key: apiKey || null, is_reasoning_model: isReasoningModel }),
      });
      if (!resp.ok) throw new Error();
      const data: LLMConfig = await resp.json();
      setApiKeyMasked(data.api_key_masked);
      setHasApiKey(data.has_api_key);
      setApiKey("");
      setConfigStatus("saved");
      setTimeout(() => setConfigStatus("idle"), 3000);
    } catch {
      setConfigStatus("error");
    } finally {
      setConfigSaving(false);
    }
  };

  // ── Memory handlers ──
  const saveMemorySettings = async (patch: {
    enabled?: boolean;
    auto_capture?: Partial<MemorySettings["auto_capture"]>;
  }) => {
    setMemorySaving(true);
    setMemoryNotice("");
    try {
      const resp = await fetch("/api/memory/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      setMemorySettings((prev) => ({
        ...prev,
        ...data.settings,
        auto_capture: { ...prev.auto_capture, ...(data.settings?.auto_capture || {}) },
      }));
      setMemoryCount(data.memory_count || 0);
      setMemoryNotice("设置已保存");
    } catch {
      setMemoryNotice("保存失败");
    } finally {
      setMemorySaving(false);
    }
  };

  const handleClearMemories = async () => {
    if (!confirm("确定清空所有记忆？此操作不可恢复。")) return;
    try {
      await fetch("/api/memory/clear", { method: "POST" });
      setMemoryCount(0);
      setMemories([]);
      setMemoryNotice("已清空全部记忆");
    } catch {
      setMemoryNotice("清空记忆失败");
    }
  };

  const handleCreateMemory = async () => {
    if (!newMemoryContent.trim()) return;
    try {
      await fetch("/api/memory/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: newMemoryCategory, content: newMemoryContent.trim() }),
      });
      setNewMemoryContent("");
      setMemoryNotice("已添加记忆");
      await loadMemories();
    } catch {
      setMemoryNotice("添加失败");
    }
  };

  const handleDeleteMemory = async (id: string) => {
    try {
      await fetch(`/api/memory/${id}`, { method: "DELETE" });
      setMemoryNotice("已删除");
      await loadMemories();
    } catch {
      setMemoryNotice("删除失败");
    }
  };

  const handleSaveEdit = async () => {
    if (!editingId || !editingContent.trim()) return;
    try {
      await fetch(`/api/memory/${editingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: editingCategory, content: editingContent.trim() }),
      });
      setEditingId(null);
      setEditingContent("");
      setMemoryNotice("已更新");
      await loadMemories();
    } catch {
      setMemoryNotice("更新失败");
    }
  };

  const handleExportMemories = async () => {
    try {
      const resp = await fetch("/api/memory/export");
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data.memories || [], null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "user-memories.json";
      a.click();
      URL.revokeObjectURL(url);
      setMemoryNotice("已导出 JSON");
    } catch {
      setMemoryNotice("导出失败");
    }
  };

  const categoryLabel: Record<MemoryItem["category"], string> = {
    preference: "偏好", fact: "事实", instruction: "指令", feedback: "反馈",
  };

  const tabs = [
    { id: "model" as Tab, label: "模型配置", icon: <Cpu className="w-4 h-4" /> },
    { id: "memory" as Tab, label: "记忆管理", icon: <Brain className="w-4 h-4" /> },
    { id: "developer" as Tab, label: "开发者", icon: <Code2 className="w-4 h-4" /> },
  ];

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-7">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">设置</h1>
        <p className="text-sm text-gray-400 mt-1">配置模型供应商、管理记忆与开发者工具</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-7 bg-gray-100 p-1 rounded-xl w-fit">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
              activeTab === tab.id
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* ═══ TAB: 模型配置 ═══ */}
      {activeTab === "model" && (
        <div className="space-y-5">
          {/* Status badge */}
          {!configLoading && (
            <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium ${
              hasApiKey
                ? "bg-green-50 text-green-700 border border-green-200"
                : "bg-gray-100 text-gray-500 border border-gray-200"
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${hasApiKey ? "bg-green-500" : "bg-gray-400"}`} />
              {hasApiKey
                ? `已配置${activePreset ? ` · ${activePreset.name}` : ""}`
                : "未配置，使用环境变量"}
            </div>
          )}

          {/* Provider cards */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
              模型供应商
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              {PROVIDERS.map((p) => {
                const selected = provider === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => handleProviderSelect(p.id)}
                    className={`relative flex items-center gap-3 px-4 py-3 rounded-xl border-2 text-left transition-all duration-150 ${
                      selected
                        ? "border-current shadow-sm"
                        : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                    }`}
                    style={selected ? { borderColor: p.color, backgroundColor: p.bg } : {}}
                  >
                    <span
                      className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold"
                      style={{ backgroundColor: selected ? p.color : "#E5E7EB", color: selected ? "#fff" : "#6B7280" }}
                    >
                      {p.abbr}
                    </span>
                    <span
                      className="text-sm font-medium"
                      style={{ color: selected ? p.color : "#374151" }}
                    >
                      {p.name}
                    </span>
                    {selected && (
                      <span
                        className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full"
                        style={{ backgroundColor: p.color }}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* BASE URL */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              Base URL
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={activePreset?.baseUrl || "https://api.example.com/v1"}
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-300"
            />
          </div>

          {/* Model Name */}
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
              模型名称
            </label>
            <div className="relative">
              <input
                type="text"
                list="model-suggestions"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder={activePreset?.models[0] || "model-name"}
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-300 pr-8"
              />
              <datalist id="model-suggestions">
                {(activePreset?.models ?? []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            {activePreset && activePreset.models.length > 0 && (
              <p className="text-xs text-gray-400 mt-1.5">
                推荐：{activePreset.models.join(" · ")}
              </p>
            )}
          </div>

          {/* Reasoning model toggle */}
          <div className="flex items-center justify-between px-3 py-2.5 border border-gray-200 rounded-xl bg-gray-50">
            <div>
              <p className="text-sm font-medium text-gray-700">推理模型</p>
              <p className="text-xs text-gray-400 mt-0.5">开启后回传 reasoning_content（DeepSeek v4 系列等思考模型需要）</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={isReasoningModel}
              onClick={() => setIsReasoningModel(!isReasoningModel)}
              className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                isReasoningModel ? "bg-blue-600" : "bg-gray-200"
              }`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                  isReasoningModel ? "translate-x-5" : "translate-x-0"
                }`}
              />
            </button>
          </div>

          {/* API Key */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider">
                API Key
              </label>
              {hasApiKey && !apiKey && (
                <span className="text-xs text-green-600 flex items-center gap-1">
                  <Check className="w-3 h-3" /> 已配置
                  {apiKeyMasked && (
                    <span className="font-mono text-gray-400">{apiKeyMasked}</span>
                  )}
                  <button
                    type="button"
                    onClick={async () => {
                      await fetch("/api/llm-config", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ provider, base_url: baseUrl, model: modelName, api_key: "" }),
                      });
                      setHasApiKey(false);
                      setApiKeyMasked("");
                    }}
                    className="ml-1 text-red-400 hover:text-red-600 underline"
                  >
                    清除
                  </button>
                </span>
              )}
            </div>
            <div className="relative">
              <input
                type={apiKeyVisible ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  hasApiKey
                    ? "留空保留现有密钥，输入新值覆盖"
                    : (activePreset?.keyPlaceholder || "your-api-key")
                }
                className="w-full pl-3 pr-10 py-2.5 border border-gray-200 rounded-xl text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-300"
              />
              <button
                type="button"
                onClick={() => setApiKeyVisible(!apiKeyVisible)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {apiKeyVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              密钥存储于服务端数据库，不暴露在浏览器。
            </p>
          </div>

          {/* Save button */}
          <div className="flex items-center justify-between pt-2 border-t border-gray-100">
            {configStatus === "saved" && (
              <span className="text-sm text-green-600 flex items-center gap-1.5">
                <Check className="w-4 h-4" /> 配置已保存
              </span>
            )}
            {configStatus === "error" && (
              <span className="text-sm text-red-500 flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4" /> 保存失败，请重试
              </span>
            )}
            {configStatus === "idle" && <span />}
            <button
              onClick={() => void handleSaveConfig()}
              disabled={configSaving}
              className="flex items-center gap-2 px-5 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Save className="w-4 h-4" />
              {configSaving ? "保存中..." : "保存配置"}
            </button>
          </div>
        </div>
      )}

      {/* ═══ TAB: 记忆管理 ═══ */}
      {activeTab === "memory" && (
        <div className="space-y-5">
          <div className="bento-card p-5 space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={memorySettings.auto_capture.preference && memorySettings.auto_capture.instruction}
                disabled={memoryLoading || memorySaving}
                onChange={(e) => {
                  const checked = e.target.checked;
                  const patch = { preference: checked, instruction: checked };
                  setMemorySettings((prev) => ({
                    ...prev,
                    auto_capture: { ...prev.auto_capture, ...patch },
                  }));
                  void saveMemorySettings({ auto_capture: patch });
                }}
                className="rounded"
              />
              <span className="text-sm text-gray-700">自动记住我的偏好和指令</span>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={memorySettings.auto_capture.fact}
                disabled={memoryLoading || memorySaving}
                onChange={(e) => {
                  const checked = e.target.checked;
                  const patch = { fact: checked };
                  setMemorySettings((prev) => ({
                    ...prev,
                    auto_capture: { ...prev.auto_capture, ...patch },
                  }));
                  void saveMemorySettings({ auto_capture: patch });
                }}
                className="rounded"
              />
              <span className="text-sm text-gray-700">自动记住关于我的事实信息（公司、职位等）</span>
            </label>
            <p className="text-xs text-gray-400">长期记忆默认开启；事实类记忆需手动打开。</p>
            {memoryNotice && (
              <p className={`text-xs ${memoryNotice.includes("失败") ? "text-red-500" : "text-green-600"}`}>
                {memoryNotice}
              </p>
            )}
            <div className="pt-3 border-t border-gray-100 flex items-center justify-between">
              <span className="text-sm text-gray-500">
                已捕获 <strong>{memoryCount}</strong> 条记忆
              </span>
              <div className="flex gap-3">
                <button className="text-sm text-gray-500 hover:text-gray-700" onClick={() => void handleExportMemories()}>
                  导出 JSON
                </button>
                <button className="text-sm text-red-500 hover:text-red-700" onClick={() => void handleClearMemories()}>
                  清空记忆
                </button>
              </div>
            </div>

            {/* Add memory */}
            <div className="pt-3 border-t border-gray-100 space-y-2">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">手动添加</p>
              <div className="flex flex-col gap-2 md:flex-row">
                <select
                  value={newMemoryCategory}
                  onChange={(e) => setNewMemoryCategory(e.target.value as MemoryItem["category"])}
                  className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm"
                >
                  <option value="preference">偏好</option>
                  <option value="fact">事实</option>
                  <option value="instruction">指令</option>
                  <option value="feedback">反馈</option>
                </select>
                <input
                  value={newMemoryContent}
                  onChange={(e) => setNewMemoryContent(e.target.value)}
                  placeholder="输入要长期保存的记忆..."
                  className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  onClick={() => void handleCreateMemory()}
                  className="rounded-lg bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700"
                >
                  添加
                </button>
              </div>
            </div>

            {/* Memory list */}
            <div className="pt-3 border-t border-gray-100 space-y-2">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">记忆列表</p>
              {memoriesLoading ? (
                <p className="text-sm text-gray-400">加载中...</p>
              ) : memories.length === 0 ? (
                <p className="text-sm text-gray-400">暂无记忆</p>
              ) : (
                <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                  {memories.map((mem) => {
                    const editing = editingId === mem.id;
                    return (
                      <div key={mem.id} className="rounded-xl border border-gray-100 bg-gray-50/70 p-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 text-xs text-gray-500">
                            <span className="rounded-full bg-white px-2 py-0.5 text-gray-700 ring-1 ring-gray-200">
                              {categoryLabel[mem.category]}
                            </span>
                            <span>{mem.source === "user_explicit" ? "手动" : "自动"}</span>
                            {mem.created_at && (
                              <span>{new Date(mem.created_at).toLocaleDateString("zh-CN")}</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-xs">
                            {editing ? (
                              <>
                                <button className="text-blue-600 hover:text-blue-700" onClick={() => void handleSaveEdit()}>保存</button>
                                <button className="text-gray-400" onClick={() => { setEditingId(null); setEditingContent(""); }}>取消</button>
                              </>
                            ) : (
                              <>
                                <button
                                  className="text-blue-600 hover:text-blue-700"
                                  onClick={() => { setEditingId(mem.id); setEditingCategory(mem.category); setEditingContent(mem.content); }}
                                >
                                  编辑
                                </button>
                                <button className="text-red-500 hover:text-red-700" onClick={() => void handleDeleteMemory(mem.id)}>删除</button>
                              </>
                            )}
                          </div>
                        </div>
                        {editing ? (
                          <div className="mt-2 space-y-2">
                            <select
                              value={editingCategory}
                              onChange={(e) => setEditingCategory(e.target.value as MemoryItem["category"])}
                              className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm"
                            >
                              <option value="preference">偏好</option>
                              <option value="fact">事实</option>
                              <option value="instruction">指令</option>
                              <option value="feedback">反馈</option>
                            </select>
                            <textarea
                              value={editingContent}
                              onChange={(e) => setEditingContent(e.target.value)}
                              rows={3}
                              className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </div>
                        ) : (
                          <p className="mt-2 text-sm leading-relaxed text-gray-700 whitespace-pre-wrap">{mem.content}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══ TAB: 开发者 ═══ */}
      {activeTab === "developer" && (
        <div className="space-y-5">
          <div className="bento-card p-5 space-y-3">
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={devMode} onChange={(e) => setDevMode(e.target.checked)} className="rounded" />
              <span className="text-sm text-gray-700">显示 Token 用量计数器</span>
            </label>
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" defaultChecked className="rounded" />
              <span className="text-sm text-gray-700">显示 Thinking 推理过程</span>
            </label>
            {devMode && tokenUsage && (
              <div className="pt-3 border-t border-gray-100">
                <h3 className="text-sm font-medium text-gray-600 mb-2">当前会话 Token 统计</h3>
                <div className="grid grid-cols-2 gap-2 text-sm text-gray-500">
                  <span>Prompt Tokens:</span>
                  <span className="text-right font-mono">{tokenUsage.promptTokens.toLocaleString()}</span>
                  <span>Completion Tokens:</span>
                  <span className="text-right font-mono">{tokenUsage.completionTokens.toLocaleString()}</span>
                  <span>使用率:</span>
                  <span className="text-right font-mono">{(tokenUsage.usageRatio * 100).toFixed(1)}%</span>
                </div>
              </div>
            )}
          </div>

          <div className="bento-card p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-2">上下文管理</h3>
            <p className="text-sm text-gray-500 mb-3">
              对话过长时系统自动压缩历史上下文。也可在聊天中输入{" "}
              <code className="bg-gray-100 px-1 rounded text-xs">/compact</code> 手动触发。
            </p>
            <div className="text-sm text-gray-400 space-y-1">
              <p>• 压缩阈值: 70% 上下文窗口</p>
              <p>• 告警阈值: 85% 上下文窗口</p>
              <p>• 上下文窗口: 128,000 Token</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
