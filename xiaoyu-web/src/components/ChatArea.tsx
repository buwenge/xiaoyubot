"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import type { Channel, GroupAutoStatus, LogEntry, Message } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { GroupChatStatus } from "./GroupChatStatus";
import { ForgeDivider } from "./ForgeDivider";
import { IconBack, IconMenu, IconClose, IconSettings } from "./Icons";
import { ChannelTabs } from "./ChannelTabs";
import { ThemeToggle } from "./ThemeToggle";
import { LogPanel } from "./LogPanel";

// ── Isolated input component (prevents message list re-render on keystroke) ──

interface ChatInputProps {
  onSend: (text: string) => void;
  isStreaming: boolean;
  placeholder: string;
  historyDate?: string | null;
  onClearDate?: () => void;
}

const ChatInput = memo(function ChatInput({ onSend, isStreaming, placeholder, historyDate, onClearDate }: ChatInputProps) {
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isMobileRef = useRef(false);

  useEffect(() => {
    isMobileRef.current = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  }, []);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming) return;
    if (historyDate && onClearDate) onClearDate();
    onSend(text);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  }, [input, isStreaming, historyDate, onClearDate, onSend]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (isMobileRef.current) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, []);

  const canSend = input.trim().length > 0 && !isStreaming;

  return (
    <div className="px-3 pb-16 md:pb-3 pt-1">
      <div className="glass-heavy rounded-2xl px-3 py-2 max-w-2xl mx-auto">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={historyDate ? "发送消息将返回当前对话..." : placeholder}
            rows={1}
            className="flex-1 resize-none py-2 bg-transparent text-warm-text text-sm placeholder:text-warm-text-secondary/40 focus:outline-none leading-relaxed"
          />
          <button
            onClick={handleSubmit}
            disabled={!canSend}
            className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
              canSend
                ? "bg-warm-accent text-white active:scale-95"
                : "bg-warm-text-secondary/10 text-warm-text-secondary/25"
            }`}
            style={{ touchAction: "manipulation" }}
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
});

// ── Main chat area ──

interface ChatAreaProps {
  messages: Message[];
  isStreaming: boolean;
  isLoading?: boolean;
  channel: Channel;
  onSend: (text: string) => void;
  onChangeChannel: (ch: Channel) => void;
  streamingChannels: Set<Channel>;
  groupAutoStatus?: GroupAutoStatus | null;
  onPauseGroup?: () => void;
  historyDate?: string | null;
  onDateSelect: (date: string | null) => void;
  onBack: () => void;
  logs: LogEntry[];
  onRequestLogs: (filter: string, limit: number) => void;
  onOpenSettings: () => void;
  onHideMessages?: (timestamps: string[]) => void;
  onUnhideMessages?: (timestamps: string[]) => void;
  contextReloading?: boolean;
}

export function ChatArea({
  messages, isStreaming, isLoading, channel, onSend, onChangeChannel, streamingChannels,
  groupAutoStatus, onPauseGroup, historyDate, onDateSelect, onBack,
  logs, onRequestLogs, onOpenSettings, onHideMessages, onUnhideMessages, contextReloading,
}: ChatAreaProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (!editMode) setSelectedIds(new Set());
  }, [editMode]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleConfirmEdit = () => {
    if (selectedIds.size === 0) {
      setEditMode(false);
      return;
    }
    const toHide: string[] = [];
    const toUnhide: string[] = [];
    for (const msg of messages) {
      if (!selectedIds.has(msg.id)) continue;
      if (msg.hidden) toUnhide.push(msg.timestamp);
      else toHide.push(msg.timestamp);
    }
    if (toHide.length && onHideMessages) onHideMessages(toHide);
    if (toUnhide.length && onUnhideMessages) onUnhideMessages(toUnhide);
    setEditMode(false);
  };

  const handleClearDate = useCallback(() => onDateSelect(null), [onDateSelect]);

  const selectedCount = selectedIds.size;
  const selectedHiddenCount = messages.filter((m) => selectedIds.has(m.id) && m.hidden).length;
  const selectedVisibleCount = selectedCount - selectedHiddenCount;

  const placeholder = channel === "sonnet" ? "给 Sonnet 下达任务..." : channel === "group" ? "在群聊中发言..." : "说点什么...";

  return (
    <div className="h-full flex flex-col relative overflow-hidden">
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat md:hidden" style={{ backgroundImage: "url('/bg-chat.png')" }} />
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat hidden md:block" style={{ backgroundImage: "url('/bg-chat-pc.png')" }} />
      <div className="absolute inset-0 bg-warm-bg/10 dark:bg-[#1E1814]/30" />

      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        <div className="bar-blend px-3 py-2 flex items-center gap-2">
          {editMode ? (
            <>
              <button
                onClick={() => setEditMode(false)}
                className="p-1.5 rounded-lg text-warm-text-secondary hover:text-warm-text transition-colors text-sm"
              >
                取消
              </button>
              <span className="flex-1 text-center text-sm text-warm-text-secondary">
                {selectedCount > 0 ? `已选 ${selectedCount} 条` : "选择要隐藏/恢复的消息"}
              </span>
              <button
                onClick={handleConfirmEdit}
                disabled={selectedCount === 0}
                className={`p-1.5 rounded-lg text-sm font-medium transition-colors ${
                  selectedCount > 0
                    ? "text-warm-accent hover:bg-warm-accent/10"
                    : "text-warm-text-secondary/30"
                }`}
              >
                确认
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onBack}
                className="p-1.5 rounded-lg text-warm-text-secondary hover:text-warm-text transition-colors"
              >
                <IconBack className="w-5 h-5" />
              </button>
              <ChannelTabs active={channel} onChange={onChangeChannel} streamingChannels={streamingChannels} />
              <div className="ml-auto flex items-center gap-1">
                {channel === "xiaoyu" && !historyDate && (
                  <button
                    onClick={() => setEditMode(true)}
                    className="p-2 rounded-xl text-warm-text-secondary/60 hover:text-warm-text-secondary transition-colors"
                    title="编辑上下文"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  </button>
                )}
                <ThemeToggle />
                <button
                  onClick={() => setDrawerOpen(true)}
                  className="p-2 rounded-xl text-warm-text-secondary/60 hover:text-warm-text-secondary transition-colors"
                >
                  <IconMenu className="w-4 h-4" />
                </button>
              </div>
            </>
          )}
        </div>

        {/* Group auto status */}
        {channel === "group" && groupAutoStatus?.active && onPauseGroup && (
          <GroupChatStatus status={groupAutoStatus} onPause={onPauseGroup} />
        )}

        {/* History date banner */}
        {historyDate && (
          <div className="glass mx-3 mt-2 rounded-xl px-4 py-2 flex items-center justify-between text-xs">
            <span className="text-warm-text-secondary">
              {historyDate} 的记录（{messages.length} 条）
            </span>
            <button
              onClick={() => onDateSelect(null)}
              className="text-warm-accent hover:opacity-80 transition-opacity"
            >
              返回当前
            </button>
          </div>
        )}

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 md:px-8 py-3">
          <div className="max-w-2xl mx-auto space-y-3">
            {isLoading && (
              <div className="text-center py-20 animate-fade-in">
                <div className="flex items-center justify-center gap-1.5 mb-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-warm-accent/50 animate-gentle-pulse" />
                  <span className="w-1.5 h-1.5 rounded-full bg-warm-accent/50 animate-gentle-pulse" style={{ animationDelay: "0.3s" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-warm-accent/50 animate-gentle-pulse" style={{ animationDelay: "0.6s" }} />
                </div>
                <p className="text-xs text-warm-text-secondary/40 font-light">加载中...</p>
              </div>
            )}
            {!isLoading && messages.length === 0 && (
              <div className="text-center py-20 animate-fade-in">
                <p className="text-lg text-warm-text/40 font-light">
                  {historyDate
                    ? `${historyDate}`
                    : channel === "sonnet" ? "Sonnet" : channel === "group" ? "群聊" : "小予"}
                </p>
                <p className="text-xs text-warm-text-secondary/40 mt-2 font-light">
                  {historyDate
                    ? "这一天没有聊天记录"
                    : channel === "sonnet" ? "直接下达任务" : channel === "group" ? "协作空间" : "发消息开始聊天"}
                </p>
              </div>
            )}
            {messages.map((msg) =>
              msg.isForgeMarker ? (
                <ForgeDivider key={msg.id} timestamp={msg.timestamp} label={msg.forgeLabel} />
              ) : (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  showSenderLabel={channel === "group"}
                  editMode={editMode}
                  selected={selectedIds.has(msg.id)}
                  onToggleSelect={() => toggleSelect(msg.id)}
                />
              )
            )}
            {isStreaming && messages.length > 0 && messages[messages.length - 1].role !== "assistant" && (
              <div className="flex justify-start">
                <div className="glass-light rounded-2xl px-4 py-2">
                  <div className="flex items-center gap-1.5">
                    <span className="w-1 h-1 rounded-full bg-warm-accent animate-gentle-pulse" />
                    <span className="w-1 h-1 rounded-full bg-warm-accent animate-gentle-pulse" style={{ animationDelay: "0.3s" }} />
                    <span className="w-1 h-1 rounded-full bg-warm-accent animate-gentle-pulse" style={{ animationDelay: "0.6s" }} />
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Edit mode bottom bar */}
        {editMode && selectedCount > 0 && (
          <div className="px-3 py-2">
            <div className="glass-heavy rounded-2xl px-4 py-2.5 max-w-2xl mx-auto flex items-center justify-center gap-3 text-xs">
              {selectedVisibleCount > 0 && (
                <span className="text-warm-text-secondary">
                  隐藏 {selectedVisibleCount} 条
                </span>
              )}
              {selectedHiddenCount > 0 && (
                <span className="text-warm-text-secondary">
                  恢复 {selectedHiddenCount} 条
                </span>
              )}
            </div>
          </div>
        )}

        {/* Input area */}
        {!editMode && (
          <ChatInput
            onSend={onSend}
            isStreaming={isStreaming}
            placeholder={placeholder}
            historyDate={historyDate}
            onClearDate={handleClearDate}
          />
        )}
      </div>

      {/* Context reloading overlay */}
      {contextReloading && (
        <div className="absolute inset-0 z-[55] flex items-center justify-center bg-black/10 backdrop-blur-[2px]">
          <div className="glass-heavy rounded-2xl px-6 py-4 flex flex-col items-center gap-3 shadow-lg">
            <div className="w-8 h-8 border-2 border-warm-accent/30 border-t-warm-accent rounded-full animate-spin" />
            <span className="text-sm text-warm-text-secondary">正在重载上下文...</span>
          </div>
        </div>
      )}

      {/* Drawer overlay */}
      {drawerOpen && (
        <div className="fixed inset-0 z-[60] flex justify-end" onClick={() => setDrawerOpen(false)}>
          <div
            className="absolute inset-0 bg-black/20 backdrop-blur-[2px] transition-opacity"
          />
          <div
            className="relative w-[85%] md:w-[380px] h-full bg-[#FFF8F0] dark:bg-[#1E1814] shadow-xl flex flex-col animate-slide-right"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer header */}
            <div className="px-4 py-3 flex items-center justify-between border-b border-warm-border/20">
              <span className="text-sm font-medium text-warm-text">日志</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => { setDrawerOpen(false); onOpenSettings(); }}
                  className="p-2 rounded-xl text-warm-text-secondary/60 hover:text-warm-accent transition-colors"
                  title="设置"
                >
                  <IconSettings className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setDrawerOpen(false)}
                  className="p-2 rounded-xl text-warm-text-secondary/60 hover:text-warm-text-secondary transition-colors"
                >
                  <IconClose className="w-4 h-4" />
                </button>
              </div>
            </div>
            {/* Drawer content: log panel */}
            <div className="flex-1 overflow-hidden">
              <LogPanel logs={logs} onRequestLogs={onRequestLogs} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
