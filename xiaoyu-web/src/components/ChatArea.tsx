"use client";

import { useEffect, useRef, useState } from "react";
import type { Channel, GroupAutoStatus, Message } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { GroupChatStatus } from "./GroupChatStatus";
import { ForgeDivider } from "./ForgeDivider";
import { IconSend, IconCalendar, IconBack } from "./Icons";
import { ChannelTabs } from "./ChannelTabs";

interface ChatAreaProps {
  messages: Message[];
  isStreaming: boolean;
  channel: Channel;
  onSend: (text: string) => void;
  onChangeChannel: (ch: Channel) => void;
  streamingChannels: Set<Channel>;
  groupAutoStatus?: GroupAutoStatus | null;
  onPauseGroup?: () => void;
  historyDate?: string | null;
  onDateSelect: (date: string | null) => void;
  onBack: () => void;
}

export function ChatArea({
  messages, isStreaming, channel, onSend, onChangeChannel, streamingChannels,
  groupAutoStatus, onPauseGroup, historyDate, onDateSelect, onBack,
}: ChatAreaProps) {
  const [input, setInput] = useState("");
  const [showDatePicker, setShowDatePicker] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    if (historyDate) onDateSelect(null);
    onSend(text);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    if (val) {
      onDateSelect(val);
      setShowDatePicker(false);
    }
  };

  const placeholder = channel === "sonnet" ? "给 Sonnet 下达任务..." : channel === "group" ? "在群聊中发言..." : "说点什么...";

  return (
    <div className="h-full flex flex-col relative overflow-hidden">
      {/* Chat background - mobile vs desktop */}
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat md:hidden" style={{ backgroundImage: "url('/bg-chat.png')" }} />
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat hidden md:block" style={{ backgroundImage: "url('/bg-chat-pc.png')" }} />
      <div className="absolute inset-0 bg-warm-bg/10 dark:bg-[#1E1814]/30" />

      <div className="relative z-10 flex flex-col h-full">
        {/* Header */}
        <div className="bar-blend px-3 py-2 flex items-center gap-2">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg text-warm-text-secondary hover:text-warm-text transition-colors"
          >
            <IconBack className="w-5 h-5" />
          </button>
          <ChannelTabs active={channel} onChange={onChangeChannel} streamingChannels={streamingChannels} />
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
            {messages.length === 0 && (
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
                <MessageBubble key={msg.id} message={msg} showSenderLabel={channel === "group"} />
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

        {/* Input area — extra bottom padding for mobile dock */}
        <div className="px-3 pb-16 md:pb-3 pt-1">
          <div className="glass-heavy rounded-2xl px-3 py-2 max-w-2xl mx-auto">
            <div className="flex items-end gap-2">
              <div className="relative">
                <button
                  onClick={() => setShowDatePicker(!showDatePicker)}
                  className={`p-2 rounded-xl transition-colors ${
                    showDatePicker || historyDate
                      ? "text-warm-accent"
                      : "text-warm-text-secondary/50 hover:text-warm-text-secondary"
                  }`}
                >
                  <IconCalendar className="w-4.5 h-4.5" />
                </button>
                {showDatePicker && (
                  <div className="absolute bottom-full mb-2 left-0 glass rounded-xl p-3 z-10 animate-scale-in">
                    <input
                      type="date"
                      onChange={handleDateChange}
                      max={`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}-${String(new Date().getDate()).padStart(2, '0')}`}
                      className="bg-white/30 dark:bg-black/20 border border-warm-border/30 rounded-lg px-3 py-2 text-sm text-warm-text focus:outline-none focus:border-warm-accent/50"
                      autoFocus
                    />
                  </div>
                )}
              </div>
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
                disabled={!input.trim() || isStreaming}
                className={`p-2 rounded-xl transition-all ${
                  input.trim() && !isStreaming
                    ? "text-warm-accent hover:bg-warm-accent/10"
                    : "text-warm-text-secondary/20"
                }`}
              >
                <IconSend className="w-4.5 h-4.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
