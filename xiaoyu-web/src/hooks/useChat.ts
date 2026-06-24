"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Channel, GroupAutoStatus, LogEntry, Message, Sender, StatusData, WeatherData, WsDownMessage } from "@/lib/types";

type ChannelMessages = Record<Channel, Message[]>;
type ChannelLoading = Record<Channel, boolean>;

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
  const [loadingChannels, setLoadingChannels] = useState<ChannelLoading>({ xiaoyu: true, group: true, sonnet: true });
  const [sessionAlerts, setSessionAlerts] = useState<Array<{ id: string; alert: string; message: string; channel?: string; timestamp: string }>>([]);
  const [hiddenTimestamps, setHiddenTimestamps] = useState<Record<Channel, Set<string>>>({
    xiaoyu: new Set(), group: new Set(), sonnet: new Set(),
  });
  const [contextReloading, setContextReloading] = useState<Record<Channel, boolean>>({
    xiaoyu: false, group: false, sonnet: false,
  });
  const idCounter = useRef(0);

  const streamRef = useRef<Record<string, { text: string; thinking: string }>>({});
  const streamTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const STREAM_FLUSH_MS = 50;

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

  const flushStreams = useCallback(() => {
    const pending = streamRef.current;
    const keys = Object.keys(pending);
    if (keys.length === 0) return;
    for (const key of keys) {
      const [ch, sender] = key.split(":") as [Channel, string];
      const data = pending[key];
      updateChannel(ch, (prev) => {
        const last = prev[prev.length - 1];
        if (last?.role === "assistant" && last.isStreaming && last.sender === sender) {
          return [...prev.slice(0, -1), {
            ...last,
            text: data.text || last.text,
            thinking: data.thinking || last.thinking,
          }];
        }
        return prev;
      });
    }
  }, []);

  const handleWsMessage = useCallback((msg: WsDownMessage) => {
    switch (msg.type) {
      case "user_message": {
        const um = msg as WsDownMessage & { text: string; timestamp: string; channel?: Channel; sender?: string };
        const ch = um.channel || "xiaoyu";
        const umSender = (um.sender || "user") as Sender;
        const role = umSender === "user" ? "user" as const : "assistant" as const;
        updateChannel(ch, (prev) => {
          if (prev.length > 0 && prev[prev.length - 1].text === um.text && prev[prev.length - 1].sender === umSender) {
            return prev;
          }
          return [...prev, {
            id: nextId(),
            role,
            text: um.text,
            isStreaming: false,
            timestamp: um.timestamp,
            channel: ch,
            sender: umSender,
          }];
        });
        if (role === "user") setStreaming(ch, true);
        break;
      }
      case "message_correct": {
        const mc = msg as WsDownMessage & { text: string; channel?: Channel; sender?: string };
        const ch = mc.channel || "xiaoyu";
        const mcSender = mc.sender || "xiaoyu";
        updateChannel(ch, (prev) => {
          const idx = prev.length - 1;
          while (idx >= 0) {
            if (prev[idx].role === "assistant" && prev[idx].sender === mcSender) {
              const updated = [...prev];
              updated[idx] = { ...updated[idx], text: mc.text };
              return updated;
            }
            break;
          }
          return prev;
        });
        break;
      }
      case "stream_text": {
        const ch = msg.channel || "xiaoyu";
        const sender = msg.sender || ch;
        const key = `${ch}:${sender}`;
        if (!streamRef.current[key]) streamRef.current[key] = { text: "", thinking: "" };
        streamRef.current[key].text = msg.full_text;
        if (!streamTimerRef.current) {
          streamTimerRef.current = setTimeout(() => {
            streamTimerRef.current = null;
            flushStreams();
          }, STREAM_FLUSH_MS);
        }
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming && last.sender === sender) return prev;
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
        const key = `${ch}:${sender}`;
        if (!streamRef.current[key]) streamRef.current[key] = { text: "", thinking: "" };
        streamRef.current[key].thinking = msg.full_thinking;
        if (!streamTimerRef.current) {
          streamTimerRef.current = setTimeout(() => {
            streamTimerRef.current = null;
            flushStreams();
          }, STREAM_FLUSH_MS);
        }
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming && last.sender === sender) return prev;
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
        const sender = msg.sender || ch;
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming && last.sender === sender) {
            const existing = last.toolCalls || [];
            const dup = existing.some((tc) => tc.name === msg.name && tc.input === msg.input);
            if (dup) return prev;
            const toolCalls = [...existing, { name: msg.name, input: msg.input }];
            return [...prev.slice(0, -1), { ...last, toolCalls }];
          }
          return [...prev, {
            id: nextId(),
            role: "assistant" as const,
            text: "",
            toolCalls: [{ name: msg.name, input: msg.input }],
            isStreaming: true,
            timestamp: new Date().toISOString(),
            channel: ch,
            sender: sender as Message["sender"],
          }];
        });
        break;
      }
      case "reply_done": {
        const ch = msg.channel || "xiaoyu";
        if (streamTimerRef.current) {
          clearTimeout(streamTimerRef.current);
          streamTimerRef.current = null;
        }
        const senderKey = `${ch}:${msg.sender || ch}`;
        delete streamRef.current[senderKey];
        updateChannel(ch, (prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.isStreaming) {
            const fullText = msg.text || "";
            const parts = fullText.split(/\n\n+/).map((p: string) => p.trim()).filter(Boolean);
            if (parts.length <= 1) {
              return [
                ...prev.slice(0, -1),
                { ...last, text: fullText, thinking: msg.thinking || last.thinking, isStreaming: false },
              ];
            }
            const newMsgs: Message[] = parts.map((part: string, i: number) => ({
              ...last,
              id: i === 0 ? last.id : nextId(),
              text: part,
              thinking: i === 0 ? (msg.thinking || last.thinking) : undefined,
              toolCalls: i === 0 ? last.toolCalls : undefined,
              isStreaming: false,
            }));
            return [...prev.slice(0, -1), ...newMsgs];
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
        const hm = msg as WsDownMessage & { messages: Array<{ role: string; text: string; thinking?: string; tool_calls?: Array<{ name: string; input: string }>; timestamp: string; sender?: string; hidden?: boolean }>; channel?: Channel; hidden_timestamps?: string[] };
        const ch = hm.channel || "xiaoyu";
        if (hm.hidden_timestamps?.length) {
          setHiddenTimestamps((prev) => {
            const next = { ...prev };
            next[ch] = new Set([...prev[ch], ...(hm.hidden_timestamps || [])]);
            return next;
          });
        }
        const defaultSender: Sender = ch === "sonnet" ? "sonnet" : "xiaoyu";
        const historyMessages: Message[] = [];
        for (const m of hm.messages) {
          const sender = (m.sender as Sender) || (m.role === "user" ? "user" : defaultSender);
          const base = {
            role: m.role as "user" | "assistant",
            isStreaming: false,
            timestamp: m.timestamp,
            channel: ch,
            sender,
            hidden: m.hidden || false,
          };
          if (m.role === "assistant" && m.text) {
            const parts = m.text.split(/\n\n+/).map((p: string) => p.trim()).filter(Boolean);
            if (parts.length > 1) {
              parts.forEach((part: string, i: number) => {
                historyMessages.push({
                  ...base,
                  id: nextId(),
                  text: part,
                  thinking: i === 0 ? m.thinking : undefined,
                  toolCalls: i === 0 ? m.tool_calls : undefined,
                });
              });
              continue;
            }
          }
          historyMessages.push({ ...base, id: nextId(), text: m.text, thinking: m.thinking, toolCalls: m.tool_calls });
        }
        updateChannel(ch, () => historyMessages);
        setLoadingChannels((prev) => ({ ...prev, [ch]: false }));
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
      case "session_alert": {
        const sa = msg as { alert: string; message: string; channel?: string; timestamp?: string };
        setSessionAlerts((prev) => [...prev, {
          id: `alert-${Date.now()}`,
          alert: sa.alert,
          message: sa.message,
          channel: sa.channel,
          timestamp: new Date().toISOString(),
        }]);
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
      case "hide_result": {
        const hr = msg as { success: boolean; channel: Channel; hidden_timestamps: string[] };
        if (hr.success && hr.hidden_timestamps?.length) {
          const ch = hr.channel || "xiaoyu";
          setHiddenTimestamps((prev) => {
            const next = { ...prev };
            next[ch] = new Set([...prev[ch], ...hr.hidden_timestamps]);
            return next;
          });
          updateChannel(ch, (prev) =>
            prev.map((m) => hr.hidden_timestamps.includes(m.timestamp) ? { ...m, hidden: true } : m)
          );
        }
        break;
      }
      case "unhide_result": {
        const ur = msg as { success: boolean; channel: Channel; unhidden_timestamps: string[] };
        if (ur.success && ur.unhidden_timestamps?.length) {
          const ch = ur.channel || "xiaoyu";
          setHiddenTimestamps((prev) => {
            const next = { ...prev };
            const s = new Set(prev[ch]);
            for (const ts of ur.unhidden_timestamps) s.delete(ts);
            next[ch] = s;
            return next;
          });
          updateChannel(ch, (prev) =>
            prev.map((m) => ur.unhidden_timestamps.includes(m.timestamp) ? { ...m, hidden: false } : m)
          );
        }
        break;
      }
      case "context_reloading": {
        const ch = (msg as { channel: Channel }).channel || "xiaoyu";
        setContextReloading((prev) => ({ ...prev, [ch]: true }));
        break;
      }
      case "context_reloaded": {
        const ch = (msg as { channel: Channel }).channel || "xiaoyu";
        setContextReloading((prev) => ({ ...prev, [ch]: false }));
        break;
      }
    }
  }, []);

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => saveMessages(channelMessages), 1000);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
  }, [channelMessages]);

  const setChannelLoading = useCallback((ch: Channel, val: boolean) => {
    setLoadingChannels((prev) => ({ ...prev, [ch]: val }));
  }, []);

  const dismissAlert = useCallback((id: string) => {
    setSessionAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  return { channelMessages, streamingChannels, loadingChannels, status, groupAutoStatus, logs, weather, cityResults, sessionAlerts, hiddenTimestamps, contextReloading, sendUserMessage, handleWsMessage, setChannelLoading, dismissAlert };
}
