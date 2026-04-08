"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Play, BarChart3, TrendingUp, DollarSign, Target, AlertTriangle } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StatCard } from "@/components/ui/stat-card";
import { runBacktest, getCurrentStrategy } from "@/lib/api";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function BacktestPage() {
  const [strategy, setStrategy] = useState("ema_crossover");
  const [count, setCount] = useState(5000);
  const [timeframe, setTimeframe] = useState("M15");

  const [balance, setBalance] = useState(10000);
  const [strategyParams, setStrategyParams] = useState<Record<string, unknown> | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getCurrentStrategy().then((res) => {
      if (res.data?.name) setStrategy(res.data.name);
      if (res.data?.params) setStrategyParams(res.data.params);
    }).catch(() => {});
  }, []);

  const handleRun = async () => {
    setLoading(true);
    try {
      const res = await runBacktest({ strategy, timeframe, count, initial_balance: balance });
      setResult(res.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const equityCurve = (result?.equity_curve as number[] || []).map((v, i) => ({ bar: i, equity: v }));

  return (
    <div className="p-6 space-y-6">
      <PageHeader title="Backtester" subtitle="Test strategies against historical data" />

      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-sm">Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Strategy</label>
              <Select value={strategy} onValueChange={(v) => v && setStrategy(v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ema_crossover">EMA Crossover</SelectItem>
                  <SelectItem value="rsi_filter">RSI Filter</SelectItem>
                  <SelectItem value="breakout">Breakout</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Timeframe</label>
              <Select value={timeframe} onValueChange={(v) => v && setTimeframe(v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="M5">M5</SelectItem>
                  <SelectItem value="M15">M15</SelectItem>
                  <SelectItem value="H1">H1</SelectItem>
                  <SelectItem value="H4">H4</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Bars</label>
              <Input
                type="number"
                value={count}
                onChange={(e) => setCount(parseInt(e.target.value) || 1000)}
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs text-muted-foreground">Initial Balance ($)</label>
              <Input
                type="number"
                value={balance}
                onChange={(e) => setBalance(parseFloat(e.target.value) || 10000)}
              />
            </div>
            <div className="pt-2">
              <Button
                onClick={handleRun}
                disabled={loading}
                className="w-full gold-gradient text-gold-foreground font-semibold hover:opacity-90"
              >
                <Play className="size-4 mr-1.5" />
                {loading ? "Running..." : "Run Backtest"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {result && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatCard icon={BarChart3} label="Total Trades" value={result.total_trades as number} />
            <StatCard
              icon={TrendingUp}
              label="Win Rate"
              value={`${((result.win_rate as number) * 100).toFixed(1)}%`}
              variant={(result.win_rate as number) > 0.5 ? "success" : "danger"}
            />
            <StatCard
              icon={DollarSign}
              label="Total Profit"
              value={`$${(result.total_profit as number).toFixed(2)}`}
              variant={(result.total_profit as number) > 0 ? "success" : "danger"}
            />
            <StatCard
              icon={Target}
              label="Profit Factor"
              value={(result.profit_factor as number).toFixed(2)}
              variant={(result.profit_factor as number) > 1.5 ? "success" : "warning"}
            />
            <StatCard
              icon={AlertTriangle}
              label="Max Drawdown"
              value={`${((result.max_drawdown as number) * 100).toFixed(1)}%`}
              variant="danger"
            />
          </div>

          <Card className="bg-card border-border">
            <CardHeader>
              <CardTitle className="text-sm">Equity Curve</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={equityCurve}>
                  <defs>
                    <linearGradient id="goldGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="oklch(0.80 0.15 85)" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="oklch(0.80 0.15 85)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(1 0 0 / 6%)" />
                  <XAxis dataKey="bar" stroke="oklch(0.60 0.01 250)" fontSize={10} />
                  <YAxis stroke="oklch(0.60 0.01 250)" fontSize={10} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.16 0.008 250 / 90%)",
                      border: "1px solid oklch(1 0 0 / 8%)",
                      borderRadius: "8px",
                      backdropFilter: "blur(12px)",
                    }}
                    labelStyle={{ color: "oklch(0.60 0.01 250)" }}
                    itemStyle={{ color: "oklch(0.93 0.01 80)" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="oklch(0.80 0.15 85)"
                    strokeWidth={2}
                    fill="url(#goldGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
