import axios from "axios";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  timeout: 10000,
});

// Add Bearer token from localStorage
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// Auth interceptor: redirect to login on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("token");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

// Bot
export const getBotStatus = (symbol?: string) =>
  api.get("/api/bot/status", { params: symbol ? { symbol } : {} });
export const startBot = (symbol?: string) =>
  api.post("/api/bot/start", null, { params: symbol ? { symbol } : {} });
export const stopBot = (symbol?: string) =>
  api.post("/api/bot/stop", null, { params: symbol ? { symbol } : {} });
export const emergencyStop = (symbol?: string) =>
  api.post("/api/bot/emergency-stop", null, { params: symbol ? { symbol } : {} });
export const updateStrategy = (name: string, params?: Record<string, unknown>, symbol?: string) =>
  api.put("/api/bot/strategy", { name, params, symbol });
export const updateSettings = (data: {
  symbol?: string;
  use_ai_filter?: boolean;
  ai_confidence_threshold?: number;
  paper_trade?: boolean;
  timeframe?: string;
  max_risk_per_trade?: number;
  max_daily_loss?: number;
  max_concurrent_trades?: number;
  max_lot?: number;
  fixed_lot?: number;
  lot_mode?: "fixed" | "auto";
}) => api.put("/api/bot/settings", data);
export const getAccount = () => api.get("/api/bot/account");
export const getBotEvents = (params?: { days?: number; event_type?: string; limit?: number }) =>
  api.get("/api/bot/events", { params });

// Positions
export const getPositions = (symbol?: string) =>
  api.get("/api/positions", { params: symbol ? { symbol } : {} });
export const closePosition = (ticket: number) =>
  api.delete(`/api/positions/${ticket}`);

// History
export const getDailyPnl = (symbol?: string) =>
  api.get("/api/history/daily-pnl", { params: symbol ? { symbol } : {} });
export const getTradeHistory = (params?: {
  days?: number;
  strategy?: string;
  symbol?: string;
  limit?: number;
  offset?: number;
}) => api.get("/api/history/trades", { params });
export const getPerformance = (days?: number, symbol?: string) =>
  api.get("/api/history/performance", { params: { days, symbol } });

// Strategy
export const getAvailableStrategies = () => api.get("/api/strategy/available");
export const getCurrentStrategy = () => api.get("/api/strategy/current");

// AI
export const getLatestSentiment = (symbol?: string) =>
  api.get("/api/ai/sentiment", { params: symbol ? { symbol } : {} });
export const getSentimentHistory = (days?: number) =>
  api.get("/api/ai/sentiment/history", { params: { days } });
export const getOptimizationReport = () =>
  api.get("/api/ai/optimization/latest");
export const runOptimization = () => api.post("/api/ai/optimization/run");
export const applyOptimization = (logId: number) =>
  api.post(`/api/ai/optimization/${logId}/apply`);

// AI Context
export const getAIContext = () => api.get("/api/ai/context");

// Backtest
export const runBacktest = (params: {
  strategy: string;
  params?: Record<string, unknown>;
  symbol?: string;
  timeframe?: string;
  count?: number;
  use_ai_filter?: boolean;
  initial_balance?: number;
  source?: string;
  from_date?: string;
  to_date?: string;
}) => api.post("/api/backtest/run", params, { timeout: 60000 });
export const runOptimize = (params: {
  strategy: string;
  param_grid: Record<string, number[]>;
  symbol?: string;
  timeframe?: string;
  source?: string;
  from_date?: string;
  to_date?: string;
  initial_balance?: number;
  min_trades?: number;
}) => api.post("/api/backtest/optimize", params, { timeout: 120000 });
export const runWalkForward = (params: {
  strategy: string;
  param_grid: Record<string, number[]>;
  n_splits?: number;
  train_pct?: number;
  symbol?: string;
  timeframe?: string;
  source?: string;
  from_date?: string;
  to_date?: string;
  initial_balance?: number;
  count?: number;
}) => api.post("/api/backtest/walk-forward", params, { timeout: 180000 });

// Agent Prompts
export const getAgentPrompts = () => api.get("/api/agent-prompts");
export const updateAgentPrompt = (agentId: string, prompt: string) =>
  api.put(`/api/agent-prompts/${agentId}`, { prompt });
export const resetAgentPrompt = (agentId: string) =>
  api.delete(`/api/agent-prompts/${agentId}`);

// Historical Data
export const collectData = (params: {
  symbol?: string;
  timeframe?: string;
  from_date: string;
  to_date: string;
}) => api.post("/api/data/collect", params, { timeout: 120000 });
export const getDataStatus = (symbol?: string) =>
  api.get("/api/data/status", { params: { symbol } });

// ML Model
export const trainModel = (params: {
  symbol?: string;
  timeframe?: string;
  from_date?: string;
  to_date?: string;
  forward_bars?: number;
  tp_pips?: number;
  sl_pips?: number;
  test_size?: number;
}) => api.post("/api/ml/train", params, { timeout: 300000 });
export const getModelStatus = (symbol?: string) =>
  api.get("/api/ml/status", { params: symbol ? { symbol } : {} });
export const mlPredict = (symbol?: string) =>
  api.post("/api/ml/predict", null, { params: symbol ? { symbol } : {} });

// Macro Data
export const getMacroLatest = () => api.get("/api/macro/latest");
export const getMacroCorrelations = (days?: number) =>
  api.get("/api/macro/correlations", { params: { days } });
export const getMacroEvents = (days?: number) =>
  api.get("/api/macro/events", { params: { days } });
export const collectMacro = (from_date?: string, to_date?: string) =>
  api.post("/api/macro/collect", null, { params: { from_date, to_date }, timeout: 60000 });

// Analytics
export const getAnalytics = (symbol?: string, days?: number) =>
  api.get("/api/analytics/performance", { params: { symbol, days } });

// Market Data
export const getOHLCV = (symbol: string = "GOLD", timeframe: string = "M15", count: number = 200) =>
  api.get("/api/market-data/ohlcv", { params: { symbol, timeframe, count } });
export const getSymbols = () => api.get("/api/market-data/symbols");

// Rollout
export const getRolloutMode = () => api.get("/api/rollout/mode");
export const setRolloutMode = (mode: string) => api.put("/api/rollout/mode", { mode });
export const getRolloutReadiness = () => api.get("/api/rollout/readiness");

// Health
export const getHealth = () => api.get("/health");

// Integration
export const getIntegrationStatus = () => api.get("/api/integration/status");
export const testIntegration = (service: string) => api.get(`/api/integration/test/${service}`);

export default api;
