import axios from "axios";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  timeout: 10000,
});

// Bot
export const getBotStatus = () => api.get("/api/bot/status");
export const startBot = () => api.post("/api/bot/start");
export const stopBot = () => api.post("/api/bot/stop");
export const emergencyStop = () => api.post("/api/bot/emergency-stop");
export const updateStrategy = (name: string, params?: Record<string, unknown>) =>
  api.put("/api/bot/strategy", { name, params });
export const updateSettings = (data: {
  use_ai_filter?: boolean;
  ai_confidence_threshold?: number;
  paper_trade?: boolean;
  timeframe?: string;
  max_risk_per_trade?: number;
  max_daily_loss?: number;
  max_concurrent_trades?: number;
  max_lot?: number;
}) => api.put("/api/bot/settings", data);
export const getAccount = () => api.get("/api/bot/account");
export const getBotEvents = (params?: { days?: number; event_type?: string; limit?: number }) =>
  api.get("/api/bot/events", { params });

// Positions
export const getPositions = () => api.get("/api/positions");
export const closePosition = (ticket: number) =>
  api.delete(`/api/positions/${ticket}`);

// History
export const getDailyPnl = () => api.get("/api/history/daily-pnl");
export const getTradeHistory = (params?: {
  days?: number;
  strategy?: string;
  limit?: number;
  offset?: number;
}) => api.get("/api/history/trades", { params });
export const getPerformance = (days?: number) =>
  api.get("/api/history/performance", { params: { days } });

// Strategy
export const getAvailableStrategies = () => api.get("/api/strategy/available");
export const getCurrentStrategy = () => api.get("/api/strategy/current");

// AI
export const getLatestSentiment = () => api.get("/api/ai/sentiment");
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
  timeframe?: string;
  source?: string;
  from_date?: string;
  to_date?: string;
  initial_balance?: number;
  min_trades?: number;
}) => api.post("/api/backtest/optimize", params, { timeout: 120000 });

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
  timeframe?: string;
  from_date?: string;
  to_date?: string;
  forward_bars?: number;
  tp_pips?: number;
  sl_pips?: number;
  test_size?: number;
}) => api.post("/api/ml/train", params, { timeout: 300000 });
export const getModelStatus = () => api.get("/api/ml/status");
export const mlPredict = () => api.post("/api/ml/predict");

// Macro Data
export const getMacroLatest = () => api.get("/api/macro/latest");
export const getMacroCorrelations = (days?: number) =>
  api.get("/api/macro/correlations", { params: { days } });
export const getMacroEvents = (days?: number) =>
  api.get("/api/macro/events", { params: { days } });
export const collectMacro = (from_date?: string, to_date?: string) =>
  api.post("/api/macro/collect", null, { params: { from_date, to_date }, timeout: 60000 });

// Market Data
export const getOHLCV = (timeframe: string = "M15", count: number = 200) =>
  api.get("/api/market-data/ohlcv", { params: { timeframe, count } });

// Health
export const getHealth = () => api.get("/health");

export default api;
