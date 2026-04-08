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
}) => api.put("/api/bot/settings", data);
export const getAccount = () => api.get("/api/bot/account");

// Positions
export const getPositions = () => api.get("/api/positions");
export const closePosition = (ticket: number) =>
  api.delete(`/api/positions/${ticket}`);

// History
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

// Backtest
export const runBacktest = (params: {
  strategy: string;
  params?: Record<string, unknown>;
  timeframe?: string;
  count?: number;
  use_ai_filter?: boolean;
  initial_balance?: number;
}) => api.post("/api/backtest/run", params, { timeout: 60000 });

// Market Data
export const getOHLCV = (timeframe: string = "M15", count: number = 200) =>
  api.get("/api/market-data/ohlcv", { params: { timeframe, count } });

// Health
export const getHealth = () => api.get("/health");

export default api;
