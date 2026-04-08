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

type AccountInfo = {
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  profit: number;
};

export type BotEvent = {
  type: string;
  message: string;
  timestamp: string;
};

type BotStore = {
  status: BotStatus | null;
  positions: Position[];
  account: AccountInfo | null;
  sentiment: Sentiment | null;
  tick: { bid: number; ask: number; spread: number; time: string } | null;
  events: BotEvent[];
  setStatus: (status: BotStatus) => void;
  setPositions: (positions: Position[]) => void;
  setAccount: (account: AccountInfo) => void;
  setSentiment: (sentiment: Sentiment) => void;
  setTick: (tick: { bid: number; ask: number; spread: number; time: string }) => void;
  addEvent: (event: BotEvent) => void;
};

export const useBotStore = create<BotStore>((set) => ({
  status: null,
  positions: [],
  account: null,
  sentiment: null,
  tick: null,
  events: [],
  setStatus: (status) => set({ status }),
  setPositions: (positions) => set({ positions }),
  setAccount: (account) => set({ account }),
  setSentiment: (sentiment) => set({ sentiment }),
  setTick: (tick) => set({ tick }),
  addEvent: (event) => set((state) => ({ events: [event, ...state.events].slice(0, 50) })),
}));
