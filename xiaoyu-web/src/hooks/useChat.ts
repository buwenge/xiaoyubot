"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Channel, GroupAutoStatus, LogEntry, Message, Sender, StatusData, WeatherData, WsDownMessage } from "@/lib/types";

type ChannelMessages = Record<Channel, Message[]>;

const STORAGE_KEY = "xiaoyu_chat_messages";
const MAX_STORED_PER_CHANNEL = 200;

function loadStoredMessages(): ChannelMessages {
  if (typeof window === "undefined") return { xiaoyu: [], group: [], sonnet: [] };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.xiaoyu && parsed.group && parsed.sonnet) return parsed;
    }
  } catch {}
  return { xiaoyu: [], group: [], sonnet: [] };
}

function saveMessages(messages: ChannelMessages) {
  try {
    const trimmed: ChannelMessages = {
      xiaoyu: messages.xiaoyu.slice(-MAX_STORED_PER_CHANNEL),
      group: messages.group.slice(-MAX_STORED_PER_CHANNEL),
      sonnet: messages.sonnet.slice(-MAX_STORED_PER_CHANNEL),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {}
}

export function useChat() {
  const [channelMessages, setChannelMessages] = useState<ChannelMessages>(loadStoredMessages);
  const [streamingChannels, setStreamingChannels] = useState<Set<Channel>>(new Set());
  const [status, setStatus] = useState<StatusData | null>(null);
  const [groupAutoStatus, setGroupAutoStatus] = useState<GroupAutoStatus | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [cityResults, setCityResults] = useState<Array<{ id: string; name: string; adm1: string; adm2: string }>>([]);
  const idCounter = useRef(0);

  const nextId = () => `msg-${++idCounter.current}`;

  const updateChannel = (channel: Channel, updater: (msgs: Message[]) => Message[]) => {
    setChannelMessages((prev) => ({
      ...prev,
      [channel]: updater(prev[channel]),
    }));
  };

  const setStreaming = (channel: Channel, val: boolean) => {
    setStreamingChannels((prev) => {
      const next = new Set(prev);
      if (val) next.add(channel);
      else next.delete(channel);
      return next;
    });
  };

  const sendUserMessage = useCallback((text: string, channel: Channel = "xiaoyu") => {
    const msg: Message = {
      id: nextId(),
      role: "user",
      text,
      isStreaming: false,
      timestamp: new Date().toISOString(),
      channel,
      sender: "user",
    };
    updateChannel(channel, (prev) => [...prev, msg]);
    setStreaming(channel, true);
  }, []);

  const handleWsMessage = useCallback((msg: WsDownMessage) => {
    switch (msg.type) {
      case "user_message": {
        const um = msg as WsDownMessage & { text: string; timestamp: string; channel?: Channel };
        const ch = um.channel || "xiaoyu";
        updateChannel(ch, (prev) => {
          if (prev.length > 0 && prev[prev.length - 1].role === "user" && prev[prev.length - 1].text === um.text) {
            return prev;
          }
          return [...prev, {
            id: nextId(),
            role: "user" as const,
            text: um.text,
            isStreaming: false,
            timestamp: um.timestamp,
            channel: ch,
            sender: "user" as const,
          }];
        });
        setStreaming(ch, true);
        break;
      }
      case "stream_text": {
        const ch = msg.channel || "xiaoyu";
        const sender = msg.sender || ch;
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming && last.sender === sender) {
            return [...prev.slice(0, -1), { ...last, text: msg.full_text }];
          }
          return [...prev, {
            id: nextId(),
            role: "assistant" as const,
            text: msg.full_text,
            isStreaming: true,
            timestamp: new Date().toISOString(),
            channel: ch,
            sender: sender as Message["sender"],
          }];
        });
        break;
      }
      case "stream_thinking": {
        const ch = msg.channel || "xiaoyu";
        const sender = msg.sender || ch;
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming && last.sender === sender) {
            return [...prev.slice(0, -1), { ...last, thinking: msg.full_thinking }];
          }
          return [...prev, {
            id: nextId(),
            role: "assistant" as const,
            text: "",
            thinking: msg.full_thinking,
            isStreaming: true,
            timestamp: new Date().toISOString(),
            channel: ch,
            sender: sender as Message["sender"],
          }];
        });
        break;
      }
      case "tool_use": {
        const ch = msg.channel || "xiaoyu";
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            const existing = last.toolCalls || [];
            const dup = existing.some((tc) => tc.name === msg.name && tc.input === msg.input);
            if (dup) return prev;
            const toolCalls = [...existing, { name: msg.name, input: msg.input }];
            return [...prev.slice(0, -1), { ...last, toolCalls }];
          }
          return prev;
        });
        break;
      }
      case "reply_done": {
        const ch = msg.channel || "xiaoyu";
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...last, text: msg.text, thinking: msg.thinking || last.thinking, isStreaming: false },
            ];
          }
          return prev;
        });
        setStreaming(ch, false);
        setStatus((prev) => ({
          ...(prev || {} as StatusData),
          session_id: ch === "xiaoyu" ? msg.session_id : prev?.session_id,
          sonnet_session_id: ch === "sonnet" ? msg.session_id : prev?.sonnet_session_id,
          usage: ch === "xiaoyu" ? msg.usage : (prev?.usage || {}),
          total_input: ch === "xiaoyu" ? msg.total_input : (prev?.total_input || 0),
          sonnet_usage: ch === "sonnet" ? msg.usage : prev?.sonnet_usage,
          sonnet_total_input: ch === "sonnet" ? msg.total_input : prev?.sonnet_total_input,
          forge_threshold: prev?.forge_threshold || 195000,
          cost_session_total: msg.cost_session_total ?? ((prev?.cost_session_total || 0) + msg.cost_this_turn),
          cost_last_turn: msg.cost_this_turn,
        }));
        break;
      }
      case "status": {
        const { type, ...rest } = msg;
        setStatus(rest as StatusData);
        if ((rest as StatusData).weather) {
          setWeather((rest as StatusData).weather!);
        }
        break;
      }
      case "weather": {
        const wm = msg as { data: WeatherData | null };
        if (wm.data) setWeather(wm.data);
        break;
      }
      case "city_results": {
        const cr = msg as { results: Array<{ id: string; name: string; adm1: string; adm2: string }> };
        setCityResults(cr.results);
        break;
      }
      case "regenerate_start": {
        const ch = (msg as { channel?: Channel }).channel || "xiaoyu";
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant") {
            return [...prev.slice(0, -1), { ...last, isStreaming: true, text: "", thinking: "", toolCalls: [] }];
          }
          return prev;
        });
        setStreaming(ch, true);
        break;
      }
      case "forge_occurred": {
        const fe = msg as WsDownMessage & { channel?: Channel };
        const ch = fe.channel || "xiaoyu";
        const label = ch === "sonnet" ? "Sonnet" : "小予";
        const marker: Message = {
          id: nextId(),
          role: "assistant" as const,
          text: "",
          isStreaming: false,
          isForgeMarker: true,
          forgeLabel: label,
          timestamp: new Date().toISOString(),
          channel: ch,
          sender: ch as Sender,
        };
        updateChannel(ch, (prev) => [...prev, marker]);
        updateChannel("group", (prev) => [...prev, { ...marker, id: nextId(), channel: "group" }]);
        break;
      }
      case "history": {
        const hm = msg as WsDownMessage & { messages: Array<{ role: string; text: string; thinking?: string; tool_calls?: Array<{ name: string; input: string }>; timestamp: string; sender?: string }>; channel?: Channel };
        const ch = hm.channel || "xiaoyu";
        const defaultSender: Sender = ch === "sonnet" ? "sonnet" : "xiaoyu";
        const historyMessages: Message[] = hm.messages.map((m) => ({
          id: nextId(),
          role: m.role as "user" | "assistant",
          text: m.text,
          thinking: m.thinking,
          toolCalls: m.tool_calls,
          isStreaming: false,
          timestamp: m.timestamp,
          channel: ch,
          sender: (m.sender as Sender) || (m.role === "user" ? "user" : defaultSender),
        }));
        updateChannel(ch, () => historyMessages);
        break;
      }
      case "log": {
        const entry: LogEntry = {
          timestamp: (msg as { timestamp: string }).timestamp,
          level: (msg as { level: string }).level,
          category: (msg as { category: string }).category,
          message: (msg as { message: string }).message,
        };
        setLogs((prev) => [...prev.slice(-199), entry]);
        break;
      }
      case "logs": {
        const { entries } = msg as { entries: LogEntry[] };
        setLogs(entries);
        break;
      }
      case "group_auto_status": {
        const gas = msg as WsDownMessage & GroupAutoStatus;
        setGroupAutoStatus({ active: gas.active, round: gas.round, max_rounds: gas.max_rounds, reason: gas.reason });
        break;
      }
      case "group_paused": {
        setGroupAutoStatus((prev) => prev ? { ...prev, active: false, reason: "paused" } : null);
        break;
      }
      case "error": {
        const ch = (msg as { channel?: Channel }).channel || "xiaoyu";
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...last, text: last.text + `\n\n[error] ${msg.message}`, isStreaming: false },
            ];
          }
          return prev;
        });
        setStreaming(ch, false);
        break;
      }
    }
  }, []);

  useEffect(() => {
    saveMessages(channelMessages);
  }, [channelMessages]);

  return { channelMessages, streamingChannels, status, groupAutoStatus, logs, weather, cityResults, sendUserMessage, handleWsMessage };
}
