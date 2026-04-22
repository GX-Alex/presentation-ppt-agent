/**
 * SkillManager 组件 — 用户自定义 Skill 管理界面。
 * Sprint 4: 列表、创建、编辑、删除、校验、启用/禁用。
 * 位于 /assets 页面的 Skill Tab 中。
 */
"use client";

import { useEffect, useState, useCallback } from "react";
import { useToast, ConfirmDialog } from "@/components/ui/Toast";

/** API 基础地址 */
const API_BASE = "/api/skills";

/** Skill 数据类型 */
interface Skill {
  id: string;
  name: string;
  display_name: string;
  description: string;
  tags: string;
  required_tools: string;
  status: string;
  is_enabled: boolean;
  scope: string;
  validation_result: { passed: boolean; issues: string[] } | null;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

/** 系统 Skill 类型 */
interface SystemSkill {
  name: string;
  display_name: string;
  description: string;
  tags: string;
  required_tools: string;
  is_system: boolean;
  is_loaded: boolean;
}

/** 创建/编辑表单数据 */
interface SkillForm {
  name: string;
  display_name: string;
  description: string;
  tags: string;
  body: string;
  required_tools: string;
  scope: string;
}

const emptyForm: SkillForm = {
  name: "",
  display_name: "",
  description: "",
  tags: "",
  body: "",
  required_tools: "",
  scope: "manual",
};

export default function SkillManager() {
  const toast = useToast();
  const [userSkills, setUserSkills] = useState<Skill[]>([]);
  const [systemSkills, setSystemSkills] = useState<SystemSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<SkillForm>(emptyForm);
  const [error, setError] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; skillId: string | null }>({
    open: false,
    skillId: null,
  });

