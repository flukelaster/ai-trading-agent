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
  enable_auto_strategy_switch?: boolean;
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
export const runOptimization = () => api.post("/api/ai/optimization/run", null, { timeout: 120000 });
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
export const getDriftReport = (symbol?: string) =>
  api.get("/api/ml/drift", { params: symbol ? { symbol } : {} });
export const getCalibration = (symbol?: string) =>
  api.get("/api/ml/calibration", { params: symbol ? { symbol } : {} });

// Monte Carlo
export const runMonteCarlo = (params: {
  strategy: string; symbol?: string; timeframe?: string;
  n_simulations?: number; initial_balance?: number;
  source?: string; from_date?: string; to_date?: string;
  count?: number; params?: Record<string, unknown>;
}) => api.post("/api/backtest/monte-carlo", params, { timeout: 120000 });

// Statistical Validation
export const runCointegration = (params: {
  symbol_a: string; symbol_b: string; timeframe?: string; count?: number; source?: string;
}) => api.get("/api/backtest/cointegration", { params, timeout: 30000 });
export const runPermutationTest = (params: {
  strategy: string; params?: Record<string, unknown>;
  symbol?: string; timeframe?: string; n_permutations?: number;
  source?: string; from_date?: string; to_date?: string; count?: number;
  include_costs?: boolean;
}) => api.post("/api/backtest/permutation-test", params, { timeout: 300000 });

export const runOverfittingScore = (params: {
  strategy: string; symbol?: string; timeframe?: string;
  source?: string; count?: number;
}) => api.post("/api/backtest/overfitting-score", params, { timeout: 300000 });

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

// Quant
export const getQuantVaR = () => api.get("/api/quant/var");
export const getQuantRegime = () => api.get("/api/quant/regime");
export const getQuantCorrelation = () => api.get("/api/quant/correlation");
export const getQuantVolatility = () => api.get("/api/quant/volatility");
export const getQuantPortfolio = () => api.get("/api/quant/portfolio");
export const getQuantSignals = () => api.get("/api/quant/signals");
export const runStressTest = (scenario: string = "all") =>
  api.post("/api/quant/stress-test", null, { params: { scenario }, timeout: 60000 });

// Bot management
export const resetPeakBalance = () => api.post("/api/bot/reset-peak");

// Health
export const getHealth = () => api.get("/health");

// Integration
export const getIntegrationStatus = () => api.get("/api/integration/status");
export const testIntegration = (service: string) => api.get(`/api/integration/test/${service}`);

// Admin
export const archiveTrades = (before: string) => api.post("/api/admin/trades/archive", null, { params: { before } });
export const unarchiveTrades = (before: string) => api.post("/api/admin/trades/unarchive", null, { params: { before } });
export const getArchiveCount = () => api.get("/api/admin/trades/archive-count");

// Symbol Config
export type AssetClass =
  | "forex"
  | "metal"
  | "energy"
  | "index"
  | "crypto"
  | "stock";

export const ASSET_CLASSES: AssetClass[] = [
  "forex",
  "metal",
  "energy",
  "index",
  "crypto",
  "stock",
];

export interface SymbolConfig {
  symbol: string;
  display_name: string;
  broker_alias: string | null;
  asset_class: AssetClass;
  is_enabled: boolean;
  default_timeframe: string;
  pip_value: number;
  default_lot: number;
  max_lot: number;
  price_decimals: number;
  sl_atr_mult: number;
  tp_atr_mult: number;
  contract_size: number;
  ml_tp_pips: number;
  ml_sl_pips: number;
  ml_forward_bars: number;
  ml_timeframe: string;
  ml_status: string;
  ml_last_trained_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export type SymbolConfigInput = Omit<
  SymbolConfig,
  "is_enabled" | "ml_status" | "ml_last_trained_at" | "created_at" | "updated_at"
>;

export interface SymbolSpec {
  symbol: string;
  digits: number;
  point: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
  trade_contract_size: number;
  trade_tick_size: number;
  trade_tick_value: number;
  visible: boolean;
}

export const listSymbolConfigs = () => api.get<SymbolConfig[]>("/api/symbols");
export const getSymbolConfig = (symbol: string) =>
  api.get<SymbolConfig>(`/api/symbols/${symbol}`);
export const createSymbolConfig = (input: SymbolConfigInput) =>
  api.post<SymbolConfig>("/api/symbols", input);
export const updateSymbolConfig = (symbol: string, input: Omit<SymbolConfigInput, "symbol">) =>
  api.put<SymbolConfig>(`/api/symbols/${symbol}`, input);
export const deleteSymbolConfig = (symbol: string) =>
  api.delete<{ status: string; symbol: string }>(`/api/symbols/${symbol}`);
export const toggleSymbolConfig = (symbol: string) =>
  api.post<SymbolConfig>(`/api/symbols/${symbol}/toggle`);
export const validateSymbolConfig = (symbol: string) =>
  api.post<{ ok: boolean; message: string; spec: SymbolSpec | null }>(
    `/api/symbols/${symbol}/validate`,
  );
export const retrainSymbolConfig = (symbol: string) =>
  api.post<{ status: string; symbol: string }>(`/api/symbols/${symbol}/retrain`);
export const getSymbolMlStatus = (symbol: string) =>
  api.get<{ symbol: string; status: string; last_trained_at: string | null }>(
    `/api/symbols/${symbol}/ml-status`,
  );

// AI usage monitoring
export const getAIUsageSummary = (days: number) =>
  api.get("/api/ai-usage/summary", { params: { days } });
export const getAIUsageTimeseries = (days: number, granularity: "day" | "hour" = "day") =>
  api.get("/api/ai-usage/timeseries", { params: { days, granularity } });
export const getAIUsageBreakdown = (days: number) =>
  api.get("/api/ai-usage/breakdown", { params: { days } });
export const getAIUsageRecent = (limit = 50) =>
  api.get("/api/ai-usage/recent", { params: { limit } });

export default api;
