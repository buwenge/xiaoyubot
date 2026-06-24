"use client";

import { memo, useState } from "react";
import type { Message } from "@/lib/types";
import { MarkdownContent } from "./MarkdownContent";
import { IconTool, IconThinking, IconChevron } from "./Icons";

interface MessageBubbleProps {
  message: Message;
  showSenderLabel?: boolean;
  editMode?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
}

const SENDER_LABELS: Record<string, { name: string; color: string }> = {
  xiaoyu: { name: "小予", color: "text-warm-accent" },
  sonnet: { name: "Sonnet", color: "text-[#6B8CAE]" },
  deepseek: { name: "DeepSeek", color: "text-[#4D8ECA]" },
  user: { name: "你", color: "text-[#7B8E6E]" },
};

function ToolCallItem({ name, input }: { name: string; input: string }) {
  const [expanded, setExpanded] = useState(false);
  const summary = input.length > 50 ? input.slice(0, 50) + "..." : input;

  return (
    <div className="text-xs">
      <button
        onClick={() => setExpanded(!expanded)}
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg text-warm-text-secondary/60 hover:text-warm-text-secondary transition-colors"
      >
        <IconTool className="w-3 h-3" />
        <span className="font-medium">{name}</span>
        {summary && <span className="text-warm-text-secondary/40 truncate max-w-[160px]">{summary}</span>}
        <IconChevron className={`w-2.5 h-2.5 transition-transform ${expanded ? "rotate-90" : ""}`} />
      </button>
      {expanded && input && (
        <pre className="mt-1 p-2.5 rounded-xl glass-light text-warm-text-secondary/70 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed">
          {input}
        </pre>
      )}
    </div>
  );
}

export const MessageBubble = memo(function MessageBubble({ message, showSenderLabel, editMode, selected, onToggleSelect }: MessageBubbleProps) {
  const [showThinking, setShowThinking] = useState(false);
  const isUser = message.role === "user";
  const isHidden = message.hidden;
  const senderInfo = SENDER_LABELS[message.sender] || SENDER_LABELS.xiaoyu;

  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"} animate-fade-in ${editMode ? "cursor-pointer" : ""}`}
      onClick={editMode ? onToggleSelect : undefined}
    >
      {editMode && !isUser && (
        <div className="flex items-start pt-3 pr-2 shrink-0">
          <div className={`w-5 h-5 rounded-full border-2 transition-all flex items-center justify-center ${
            selected
              ? "border-warm-accent bg-warm-accent"
              : "border-warm-text-secondary/30"
          }`}>
            {selected && (
              <svg className="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
        </div>
      )}

      <div
        className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 transition-all ${
          isUser
            ? "glass rounded-br-lg"
            : "rounded-bl-lg bg-[#E8F5E9]/80 dark:bg-[#2E4A30]/70 backdrop-blur-sm"
        } ${isHidden ? "opacity-35 relative" : ""}`}
      >
        {isHidden && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
            <span className="text-[10px] text-warm-text-secondary/60 bg-warm-bg/80 dark:bg-[#1E1814]/80 px-2 py-0.5 rounded-full">
              已隐藏
            </span>
          </div>
        )}

        {showSenderLabel && (
          <div className={`text-[11px] font-medium mb-1 ${senderInfo.color}`}>
            {senderInfo.name}
          </div>
        )}

        {!isUser && message.thinking && (
          <div className="mb-1.5">
            <button
              onClick={(e) => { e.stopPropagation(); setShowThinking(!showThinking); }}
              className="flex items-center gap-1 text-[11px] text-warm-text-secondary/40 hover:text-warm-text-secondary/60 transition-colors"
            >
              <IconThinking className="w-3 h-3" />
              <span>思维链</span>
              <IconChevron className={`w-2.5 h-2.5 transition-transform ${showThinking ? "rotate-90" : ""}`} />
            </button>
            {showThinking && (
              <div className="mt-1.5 p-2.5 rounded-xl bg-warm-thinking/50 text-[11px] text-warm-text-secondary/60 italic leading-relaxed whitespace-pre-wrap max-h-[250px] overflow-y-auto">
                {message.thinking}
              </div>
            )}
          </div>
        )}

        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-1.5 space-y-1">
            {message.toolCalls.map((tc, i) => (
              <ToolCallItem key={i} name={tc.name} input={tc.input} />
            ))}
          </div>
        )}

        <div className="text-warm-text text-[14px] leading-relaxed break-words">
          {isUser ? (
            <span className="whitespace-pre-wrap">{message.text}</span>
          ) : message.isStreaming ? (
            <>
              <span className="whitespace-pre-wrap">{message.text}</span>
              <span className="inline-block w-0.5 h-3.5 bg-warm-accent/60 ml-0.5 animate-pulse align-text-bottom rounded-full" />
            </>
          ) : (
            <MarkdownContent content={message.text} />
          )}
        </div>

        <div className={`text-[10px] text-warm-text-secondary/40 mt-1 ${isUser ? "text-right" : "text-left"}`}>
          {new Date(message.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
        </div>
      </div>

      {editMode && isUser && (
        <div className="flex items-start pt-3 pl-2 shrink-0">
          <div className={`w-5 h-5 rounded-full border-2 transition-all flex items-center justify-center ${
            selected
              ? "border-warm-accent bg-warm-accent"
              : "border-warm-text-secondary/30"
          }`}>
            {selected && (
              <svg className="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
        </div>
      )}
    </div>
  );
});