  /** 加载用户 Skill 列表 */
  const loadSkills = useCallback(async () => {
    try {
      setLoading(true);
      const [userRes, sysRes] = await Promise.all([
        fetch(API_BASE),
        fetch(`${API_BASE}/system`),
      ]);
      const userData = await userRes.json();
      const sysData = await sysRes.json();
      setUserSkills(userData.skills || []);
      setSystemSkills(sysData.skills || []);
    } catch (e) {
      console.error("加载 Skill 列表失败:", e);
      toast.error("加载 Skill 列表失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  /** 验证表单 */
  const validateForm = (): string | null => {
    if (!form.name.trim()) return "名称不能为空";
    if (!form.description.trim()) return "描述不能为空";
    if (!form.body.trim()) return "正文内容不能为空";
    if (form.name.length > 50) return "名称不能超过50个字符";
    if (form.description.length > 200) return "描述不能超过200个字符";
    return null;
  };

  /** 创建 Skill */
  const handleCreate = async () => {
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError("");
    try {
      const res = await fetch(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json();
        setError(err.detail || "创建失败");
        return;
      }
      toast.success("Skill 创建成功");
      setShowForm(false);
      setForm(emptyForm);
      await loadSkills();
    } catch (e) {
      setError(`请求失败: ${e}`);
    }
  };

  /** 更新 Skill */
  const handleUpdate = async () => {
    if (!editingId) return;
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError("");
    try {
      const res = await fetch(`${API_BASE}/${editingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json();
        setError(err.detail || "更新失败");
        return;
      }
      toast.success("Skill 更新成功");
      setShowForm(false);
      setEditingId(null);
      setForm(emptyForm);
      await loadSkills();
    } catch (e) {
      setError(`请求失败: ${e}`);
    }
  };

  /** 删除 Skill */
  const handleDelete = async (id: string) => {
    setDeleteConfirm({ open: true, skillId: id });
  };

  const confirmDelete = async () => {
    if (!deleteConfirm.skillId) return;
    try {
      const res = await fetch(`${API_BASE}/${deleteConfirm.skillId}`, { method: "DELETE" });
      if (res.ok) {
        toast.success("Skill 已删除");
      } else {
        toast.error("删除失败，请稍后重试");
      }
      await loadSkills();
    } catch (e) {
      console.error("删除失败:", e);
      toast.error("网络错误，删除失败");
    } finally {
      setDeleteConfirm({ open: false, skillId: null });
    }
  };

  /** 校验 Skill */
  const handleValidate = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/${id}/validate`, { method: "POST" });
      const data = await res.json();
      await loadSkills();
      const skill = data.skill;
      if (skill?.validation_result && !skill.validation_result.passed) {
        toast.warning(`校验未通过: ${skill.validation_result.issues.join(", ")}`);
      } else if (skill?.validation_result?.passed) {
        toast.success("校验通过！");
      }
    } catch (e) {
      console.error("校验失败:", e);
      toast.error("校验请求失败");
    }
  };

  /** 切换启用状态 */
  const handleToggle = async (id: string) => {
    try {
      await fetch(`${API_BASE}/${id}/toggle`, { method: "POST" });
      await loadSkills();
      toast.success("状态已更新");
    } catch (e) {
      console.error("切换失败:", e);
      toast.error("切换状态失败");
    }
  };

  /** 打开编辑表单 */
  const openEdit = (skill: Skill) => {
    setEditingId(skill.id);
    setForm({
      name: skill.name,
      display_name: skill.display_name,
      description: skill.description,
      tags: skill.tags,
      body: "",  // 需要从 API 获取
      required_tools: skill.required_tools,
      scope: skill.scope,
    });
    setShowForm(true);
    setError("");
  };

  /** 状态标签颜色 */
  const statusColor = (status: string) => {
    switch (status) {
      case "validated": return "bg-green-100 text-green-700";
      case "published": return "bg-blue-100 text-blue-700";
      default: return "bg-yellow-100 text-yellow-700";
    }
  };

  if (loading) {
    return <div className="text-center py-10 text-gray-400">加载中...</div>;
  }

  return (
    <div className="space-y-6">
      {/* 系统 Skill */}
      <div>
        <h3 className="text-sm font-semibold text-gray-600 mb-3">
          🔧 系统预置 Skill ({systemSkills.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {systemSkills.map((skill) => (
            <div
              key={skill.name}
              className="border border-gray-200 rounded-lg p-4 bg-gray-50"
            >
              <div className="flex items-center justify-between">
                <h4 className="font-medium text-gray-800">
                  {skill.display_name}
                </h4>
                <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
                  系统
                </span>
              </div>
              <p className="text-sm text-gray-500 mt-1">{skill.description}</p>
              <div className="text-xs text-gray-400 mt-2">
                工具: {skill.required_tools || "无"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 用户 Skill */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-600">
            👤 自定义 Skill ({userSkills.length})
          </h3>
          <button
            onClick={() => {
              setShowForm(true);
              setEditingId(null);
              setForm(emptyForm);
              setError("");
            }}
            className="px-3 py-1.5 bg-primary-600 text-white text-sm rounded-lg hover:bg-primary-700 transition"
          >
            + 新建 Skill
          </button>
        </div>

        {userSkills.length === 0 && !showForm && (
          <div className="text-center py-10 text-gray-400 border border-dashed rounded-lg">
            <p>暂无自定义 Skill</p>
            <p className="text-sm mt-1">点击「新建 Skill」创建你的第一个专业角色</p>
          </div>
        )}

        {/* Skill 列表 */}
        <div className="space-y-3">
          {userSkills.map((skill) => (
            <div
              key={skill.id}
              className="border border-gray-200 rounded-lg p-4 bg-white"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h4 className="font-medium text-gray-800">
                    {skill.display_name || skill.name}
                  </h4>
                  <span className={`text-xs px-2 py-0.5 rounded ${statusColor(skill.status)}`}>
                    {skill.status}
                  </span>
                  {skill.is_enabled && (
                    <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
                      已启用
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleValidate(skill.id)}
                    className="text-xs px-2 py-1 text-blue-600 hover:bg-blue-50 rounded"
                  >
                    校验
                  </button>
                  <button
                    onClick={() => handleToggle(skill.id)}
                    className={`text-xs px-2 py-1 rounded ${
                      skill.is_enabled
                        ? "text-orange-600 hover:bg-orange-50"
                        : "text-green-600 hover:bg-green-50"
                    }`}
                  >
                    {skill.is_enabled ? "禁用" : "启用"}
                  </button>
                  <button
                    onClick={() => openEdit(skill)}
                    className="text-xs px-2 py-1 text-gray-600 hover:bg-gray-100 rounded"
                  >
                    编辑
                  </button>
                  <button
                    onClick={() => handleDelete(skill.id)}
                    className="text-xs px-2 py-1 text-red-600 hover:bg-red-50 rounded"
                  >
                    删除
                  </button>
                </div>
              </div>
              <p className="text-sm text-gray-500 mt-1">{skill.description}</p>
              <div className="flex items-center gap-4 text-xs text-gray-400 mt-2">
                <span>作用域: {skill.scope}</span>
                <span>使用: {skill.usage_count} 次</span>
                {skill.tags && <span>标签: {skill.tags}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 创建/编辑表单 */}
      {showForm && (
        <div className="border border-primary-200 rounded-lg p-6 bg-primary-50">
          <h3 className="font-semibold text-gray-800 mb-4">
            {editingId ? "编辑 Skill" : "新建 Skill"}
          </h3>
          {error && (
            <div className="mb-4 p-3 bg-red-50 text-red-600 text-sm rounded">
              {error}
            </div>
          )}
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  名称 *
                </label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="如: my_expert"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                  disabled={!!editingId}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  展示名称
                </label>
                <input
                  type="text"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  placeholder="如: 我的专家"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                描述 *
              </label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="简短描述这个 Skill 的能力"
                className="w-full px-3 py-2 border rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                正文 (Markdown) *
              </label>
              <textarea
                value={form.body}
                onChange={(e) => setForm({ ...form, body: e.target.value })}
                placeholder="使用 Markdown 格式编写 Skill 的详细指令..."
                rows={8}
                className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
              />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  标签
                </label>
                <input
                  type="text"
                  value={form.tags}
                  onChange={(e) => setForm({ ...form, tags: e.target.value })}
                  placeholder="逗号分隔"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  依赖工具
                </label>
                <input
                  type="text"
                  value={form.required_tools}
                  onChange={(e) => setForm({ ...form, required_tools: e.target.value })}
                  placeholder="逗号分隔"
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  作用域
                </label>
                <select
                  value={form.scope}
                  onChange={(e) => setForm({ ...form, scope: e.target.value })}
                  className="w-full px-3 py-2 border rounded-lg text-sm"
                >
                  <option value="manual">手动加载</option>
                  <option value="auto">自动加载</option>
                </select>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={editingId ? handleUpdate : handleCreate}
                className="px-4 py-2 bg-primary-600 text-white text-sm rounded-lg hover:bg-primary-700"
              >
                {editingId ? "保存修改" : "创建 Skill"}
              </button>
              <button
                onClick={() => {
                  setShowForm(false);
                  setEditingId(null);
                  setForm(emptyForm);
                  setError("");
                }}
                className="px-4 py-2 text-gray-600 text-sm rounded-lg hover:bg-gray-100"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认对话框 */}
      <ConfirmDialog
        open={deleteConfirm.open}
        title="确认删除"
        message="确定要删除此 Skill 吗？此操作不可撤销。"
        confirmText="删除"
        cancelText="取消"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirm({ open: false, skillId: null })}
        type="error"
      />
    </div>
  );
}
