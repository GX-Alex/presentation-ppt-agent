/**
 * Sidebar — 左侧导航栏。
 * Sprint 7: 响应式折叠 + 移动端适配 + 任务历史完善。
 */
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import {
  PlusCircle,
  FolderOpen,
  LayoutGrid,
  Settings,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  Trash2,
} from "lucide-react";
import { useChatStore } from "@/stores/chatStore";

/** 任务摘要类型 */
interface TaskSummary {
  id: string;
  title: string;
  status: string;
  intent: string | null;
  created_at: string | null;
}

/** 导航项配置 */
const navItems = [
  { href: "/chat/new", label: "新建任务", icon: PlusCircle },
  { href: "/assets", label: "资产", icon: FolderOpen },
  { href: "/gallery", label: "公共空间", icon: LayoutGrid },
  { href: "/settings", label: "设置", icon: Settings },
];

/** 清除标题中的附件标记，防止侧边栏显示原始 [附件: ...] 文本（含被截断的不完整标记） */
function cleanTitle(title: string): string {
  return title
    .replace(/\[附件: .+?\]/g, "")       // 完整标记
    .replace(/\[附件: [^\]]*$/g, "")      // 被截断的不完整标记（无闭合 ]）
    .replace(/\n{2,}/g, " ")              // 多余换行替换为空格
    .trim() || "未命名任务";
}

