/**
 * i18n 国际化壳子 — Sprint 7。
 * 当前仅预留接口和中文语言包，后续可扩展多语言。
 * 使用方式: import { t } from "@/lib/i18n";  t("common.save")
 */

// ────── 语言包类型 ──────

type NestedStrings = { [key: string]: string | NestedStrings };

// ────── 中文语言包 ──────

const zhCN: NestedStrings = {
  common: {
    save: "保存",
    cancel: "取消",
    delete: "删除",
    confirm: "确认",
    loading: "加载中...",
    refresh: "刷新",
    search: "搜索",
    upload: "上传",
    download: "下载",
    export: "导出",
    publish: "发布",
    fork: "Fork",
    edit: "编辑",
    back: "返回",
    next: "下一步",
    prev: "上一步",
    close: "关闭",
    yes: "是",
    no: "否",
    noData: "暂无数据",
    error: "出错了",
    retry: "重试",
    success: "成功",
  },
  nav: {
    newTask: "新建任务",
    assets: "资产",
    gallery: "公共空间",
    settings: "设置",
    taskHistory: "任务记录",
    noHistory: "暂无历史任务",
  },
  chat: {
    inputPlaceholder: "输入消息... (Enter 发送, Shift+Enter 换行)",
    thinking: "正在思考...",
    searching: "正在搜索...",
    generating: "正在生成...",
    connectionLost: "连接已断开，正在重连...",
    connected: "已连接",
    reconnecting: "重连中...",
  },
  assets: {
    title: "资产",
    searchPlaceholder: "搜索资产...",
    noAssets: "资产为空",
    noAssetsHint: "上传文件或生成内容后，文件将自动出现在资产库",
    publishToGallery: "发布到公共空间",
    published: "已发布到公共空间！",
    tabs: {
      all: "全部",
      document: "文档",
      ppt: "PPT",
      code: "代码",
      image: "图片",
      skill: "🔌 Skill",
    },
  },
  gallery: {
    title: "公共空间",
    searchPlaceholder: "搜索作品...",
    noItems: "暂无作品",
    noItemsHint: "发布你的资产文件到公共空间，让更多人看到你的创作。",
    forkSuccess: "Fork 成功！已添加到你的资产。",
    sortNewest: "最新发布",
    sortPopular: "最多浏览",
    sortRemix: "最多 Fork",
    tabs: {
      featured: "推荐",
      ppt: "PPT",
      research: "研究",
      code: "代码",
      skill: "🔌 Skill",
      other: "其他",
    },
  },
  settings: {
    title: "设置",
    model: "模型配置",
    defaultModel: "默认模型",
    apiKeys: "API Key 管理",
    memory: "记忆管理",
    clearMemory: "清空记忆",
    clearMemoryConfirm: "确定清空所有记忆？此操作不可恢复。",
    devMode: "开发者模式",
    contextManagement: "上下文管理",
  },
  ppt: {
    generating: "正在生成幻灯片",
    complete: "生成完成",
    editing: "编辑模式",
    slideOf: "第 {n} 页",
    export: "导出",
    exportHTML: "HTML (浏览器展示)",
    exportPDF: "PDF (打印/分享)",
    exportPPTX: "PPTX (可编辑)",
  },
  error: {
    networkError: "网络连接异常，请检查网络后重试",
    serverError: "服务器异常，请稍后重试",
    timeout: "请求超时，请稍后重试",
    unknown: "发生未知错误",
  },
};

// ────── 当前语言 ──────

let currentLocale = "zh-CN";
const locales: Record<string, NestedStrings> = { "zh-CN": zhCN };

// ────── 翻译函数 ──────

/**
 * 根据 key 路径获取翻译文本。
 * 支持嵌套路径，如 t("common.save") → "保存"
 * 支持变量替换，如 t("ppt.slideOf", { n: 3 }) → "第 3 页"
 */
export function t(key: string, vars?: Record<string, string | number>): string {
  const pack = locales[currentLocale] || zhCN;
  const parts = key.split(".");
  let result: string | NestedStrings = pack;

  for (const part of parts) {
    if (typeof result === "object" && result !== null && part in result) {
      result = result[part];
    } else {
      // key 未找到，返回 key 本身
      return key;
    }
  }

  if (typeof result !== "string") return key;

  // 变量替换 {varName}
  if (vars) {
    return result.replace(/\{(\w+)\}/g, (_, name) =>
      vars[name] !== undefined ? String(vars[name]) : `{${name}}`
    );
  }

  return result;
}

/**
 * 切换语言（预留接口）。
 */
export function setLocale(locale: string): void {
  if (locale in locales) {
    currentLocale = locale;
  }
}

/**
 * 获取当前语言。
 */
export function getLocale(): string {
  return currentLocale;
}
