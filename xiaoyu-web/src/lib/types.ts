export type Channel = "xiaoyu" | "group" | "sonnet";
export type Sender = "xiaoyu" | "sonnet" | "deepseek" | "user";

export interface ToolCall {
  name: string;
  input: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  thinking?: string;
  toolCalls?: ToolCall[];
  isStreaming: boolean;
  isForgeMarker?: boolean;
  forgeLabel?: string;
  timestamp: string;
  channel: Channel;
  sender: Sender;
  hidden?: boolean;
}

export interface Usage {
  input_tokens?: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
  output_tokens?: number;
}

export interface QuotaData {
  window_input_tokens: number;
  window_output_tokens: number;
  limit: number;
  percentage: number;
  window_start: number;
  record_count: number;
  refresh_remaining_seconds: number;
}

export interface WeatherForecast {
  date: string;
  textDay: string;
  textNight: string;
  tempMin: string;
  tempMax: string;
  iconDay: string;
}

export interface WeatherData {
  cityName: string;
  temp: string;
  feelsLike: string;
  text: string;
  icon: string;
  humidity: string;
  windDir: string;
  windScale: string;
  precip: string;
  vis: string;
  updateTime: string;
  forecast: WeatherForecast[];
}

export interface RateLimitInfo {
  status: string;
  resetsAt: number;
  rateLimitType: string;
  overageStatus?: string;
  isUsingOverage?: boolean;
}

export interface StatusData {
  session_id?: string;
  sonnet_session_id?: string;
  usage: Usage;
  total_input: number;
  sonnet_usage?: Usage;
  sonnet_total_input?: number;
  forge_threshold: number;
  sonnet_forge_threshold?: number;
  retain_tokens?: number;
  sonnet_retain_tokens?: number;
  cost_session_total: number;
  cost_last_turn: number;
  next_wake?: string;
  last_chat_time?: string;
  quota?: QuotaData;
  weekly_quota?: QuotaData;
  rate_limit_info?: RateLimitInfo;
  weather?: WeatherData;
  group_max_rounds?: number;
}

// WS message types
export type WsUpMessage =
  | { type: "auth"; secret: string }
  | { type: "chat"; text: string; channel?: Channel }
  | { type: "get_status" }
  | { type: "regenerate"; channel?: Channel }
  | { type: "set_forge_threshold"; value: number }
  | { type: "set_sonnet_forge_threshold"; value: number }
  | { type: "set_retain_tokens"; value: number }
  | { type: "set_sonnet_retain_tokens"; value: number }
  | { type: "set_quota_limit"; value: number }
  | { type: "set_weekly_quota_limit"; value: number }
  | { type: "set_group_max_rounds"; value: number }
  | { type: "forge"; target: "xiaoyu" | "sonnet" }
  | { type: "pause_group" }
  | { type: "get_history"; channel?: Channel; date?: string }
  | { type: "get_logs"; filter?: string; limit?: number }
  | { type: "get_weather" }
  | { type: "search_city"; query: string }
  | { type: "set_weather_city"; city_id: string }
  | { type: "ping" }
  | { type: "get_emotion_events"; days?: number }
  | { type: "emotion_dismiss"; id: number }
  | { type: "emotion_edit"; id: number; updates: Partial<EmotionEvent> }
  | { type: "hide_messages"; channel: Channel; timestamps: string[] }
  | { type: "unhide_messages"; channel: Channel; timestamps: string[] };

export interface LogEntry {
  timestamp: string;
  level: string;
  category: string;
  message: string;
  detail?: Record<string, unknown>;
}

export interface GroupAutoStatus {
  active: boolean;
  round: number;
  max_rounds: number;
  reason?: string;
}

export type WsDownMessage =
  | { type: "auth_ok" }
  | { type: "stream_text"; text: string; full_text: string; channel?: Channel; sender?: Sender }
  | { type: "stream_thinking"; text: string; full_thinking: string; channel?: Channel; sender?: Sender }
  | { type: "tool_use"; name: string; input: string; channel?: Channel; sender?: Sender }
  | { type: "reply_done"; text: string; thinking: string; usage: Usage; total_input: number; cost_this_turn: number; cost_session_total?: number; session_id: string; channel?: Channel; sender?: Sender }
  | ({ type: "status" } & StatusData)
  | { type: "user_message"; text: string; channel?: Channel; sender?: Sender; timestamp: string }
  | { type: "forge_occurred"; old_session_id: string; new_session_id: string; total_input_before: number; target?: string }
  | { type: "forge_result"; success: boolean; target?: string; new_session_id?: string; error?: string }
  | { type: "regenerate_start"; channel?: Channel }
  | { type: "group_paused" }
  | ({ type: "group_auto_status" } & GroupAutoStatus)
  | { type: "log"; timestamp: string; level: string; category: string; message: string; detail?: Record<string, unknown> }
  | { type: "history"; messages: Array<{ role: string; text: string; thinking?: string; tool_calls?: ToolCall[]; timestamp: string }>; channel?: Channel; date?: string }
  | { type: "logs"; entries: LogEntry[] }
  | { type: "weather"; data: WeatherData | null }
  | { type: "city_results"; results: Array<{ id: string; name: string; adm1: string; adm2: string }> }
  | { type: "message_correct"; text: string; channel?: Channel; sender?: Sender }
  | { type: "error"; message: string; channel?: Channel }
  | { type: "session_alert"; alert: string; message: string; channel?: Channel; expected?: string; actual?: string; old_session?: string; new_session?: string }
  | { type: "emotion_events"; events: EmotionEvent[]; summary: EmotionSummary[] }
  | { type: "emotion_events_new"; events: EmotionEvent[] }
  | { type: "emotion_event_updated"; id: number; [key: string]: unknown }
  | { type: "hide_result"; success: boolean; channel: Channel; hidden_timestamps: string[]; error?: string }
  | { type: "unhide_result"; success: boolean; channel: Channel; unhidden_timestamps: string[]; error?: string }
  | { type: "context_reloading"; channel: Channel }
  | { type: "context_reloaded"; channel: Channel };

export interface EmotionEvent {
  id: number;
  timestamp: string;
  subject: "user" | "xiaoyu";
  emotion: string;
  intensity: number;
  cause: string;
  source_excerpt?: string;
  source_channel: string;
  state: "open" | "resolved" | "dismissed";
  resolved_at?: string;
}

export interface EmotionSummary {
  subject: string;
  emotion: string;
  count: number;
  avg_intensity: number;
}
