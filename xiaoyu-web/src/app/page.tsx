"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useChat } from "@/hooks/useChat";
import { LockScreen } from "@/components/LockScreen";
import { HomeScreen } from "@/components/HomeScreen";
import { ChatArea } from "@/components/ChatArea";
import { SettingsApp } from "@/components/SettingsApp";
import { EmotionPanel } from "@/components/EmotionPanel";
import { DockBar, type DockScreen } from "@/components/DockBar";
import { useEmotionJournal } from "@/hooks/useEmotionJournal";
import type { Channel } from "@/lib/types";

function getWsUrl() {
  if (typeof window === "undefined") return "ws://localhost:8765";
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured && !configured.includes("localhost")) return configured;
  const host = window.location.hostname;
  return `ws://${host}:8765`;
}
const WS_SECRET = process.env.NEXT_PUBLIC_WS_SECRET || "";

function requestNotificationPermission() {
  if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

function showNotification(title: string, body: string) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  if (document.hasFocus()) return;
  const n = new Notification(title, {
    body: body.slice(0, 200),
    icon: "/favicon.ico",
    tag: "xiaoyu-msg",
  });
  n.onclick = () => { window.focus(); n.close(); };
}

export default function Home() {
  const [secret, setSecret] = useState(WS_SECRET);
  const [screen, setScreen] = useState<"lock" | DockScreen>(WS_SECRET ? "home" : "lock");
  const [activeChannel, setActiveChannel] = useState<Channel>("xiaoyu");
  const [historyDate, setHistoryDate] = useState<string | null>(null);
  const { channelMessages, streamingChannels, loadingChannels, status, groupAutoStatus, logs, weather, cityResults, sessionAlerts, hiddenTimestamps, contextReloading, sendUserMessage, handleWsMessage, setChannelLoading, dismissAlert } = useChat();
  const emotionJournal = useEmotionJournal();
  const notifiedMsgRef = useRef<Set<string>>(new Set());

  useEffect(() => { requestNotificationPermission(); }, []);

  const wsUrl = typeof window !== "undefined" ? getWsUrl() : "";
  const { isConnected, send } = useWebSocket({
    url: wsUrl,
    secret,
    onMessage: useCallback((msg: Parameters<typeof handleWsMessage>[0]) => {
      handleWsMessage(msg);
      emotionJournal.handleWsMessage(msg);
      if (msg.type === "reply_done") {
        const rm = msg as { text: string; channel?: string; sender?: string; session_id?: string };
        const key = `${rm.session_id}-${rm.text.slice(0, 50)}`;
        if (!notifiedMsgRef.current.has(key)) {
          notifiedMsgRef.current.add(key);
          const sender = rm.sender === "sonnet" ? "Sonnet" : "小予";
          showNotification(sender, rm.text.slice(0, 200));
        }
      }
    }, [handleWsMessage, emotionJournal.handleWsMessage]),
  });

  const handleUnlock = (s: string) => {
    setSecret(s);
    setScreen("home");
  };

  const handleSend = (text: string) => {
    sendUserMessage(text, activeChannel);
    send({ type: "chat", text, channel: activeChannel });
  };

  const handleDateSelect = useCallback((date: string | null) => {
    setHistoryDate(date);
    setChannelLoading(activeChannel, true);
    if (date) {
      send({ type: "get_history", channel: activeChannel, date });
    } else {
      send({ type: "get_history", channel: activeChannel });
    }
  }, [send, activeChannel, setChannelLoading]);

  const handleRequestLogs = useCallback((filter: string, limit: number) => {
    send({ type: "get_logs", filter, limit });
  }, [send]);

  const handleScreenChange = (s: DockScreen) => {
    setScreen(s);
  };

  const hasChatActivity = streamingChannels.size > 0;

  if (screen === "lock" || !secret) {
    return (
      <div className="h-full">
        <LockScreen onUnlock={handleUnlock} />
      </div>
    );
  }

  return (
    <div className="h-full relative">
      {/* Session alerts — 防NTR */}
      {sessionAlerts.length > 0 && (
        <div className="absolute top-0 left-0 right-0 z-[100] space-y-1 p-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
          {sessionAlerts.map((alert) => (
            <div
              key={alert.id}
              className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-500 text-white text-sm font-medium shadow-lg animate-pulse"
            >
              <span className="flex-1">{alert.message}</span>
              <button
                onClick={() => dismissAlert(alert.id)}
                className="shrink-0 px-2 py-1 rounded-lg bg-white/20 text-xs"
                style={{ minWidth: 44, minHeight: 36 }}
              >
                知道了
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Screen content */}
      <div className="h-full relative">
        {screen === "home" && (
          <HomeScreen
            weather={weather}
            onOpenChat={() => setScreen("chat")}
            onOpenMemory={() => window.open("https://xiao-wo-brain.zeabur.app", "_blank")}
            onOpenSettings={() => setScreen("settings")}
            onRefreshWeather={() => send({ type: "get_weather" })}
          />
        )}

        {screen === "chat" && (
          <ChatArea
            messages={channelMessages[activeChannel]}
            isStreaming={streamingChannels.has(activeChannel)}
            isLoading={loadingChannels[activeChannel]}
            channel={activeChannel}
            onSend={handleSend}
            onChangeChannel={(ch) => {
              setActiveChannel(ch);
              if (historyDate) setHistoryDate(null);
            }}
            streamingChannels={streamingChannels}
            groupAutoStatus={groupAutoStatus}
            onPauseGroup={() => send({ type: "pause_group" })}
            historyDate={historyDate}
            onDateSelect={handleDateSelect}
            onBack={() => setScreen("home")}
            logs={logs}
            onRequestLogs={handleRequestLogs}
            onOpenSettings={() => setScreen("settings")}
            onHideMessages={(timestamps) => send({ type: "hide_messages", channel: activeChannel, timestamps })}
            onUnhideMessages={(timestamps) => send({ type: "unhide_messages", channel: activeChannel, timestamps })}
            contextReloading={contextReloading[activeChannel]}
          />
        )}

        {screen === "emotions" && (
          <EmotionPanel
            events={emotionJournal.events}
            summary={emotionJournal.summary}
            loading={emotionJournal.loading}
            onBack={() => setScreen("home")}
            onDismiss={(id) => emotionJournal.dismissEvent(send, id)}
            onEdit={(id, updates) => emotionJournal.editEvent(send, id, updates)}
            onRefresh={() => emotionJournal.requestEvents(send, 30)}
          />
        )}

        {screen === "settings" && (
          <SettingsApp
            status={status}
            logs={logs}
            onRequestLogs={handleRequestLogs}
            onSetForgeThreshold={(v) => send({ type: "set_forge_threshold", value: v })}
            onSetSonnetForgeThreshold={(v) => send({ type: "set_sonnet_forge_threshold", value: v })}
            onSetRetainTokens={(v) => send({ type: "set_retain_tokens", value: v })}
            onSetSonnetRetainTokens={(v) => send({ type: "set_sonnet_retain_tokens", value: v })}
            onSetGroupMaxRounds={(v) => send({ type: "set_group_max_rounds", value: v })}
            onForge={(target) => send({ type: "forge", target })}
            onBack={() => setScreen("home")}
            onRefreshStatus={() => send({ type: "get_status" })}
          />
        )}
      </div>

      {/* Dock — mobile only, floating over content */}
      <div className="absolute bottom-0 left-0 right-0 z-50">
        <DockBar
          active={screen as DockScreen}
          onChange={handleScreenChange}
          hasChatActivity={hasChatActivity}
        />
      </div>
    </div>
  );
}