/** intent → 图标标记 */
function intentBadge(intent: string | null): string {
  if (!intent) return "";
  const m: Record<string, string> = { ppt: "📊", research: "📖", code_analysis: "💻", chat: "💬" };
  return m[intent] || "";
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(false);

  /** 新建任务：清空 store 后跳转 */
  const handleNewTask = useCallback(() => {
    const store = useChatStore.getState();
    store.clearMessages();
    store.resetPpt();
    store.clearExecutionSteps();
    useChatStore.setState({ taskId: null, intent: null });
    router.push("/chat/new");
  }, [router]);

  // 响应式：窗口小于 768px 时自动折叠
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const handler = (e: MediaQueryListEvent) => {
      if (e.matches) setCollapsed(true);
    };
    if (mq.matches) setCollapsed(true);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // 移动端菜单打开时锁定 body 滚动
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [mobileOpen]);

  // 路由变化时关闭移动端菜单
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // 加载任务列表
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const resp = await fetch("/api/tasks/");
        if (!resp.ok) return;
        const data = await resp.json();
        if (!cancelled && data.tasks) setTasks(data.tasks);
      } catch (err) {
        console.error("[Sidebar] 加载任务列表失败:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [pathname]);

  // 键盘快捷键 ⌘.  切换侧边栏
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ".") {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  /** 删除任务 */
  const handleDeleteTask = useCallback(async (taskId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    if (!confirm("确定要删除这个任务吗？删除后无法恢复。")) {
      return;
    }

    try {
      const resp = await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
      if (resp.ok) {
        // 从列表中移除
        setTasks((prev) => prev.filter((t) => t.id !== taskId));
        // 如果当前在删除的任务页面，跳转到新任务
        if (pathname === `/chat/${taskId}`) {
          router.push("/chat/new");
        }
      } else {
        console.error("[Sidebar] 删除任务失败");
      }
    } catch (err) {
      console.error("[Sidebar] 删除任务失败:", err);
    }
  }, [pathname, router]);

  const sidebarContent = (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-5">
        {!collapsed && (
          <span className="text-lg font-bold text-gray-900 select-none tracking-tight">🤖 Agent</span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg hidden md:block transition-colors"
          title={collapsed ? "展开侧边栏 (⌘.)" : "收起侧边栏 (⌘.)"}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
        {/* 移动端关闭按钮 */}
        <button
          onClick={() => setMobileOpen(false)}
          className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg md:hidden transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-1 px-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            pathname === item.href ||
            (item.href === "/chat/new" && pathname.startsWith("/chat/"));

          // "新建任务" 使用 button + onClick 来清空 store
          if (item.href === "/chat/new") {
            return (
              <button
                key={item.href}
                onClick={handleNewTask}
                className={`flex items-center gap-3 px-3 py-2.5 text-sm rounded-xl transition-all w-full text-left mb-0.5 ${
                  isActive
                    ? "bg-primary-50 text-primary-700 font-semibold shadow-sm"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                }`}
                title={collapsed ? item.label : undefined}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </button>
            );
          }

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 text-sm rounded-xl transition-all mb-0.5 ${
                isActive
                  ? "bg-primary-50 text-primary-700 font-semibold shadow-sm"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              }`}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}

        {/* 任务历史列表 */}
        {!collapsed && (
          <div className="mt-5">
            <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2 px-3">
              历史记录
            </div>
            {loading ? (
              <div className="space-y-2 px-3 py-2">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="flex items-center gap-2 py-2">
                    <div className="w-4 h-4 bg-gray-200 rounded animate-pulse flex-shrink-0" />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-3 bg-gray-200 rounded-full animate-pulse" style={{ width: `${60 + i * 10}%` }} />
                      <div className="h-2 bg-gray-100 rounded-full animate-pulse w-[40%]" />
                    </div>
                  </div>
                ))}
              </div>
            ) : tasks.length === 0 ? (
              <div className="text-xs text-gray-400 text-center py-4">
                暂无历史任务
              </div>
            ) : (
              <div className="space-y-0.5 max-h-[50vh] overflow-y-auto scrollbar-thin">
                {tasks.map((t) => {
                  const isActive = pathname === `/chat/${t.id}`;
                  return (
                    <div
                      key={t.id}
                      className={`hover-reveal group relative flex items-center gap-2 px-3 py-2 rounded-xl text-xs transition-all truncate ${
                        isActive
                          ? "bg-primary-50 text-primary-700 font-medium"
                          : "text-gray-500 hover:bg-gray-50 hover:text-gray-700"
                      }`}
                    >
                      <Link
                        href={`/chat/${t.id}`}
                        className="flex-1 min-w-0"
                        title={cleanTitle(t.title || "未命名任务")}
                      >
                        <div className="flex items-center gap-1 truncate">
                          {intentBadge(t.intent) && (
                            <span className="flex-shrink-0">{intentBadge(t.intent)}</span>
                          )}
                          <span className="truncate">{cleanTitle(t.title || "未命名任务")}</span>
                        </div>
                        {t.created_at && (
                          <div className="text-[10px] text-gray-300 mt-0.5">
                            {new Date(t.created_at).toLocaleDateString("zh-CN")}
                          </div>
                        )}
                      </Link>
                      {/* 删除按钮 - 悬停时显示 */}
                      <button
                        onClick={(e) => handleDeleteTask(t.id, e)}
                        className="hover-child flex-shrink-0 p-1 text-gray-400 hover:text-red-500 transition-colors rounded-lg hover:bg-red-50"
                        title="删除任务"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </nav>

      {/* Footer */}
      {!collapsed && (
        <div className="px-5 py-4 text-[11px] text-gray-400 font-medium">
          General Agent v1.0.0
        </div>
      )}
    </>
  );

  return (
    <>
      {/* 移动端菜单按钮 */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-5 left-5 z-50 p-2.5 bento-card md:hidden"
        aria-label="打开菜单"
      >
        <Menu className="w-5 h-5 text-gray-600" />
      </button>

      {/* 移动端遮罩 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* 移动端侧边栏 */}
      <aside
        className={`fixed inset-y-3 left-3 z-50 flex flex-col bento-card w-[260px] transition-transform duration-200 md:hidden ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {sidebarContent}
      </aside>

      {/* 桌面端侧边栏 */}
      <aside
        className={`hidden md:flex flex-col bento-card transition-all duration-200 flex-shrink-0 ${
          collapsed ? "w-[68px]" : "w-[260px]"
        }`}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
