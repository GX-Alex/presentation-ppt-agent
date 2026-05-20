/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * ExecutionTimeline — 步骤卡片流，显示 Agent 执行过程。
 * 替代 ReasoningBubble，增加 SubAgent 嵌套卡片。
 */
"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  CheckCircle2,
  XCircle,
  Circle,
  Bot,
  Search,
  FileCode,
  PenTool,
  FileText,
} from "lucide-react";
import {
  useChatStore,
  type ExecutionStep,
  type SubAgentState,
  type StepStatus,
} from "@/stores/chatStore";

// ── Agent 类型图标映射 ──
const AGENT_ICONS: Record<string, any> = {
  code_analyst: FileCode,
  researcher: Search,
  diagram: PenTool,
  writer: FileText,
};

const AGENT_LABELS: Record<string, string> = {
  code_analyst: "代码分析",
  researcher: "深度研究",
  diagram: "架构图生成",
  writer: "综合写作",
};

// ── 状态图标 ──
function StatusIcon({ status, size = 16 }: { status: StepStatus; size?: number }) {
  switch (status) {
    case "running":
      return <Loader2 size={size} className="animate-spin text-blue-500" />;
    case "completed":
      return <CheckCircle2 size={size} className="text-emerald-500" />;
    case "failed":
      return <XCircle size={size} className="text-red-500" />;
    default:
      return <Circle size={size} className="text-slate-400" />;
  }
}

// ── 状态样式 ──
function statusBg(status: StepStatus): string {
  switch (status) {
    case "running":
      return "bg-blue-50 border-blue-200";
    case "completed":
      return "bg-emerald-50 border-emerald-200";
    case "failed":
      return "bg-red-50 border-red-200";
    default:
      return "bg-slate-50 border-slate-200";
  }
}

// ── SubAgentCard ──
function SubAgentCard({ agent }: { agent: SubAgentState }) {
  const [expanded, setExpanded] = useState(agent.status === "running");
  const AgentIcon = AGENT_ICONS[agent.agentType] || Bot;
  const label = AGENT_LABELS[agent.agentType] || agent.agentType;

  return (
    <div className={`ml-4 mt-2 rounded-lg border ${statusBg(agent.status)} overflow-hidden`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/5 transition-colors"
      >
        <AgentIcon size={14} className="text-slate-600 flex-shrink-0" />
        <span className="font-medium text-slate-700">{label}</span>
        <StatusIcon status={agent.status} size={14} />
        {agent.duration != null && (
          <span className="text-xs text-slate-500 ml-auto mr-2">{(agent.duration / 1000).toFixed(1)}s</span>
        )}
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>

      {expanded && (
        <div className="px-3 pb-2 text-xs text-slate-600">
          <p className="mb-1 text-slate-500 truncate">{agent.task}</p>
          {agent.steps.length > 0 && (
            <div className="space-y-0.5 mt-1">
              {agent.steps.map((step, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <StatusIcon status={step.status} size={10} />
                  <span className="truncate">{step.title}</span>
                </div>
              ))}
            </div>
          )}
          {agent.result && (
            <div className="mt-2 p-2 bg-white/60 rounded text-xs whitespace-pre-wrap max-h-32 overflow-y-auto">
              {agent.result.slice(0, 500)}
              {agent.result.length > 500 && "..."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── StepCard ──
function StepCard({ step }: { step: ExecutionStep }) {
  const [expanded, setExpanded] = useState(step.status === "running");

  return (
    <div className={`rounded-lg border ${statusBg(step.status)} overflow-hidden`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/5 transition-colors"
      >
        <StatusIcon status={step.status} size={16} />
        <span className="font-medium text-slate-700">{step.title}</span>
        {step.duration != null && (
          <span className="text-xs text-slate-500 ml-auto mr-2">{(step.duration / 1000).toFixed(1)}s</span>
        )}
        {(step.subAgents?.length || step.content) ? (
          expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        ) : null}
      </button>

      {expanded && (
        <div className="px-3 pb-2">
          {step.content && (
            <p className="text-xs text-slate-600 whitespace-pre-wrap">{step.content}</p>
          )}
          {step.subAgents?.map((sa) => (
            <SubAgentCard key={sa.agentId} agent={sa} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── ExecutionTimeline (主组件) ──
export default function ExecutionTimeline() {
  const executionSteps = useChatStore((s) => s.executionSteps);
  const hasRunning = executionSteps.some(
    (s) => s.status === "running" || s.subAgents?.some((sa) => sa.status === "running")
  );
  const [collapsed, setCollapsed] = useState(!hasRunning);

  if (executionSteps.length === 0) return null;

  return (
    <div className="my-2 mx-1">
      {/* 头部 */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 mb-2 text-xs text-slate-500 hover:text-slate-700 transition-colors"
      >
        {hasRunning ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <CheckCircle2 size={12} className="text-emerald-500" />
        )}
        <span>{hasRunning ? "执行中..." : "执行完成"}</span>
        <span className="text-slate-400">({executionSteps.length} 步)</span>
        {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
      </button>

      {/* 步骤列表 */}
      {!collapsed && (
        <div className="space-y-2">
          {executionSteps.map((step) => (
            <StepCard key={step.id} step={step} />
          ))}
        </div>
      )}
    </div>
  );
}
