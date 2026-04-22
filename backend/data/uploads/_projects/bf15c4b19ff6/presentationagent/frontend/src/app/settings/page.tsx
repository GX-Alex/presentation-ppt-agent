/**
 * Settings page — 用户设置、记忆管理、开发者模式、API Key 管理。
 * Route: /settings
 * Sprint 6: API Key 管理 + 模型选择增强。
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import InstalledPackagesPanel from "@/components/packages/InstalledPackagesPanel";
import { useChatStore } from "@/stores/chatStore";
import { Eye, EyeOff, Key, Save } from "lucide-react";

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

// ────── API Key 管理组件 ──────

function ApiKeyField({ label, envKey, description }: { label: string; envKey: string; description: string }) {
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [saved, setSaved] = useState(false);

  return (
    <div className="space-y-1">
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <p className="text-xs text-gray-400">{description}</p>
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type={visible ? "text" : "password"}
            value={value}
            onChange={(e) => { setValue(e.target.value); setSaved(false); }}
            placeholder={`输入 ${envKey}...`}
            className="w-full pl-9 pr-10 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <button
            onClick={() => setVisible(!visible)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          >
            {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
        <button
          onClick={() => {
            // 前端暂存（实际部署需要后端环境变量管理）
            localStorage.setItem(`apikey_${envKey}`, value);
            setSaved(true);
            setTimeout(() => setSaved(false), 2000);
          }}
          className={`px-3 py-2 rounded-lg text-sm flex items-center gap-1 ${
            saved
              ? "bg-green-100 text-green-700"
              : "bg-primary-600 text-white hover:bg-primary-700"
          }`}
        >
          <Save className="w-4 h-4" />
          {saved ? "已保存" : "保存"}
        </button>
      </div>
    </div>
  );
}

// ────── 主组件 ──────

export default function SettingsPage() {
  const { devMode, setDevMode, memoryCount, tokenUsage, setMemoryCount } = useChatStore();
  const [selectedModel, setSelectedModel] = useState("minimax-m2.5");
  const [memorySettings, setMemorySettings] = useState<MemorySettings>({
    enabled: true,
    auto_capture: {
      preference: true,
      instruction: true,
      fact: false,
      feedback: false,
    },
  });
  const [memoryLoading, setMemoryLoading] = useState(true);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memoryNotice, setMemoryNotice] = useState("");
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(true);
  const [newMemoryCategory, setNewMemoryCategory] = useState<MemoryItem["category"]>("preference");
  const [newMemoryContent, setNewMemoryContent] = useState("");
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editingMemoryCategory, setEditingMemoryCategory] = useState<MemoryItem["category"]>("preference");
  const [editingMemoryContent, setEditingMemoryContent] = useState("");

  // 从 localStorage 恢复模型选择
  useEffect(() => {
    const saved = localStorage.getItem("selected_model");
    if (saved) setSelectedModel(saved);
  }, []);

  useEffect(() => {
    const loadMemorySettings = async () => {
      try {
        const resp = await fetch("/api/memory/settings");
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (data.settings) {
          setMemorySettings((prev) => ({
            ...prev,
            ...data.settings,
            auto_capture: {
              ...prev.auto_capture,
              ...(data.settings.auto_capture || {}),
            },
          }));
        }
        setMemoryCount(data.memory_count || 0);
      } catch (error) {
        console.error("[Settings] 加载记忆设置失败", error);
        setMemoryNotice("记忆设置加载失败，已使用默认值");
      } finally {
        setMemoryLoading(false);
      }
    };

    loadMemorySettings();
  }, [setMemoryCount]);

  const loadMemories = useCallback(async () => {
    setMemoriesLoading(true);
    try {
      const resp = await fetch("/api/memory/");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setMemories(data.memories || []);
      setMemoryCount(data.total || 0);
    } catch (error) {
      console.error("[Settings] 加载记忆列表失败", error);
      setMemoryNotice("加载记忆列表失败");
    } finally {
      setMemoriesLoading(false);
    }
  }, [setMemoryCount]);

  useEffect(() => {
    void loadMemories();
  }, [loadMemories]);

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    localStorage.setItem("selected_model", model);
  };

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
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      setMemorySettings((prev) => ({
        ...prev,
        ...data.settings,
        auto_capture: {
          ...prev.auto_capture,
          ...(data.settings?.auto_capture || {}),
        },
      }));
      setMemoryCount(data.memory_count || 0);
      setMemoryNotice("记忆设置已保存");
    } catch (error) {
      console.error("[Settings] 保存记忆设置失败", error);
      setMemoryNotice("记忆设置保存失败");
    } finally {
      setMemorySaving(false);
    }
  };

  const handleClearMemories = async () => {
    if (!confirm("确定清空所有记忆？此操作不可恢复。")) return;

    try {
      const resp = await fetch("/api/memory/clear", { method: "POST" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setMemoryCount(0);
      setMemories([]);
      setMemoryNotice("已清空全部记忆");
    } catch (error) {
      console.error("[Settings] 清空记忆失败", error);
      setMemoryNotice("清空记忆失败");
    }
  };

  const preferenceAndInstructionEnabled =
    memorySettings.auto_capture.preference && memorySettings.auto_capture.instruction;

  const handleCreateMemory = async () => {
    if (!newMemoryContent.trim()) return;
    try {
      const resp = await fetch("/api/memory/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: newMemoryCategory,
          content: newMemoryContent.trim(),
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setNewMemoryContent("");
      setMemoryNotice("已添加记忆");
      await loadMemories();
    } catch (error) {
      console.error("[Settings] 创建记忆失败", error);
      setMemoryNotice("添加记忆失败");
    }
  };

  const handleDeleteMemory = async (memoryId: string) => {
    try {
      const resp = await fetch(`/api/memory/${memoryId}`, { method: "DELETE" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setMemoryNotice("已删除记忆");
      await loadMemories();
    } catch (error) {
      console.error("[Settings] 删除记忆失败", error);
      setMemoryNotice("删除记忆失败");
    }
  };

  const handleSaveEditedMemory = async () => {
    if (!editingMemoryId || !editingMemoryContent.trim()) return;
    try {
      const resp = await fetch(`/api/memory/${editingMemoryId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: editingMemoryCategory,
          content: editingMemoryContent.trim(),
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setEditingMemoryId(null);
      setEditingMemoryContent("");
      setMemoryNotice("已更新记忆");
      await loadMemories();
    } catch (error) {
      console.error("[Settings] 更新记忆失败", error);
      setMemoryNotice("更新记忆失败");
    }
  };

  const handleExportMemories = async () => {
    try {
      const resp = await fetch("/api/memory/export");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data.memories || [], null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "user-memories.json";
      link.click();
      URL.revokeObjectURL(url);
      setMemoryNotice("已导出记忆 JSON");
    } catch (error) {
      console.error("[Settings] 导出记忆失败", error);
      setMemoryNotice("导出记忆失败");
    }
  };

  const categoryLabel: Record<MemoryItem["category"], string> = {
    preference: "偏好",
    fact: "事实",
    instruction: "指令",
    feedback: "反馈",
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6 tracking-tight">设置</h1>

      {/* 模型配置 */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">模型配置</h2>
        <div className="bento-card p-5">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            默认模型
          </label>
          <select
            value={selectedModel}
            onChange={(e) => handleModelChange(e.target.value)}
            className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-gray-50"
          >
            <option value="minimax-m2.5">MiniMax M2.5</option>
            <option value="glm-5">GLM-5</option>
            <option value="deepseek-v3">DeepSeek V3</option>
            <option value="claude-sonnet">Claude Sonnet</option>
            <option value="gpt-4o">GPT-4o</option>
          </select>
          <p className="mt-1.5 text-xs text-gray-400">
            选择 Agent 推理使用的默认大模型
          </p>
        </div>
      </section>

      {/* API Key 管理 */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">API Key 管理</h2>
        <div className="bento-card p-5 space-y-4">
          <ApiKeyField
            label="Pexels API Key"
            envKey="PEXELS_API_KEY"
            description="用于 image_search 工具搜索免费高质量图片"
          />
          <ApiKeyField
            label="Tavily API Key"
            envKey="TAVILY_API_KEY"
            description="用于 web_search 工具进行联网搜索"
          />
          <ApiKeyField
            label="LLM API Key"
            envKey="LLM_API_KEY"
            description="大模型 API 密钥（DeepSeek / OpenAI / Anthropic）"
          />
          <p className="text-xs text-gray-400 pt-2 border-t border-gray-100">
            提示：密钥仅保存在浏览器本地，不会上传至服务器。生产部署请使用环境变量。
          </p>
        </div>
      </section>

      {/* Package 管理 */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">Package 管理</h2>
        <div className="bento-card p-5 space-y-3">
          <div>
            <p className="text-sm text-gray-600">
              这里展示当前已安装的 Native PPTX-first 相关工作流包、Skill 包和适配器。你可以直接启停，安装请前往公共空间页的 Packages 标签。
            </p>
          </div>
          <InstalledPackagesPanel variant="summary" />
        </div>
      </section>

      {/* 记忆管理 */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">记忆管理</h2>
        <div className="bento-card p-5 space-y-3">
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={preferenceAndInstructionEnabled}
              disabled={memoryLoading || memorySaving}
              onChange={(e) => {
                const checked = e.target.checked;
                setMemorySettings((prev) => ({
                  ...prev,
                  auto_capture: {
                    ...prev.auto_capture,
                    preference: checked,
                    instruction: checked,
                  },
                }));
                void saveMemorySettings({
                  auto_capture: {
                    ...memorySettings.auto_capture,
                    preference: checked,
                    instruction: checked,
                  },
                });
              }}
              className="rounded"
            />
            <span className="text-sm text-gray-700">自动记住我的偏好和指令</span>
          </label>
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={memorySettings.auto_capture.fact}
              disabled={memoryLoading || memorySaving}
              onChange={(e) => {
                const checked = e.target.checked;
                setMemorySettings((prev) => ({
                  ...prev,
                  auto_capture: {
                    ...prev.auto_capture,
                    fact: checked,
                  },
                }));
                void saveMemorySettings({
                  auto_capture: {
                    ...memorySettings.auto_capture,
                    fact: checked,
                  },
                });
              }}
              className="rounded"
            />
            <span className="text-sm text-gray-700">自动记住关于我的事实信息（公司、职位等）</span>
          </label>
          <p className="text-xs text-gray-400">
            长期记忆默认开启；事实类记忆默认关闭，需你明确打开。
          </p>
          {memoryNotice ? (
            <p className={`text-xs ${memoryNotice.includes("失败") ? "text-red-500" : "text-green-600"}`}>
              {memoryNotice}
            </p>
          ) : null}
          <div className="pt-3 border-t border-gray-100 flex items-center justify-between">
            <span className="text-sm text-gray-500">
              已捕获记忆: <strong>{memoryCount}</strong> 条
            </span>
            <div className="flex items-center gap-3">
              <button
                className="text-sm text-gray-500 hover:text-gray-700"
                onClick={() => void handleExportMemories()}
              >
                导出 JSON
              </button>
              <button
                className="text-sm text-red-500 hover:text-red-700"
                onClick={() => void handleClearMemories()}
              >
                清空记忆
              </button>
            </div>
          </div>

          <div className="pt-3 border-t border-gray-100 space-y-2">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">手动添加记忆</p>
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
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <button
                onClick={() => void handleCreateMemory()}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700"
              >
                添加
              </button>
            </div>
          </div>

          <div className="pt-3 border-t border-gray-100 space-y-2">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">记忆列表</p>
            {memoriesLoading ? (
              <p className="text-sm text-gray-400">加载中...</p>
            ) : memories.length === 0 ? (
              <p className="text-sm text-gray-400">暂无记忆</p>
            ) : (
              <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
                {memories.map((memory) => {
                  const editing = editingMemoryId === memory.id;
                  return (
                    <div key={memory.id} className="rounded-xl border border-gray-100 bg-gray-50/70 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 text-xs text-gray-500">
                          <span className="rounded-full bg-white px-2 py-1 text-gray-700 ring-1 ring-gray-200">
                            {categoryLabel[memory.category]}
                          </span>
                          <span>{memory.source === "user_explicit" ? "手动" : "自动"}</span>
                          {memory.created_at ? (
                            <span>{new Date(memory.created_at).toLocaleDateString("zh-CN")}</span>
                          ) : null}
                        </div>
                        <div className="flex items-center gap-2 text-xs">
                          {editing ? (
                            <>
                              <button className="text-primary-600 hover:text-primary-700" onClick={() => void handleSaveEditedMemory()}>
                                保存
                              </button>
                              <button
                                className="text-gray-400 hover:text-gray-600"
                                onClick={() => {
                                  setEditingMemoryId(null);
                                  setEditingMemoryContent("");
                                }}
                              >
                                取消
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                className="text-primary-600 hover:text-primary-700"
                                onClick={() => {
                                  setEditingMemoryId(memory.id);
                                  setEditingMemoryCategory(memory.category);
                                  setEditingMemoryContent(memory.content);
                                }}
                              >
                                编辑
                              </button>
                              <button
                                className="text-red-500 hover:text-red-700"
                                onClick={() => void handleDeleteMemory(memory.id)}
                              >
                                删除
                              </button>
                            </>
                          )}
                        </div>
                      </div>

                      {editing ? (
                        <div className="mt-3 space-y-2">
                          <select
                            value={editingMemoryCategory}
                            onChange={(e) => setEditingMemoryCategory(e.target.value as MemoryItem["category"])}
                            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm"
                          >
                            <option value="preference">偏好</option>
                            <option value="fact">事实</option>
                            <option value="instruction">指令</option>
                            <option value="feedback">反馈</option>
                          </select>
                          <textarea
                            value={editingMemoryContent}
                            onChange={(e) => setEditingMemoryContent(e.target.value)}
                            rows={3}
                            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                          />
                        </div>
                      ) : (
                        <p className="mt-3 text-sm leading-relaxed text-gray-700 whitespace-pre-wrap">
                          {memory.content}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 开发者模式 */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">开发者模式</h2>
        <div className="bento-card p-5 space-y-3">
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={devMode}
              onChange={(e) => setDevMode(e.target.checked)}
              className="rounded"
            />
            <span className="text-sm text-gray-700">显示 Token 用量计数器</span>
          </label>
          <label className="flex items-center gap-3">
            <input type="checkbox" defaultChecked className="rounded" />
            <span className="text-sm text-gray-700">显示 Thinking 推理过程</span>
          </label>

          {/* Token 统计 */}
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
      </section>

      {/* 上下文管理 */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">上下文管理</h2>
        <div className="bento-card p-5">
          <p className="text-sm text-gray-600 mb-3">
            当对话过长时，系统会自动压缩历史上下文。你也可以在聊天中输入{" "}
            <code className="bg-gray-100 px-1 rounded">/compact</code>{" "}
            手动触发压缩。
          </p>
          <div className="text-sm text-gray-500">
            <p>• 压缩阈值: 70% 上下文窗口</p>
            <p>• 告警阈值: 85% 上下文窗口</p>
            <p>• 上下文窗口: 128,000 Token</p>
          </div>
        </div>
      </section>
    </div>
  );
}
