"use client";

import { useEffect, useState } from "react";
import type { WeatherData } from "@/lib/types";
import { IconChat, IconBrain, IconSettings, IconLocation } from "./Icons";

interface HomeScreenProps {
  weather: WeatherData | null;
  onOpenChat: () => void;
  onOpenMemory: () => void;
  onOpenSettings: () => void;
  onRefreshWeather: () => void;
}

function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function MobileHome({ now, weather, onOpenChat, onOpenMemory, onRefreshWeather }: {
  now: Date; weather: WeatherData | null;
  onOpenChat: () => void; onOpenMemory: () => void; onRefreshWeather: () => void;
}) {
  const timeStr = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateStr = now.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
  const weekday = now.toLocaleDateString("zh-CN", { weekday: "short" });

  return (
    <div className="h-full flex flex-col relative overflow-hidden md:hidden">
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat" style={{ backgroundImage: "url('/bg-desktop.png')" }} />
      <div className="relative z-10 flex flex-col h-full px-5 pt-12 pb-16">
        <div className="flex items-start justify-between animate-fade-in">
          <div className="glass rounded-2xl px-4 py-3 min-w-[120px]">
            <div className="text-2xl font-light text-warm-text tracking-wide leading-none">{timeStr}</div>
            <div className="text-xs text-warm-text-secondary mt-1.5 font-light">{dateStr} {weekday}</div>
          </div>
          {weather ? (
            <div className="glass rounded-2xl px-4 py-3 min-w-[100px] text-right">
              <div className="text-2xl font-light text-warm-text leading-none">{weather.temp}°</div>
              <div className="flex items-center justify-end gap-1 mt-1.5">
                <IconLocation className="w-3 h-3 text-warm-text-secondary/60" />
                <span className="text-xs text-warm-text-secondary font-light">{weather.cityName || weather.text}</span>
              </div>
            </div>
          ) : (
            <button onClick={onRefreshWeather} className="glass rounded-2xl px-4 py-3 min-w-[100px] text-right">
              <div className="text-lg text-warm-text-secondary font-light">--°</div>
            </button>
          )}
        </div>
        <div className="flex-1 flex items-end pb-8">
          <div className="w-full grid grid-cols-2 gap-3 animate-slide-up" style={{ animationDelay: "0.1s", animationFillMode: "both" }}>
            <AppCard icon={<IconChat className="w-5 h-5" />} label="小予" sublabel="聊天" color="var(--accent)" onClick={onOpenChat} />
            <AppCard icon={<IconBrain className="w-5 h-5" />} label="记忆库" sublabel="ombre-brain" color="#7B8E6E" onClick={onOpenMemory} />
          </div>
        </div>
      </div>
    </div>
  );
}

function DesktopHome({ now, weather, onOpenChat, onOpenMemory, onOpenSettings, onRefreshWeather }: {
  now: Date; weather: WeatherData | null;
  onOpenChat: () => void; onOpenMemory: () => void; onOpenSettings: () => void; onRefreshWeather: () => void;
}) {
  const timeStr = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const dateStr = now.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });
  const weekday = now.toLocaleDateString("zh-CN", { weekday: "long" });

  return (
    <div className="h-full flex flex-col relative overflow-hidden hidden md:flex">
      <div className="absolute inset-0 bg-cover bg-center bg-no-repeat" style={{ backgroundImage: "url('/bg-desktop-pc.png')" }} />

      {/* Center: time + weather */}
      <div className="flex-1 flex flex-col items-center justify-center relative z-10 animate-fade-in">
        <div className="text-center">
          <div className="text-8xl font-extralight text-[#3D3229] tracking-widest leading-none" style={{ textShadow: "0 2px 12px rgba(255,255,255,0.5)" }}>
            {timeStr}
          </div>
          <div className="mt-4 text-xl font-normal text-[#3D3229] tracking-wide" style={{ textShadow: "0 1px 8px rgba(255,255,255,0.5)" }}>
            {dateStr} {weekday}
          </div>
          {weather && (
            <div className="mt-3 flex items-center justify-center gap-2 text-[#4A3A2A]" style={{ textShadow: "0 1px 6px rgba(255,255,255,0.5)" }}>
              <span className="text-lg font-normal">{weather.temp}°C</span>
              <span className="text-base">·</span>
              <span className="text-base font-normal">{weather.text}</span>
              {weather.cityName && (
                <>
                  <span className="text-base">·</span>
                  <span className="text-base font-normal">{weather.cityName}</span>
                </>
              )}
            </div>
          )}
          {!weather && (
            <button onClick={onRefreshWeather} className="mt-3 text-base text-[#5A4A3A] hover:text-[#3D3229] transition-colors">
              加载天气...
            </button>
          )}
        </div>
      </div>

      {/* Bottom: app dock */}
      <div className="relative z-10 pb-10 flex justify-center animate-slide-up" style={{ animationDelay: "0.15s", animationFillMode: "both" }}>
        <div className="flex items-center gap-4 px-6 py-3 rounded-2xl" style={{ background: "rgba(255,248,240,0.35)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)" }}>
          <DockIcon icon={<IconChat className="w-6 h-6" />} label="聊天" onClick={onOpenChat} />
          <DockIcon icon={<IconBrain className="w-6 h-6" />} label="记忆库" onClick={onOpenMemory} />
          <DockIcon icon={<IconSettings className="w-6 h-6" />} label="设置" onClick={onOpenSettings} />
        </div>
      </div>
    </div>
  );
}

function AppCard({ icon, label, sublabel, color, onClick }: {
  icon: React.ReactNode; label: string; sublabel?: string; color: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick} className="glass rounded-3xl p-5 flex flex-col items-start gap-3 text-left transition-transform active:scale-[0.97] hover:scale-[1.01] w-full">
      <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: `${color}20` }}>
        <div style={{ color }}>{icon}</div>
      </div>
      <div>
        <div className="text-sm font-medium text-warm-text">{label}</div>
        {sublabel && <div className="text-xs text-warm-text-secondary/70 mt-0.5 font-light">{sublabel}</div>}
      </div>
    </button>
  );
}

function DockIcon({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex flex-col items-center gap-1.5 px-4 py-1 text-[#5A4A3A]/70 hover:text-[#3D3229] transition-colors">
      {icon}
      <span className="text-[11px] font-light">{label}</span>
    </button>
  );
}

export function HomeScreen({ weather, onOpenChat, onOpenMemory, onOpenSettings, onRefreshWeather }: HomeScreenProps) {
  const now = useClock();

  return (
    <>
      <MobileHome now={now} weather={weather} onOpenChat={onOpenChat} onOpenMemory={onOpenMemory} onRefreshWeather={onRefreshWeather} />
      <DesktopHome now={now} weather={weather} onOpenChat={onOpenChat} onOpenMemory={onOpenMemory} onOpenSettings={onOpenSettings} onRefreshWeather={onRefreshWeather} />
    </>
  );
}
