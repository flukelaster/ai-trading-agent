import { create } from "zustand";

type Position = {
  ticket: number;
  symbol: string;
  type: string;
  lot: number;
  open_price: number;
  current_price: number;
  sl: number;
  tp: number;
  profit: number;
  open_time: string;
};

type Sentiment = {
  label: string;
  score: number;
  confidence: number;
  key_factors: string[];
  source_count: number;
  analyzed_at: string;
};

type BotStatus = {
  state: string;
  strategy: string;
  strategy_params: Record<string, unknown>;
  symbol: string;
  timeframe: string;
  started_at: string | null;
  use_ai_filter: boolean;
  paper_trade: boolean;
  sentiment?: Sentiment;
};

type SymbolInfo = {
  symbol: string;
  display_name: string;
  timeframe: string;
  state: string;
  price_decimals: number;
  max_lot: number;
  default_lot: number;
};

type AccountInfo = {
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  profit: number;
};

type Tick = { bid: number; ask: number; spread: number; time: string; symbol?: string };

export type BotEvent = {
  type: string;
  message: string;
  timestamp: string;
};

type BotStore = {
  activeSymbol: string;
  symbols: SymbolInfo[];
  status: BotStatus | null;
  symbolStatuses: Record<string, BotStatus>;
  positions: Position[];
  account: AccountInfo | null;
  sentiment: Sentiment | null;
  ticks: Record<string, Tick>;
  tick: Tick | null; // active symbol's tick (convenience)
  events: BotEvent[];
  setActiveSymbol: (symbol: string) => void;
  setSymbols: (symbols: SymbolInfo[]) => void;
  setStatus: (status: BotStatus) => void;
  setSymbolStatuses: (statuses: Record<string, BotStatus>) => void;
  setPositions: (positions: Position[]) => void;
  setAccount: (account: AccountInfo) => void;
  setSentiment: (sentiment: Sentiment) => void;
  setTick: (tick: Tick) => void;
  addEvent: (event: BotEvent) => void;
};

export const useBotStore = create<BotStore>((set, get) => ({
  activeSymbol: "GOLD",
  symbols: [],
  status: null,
  symbolStatuses: {},
  positions: [],
  account: null,
  sentiment: null,
  ticks: {},
  tick: null,
  events: [],
  setActiveSymbol: (symbol) => {
    const ticks = get().ticks;
    set({ activeSymbol: symbol, tick: ticks[symbol] || null });
  },
  setSymbols: (symbols) => set({ symbols }),
  setStatus: (status) => set({ status }),
  setSymbolStatuses: (statuses) => set({ symbolStatuses: statuses }),
  setPositions: (positions) => set({ positions }),
  setAccount: (account) => set({ account }),
  setSentiment: (sentiment) => set({ sentiment }),
  setTick: (tick) => {
    const symbol = tick.symbol || get().activeSymbol;
    const ticks = { ...get().ticks, [symbol]: tick };
    const isActive = symbol === get().activeSymbol;
    set({ ticks, ...(isActive ? { tick } : {}) });
  },
  addEvent: (event) => set((state) => ({ events: [event, ...state.events].slice(0, 50) })),
}));
