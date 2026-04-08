"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, CandlestickData, ColorType, CandlestickSeries, LineSeries } from "lightweight-charts";
import { getOHLCV } from "@/lib/api";

type Props = {
  symbol: string;
  timeframe: string;
  tick?: { bid: number; ask: number; time?: string } | null;
  emaFast?: number;
  emaSlow?: number;
};

function calcEMA(data: { time: number; close: number }[], period: number) {
  const k = 2 / (period + 1);
  const result: { time: number; value: number }[] = [];
  let prev = data[0]?.close ?? 0;
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      prev = (data.slice(0, i + 1).reduce((s, d) => s + d.close, 0)) / (i + 1);
      continue;
    }
    const ema = data[i].close * k + prev * (1 - k);
    result.push({ time: data[i].time, value: Math.round(ema * 100) / 100 });
    prev = ema;
  }
  return result;
}

export default function PriceChart({ symbol, timeframe, tick, emaFast = 20, emaSlow = 50 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaFastRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSlowRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [loading, setLoading] = useState(true);

  // Store last candle from OHLCV for live updating
  const lastCandleRef = useRef<{ time: number; open: number; high: number; low: number; close: number } | null>(null);

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8a8fa0",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: {
        vertLine: { color: "rgba(212,175,55,0.3)", labelBackgroundColor: "#d4af37" },
        horzLine: { color: "rgba(212,175,55,0.3)", labelBackgroundColor: "#d4af37" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    });

    const emaFastSeries = chart.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const emaSlowSeries = chart.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    seriesRef.current = series;
    emaFastRef.current = emaFastSeries;
    emaSlowRef.current = emaSlowSeries;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      emaFastRef.current = null;
      emaSlowRef.current = null;
    };
  }, []);

  // Fetch candle data
  useEffect(() => {
    let cancelled = false;

    const fetchCandles = async () => {
      try {
        const res = await getOHLCV(timeframe, 200);
        if (cancelled || !seriesRef.current) return;
        const candles = res.data.candles as CandlestickData[];
        if (candles.length > 0) {
          seriesRef.current.setData(candles);

          // Calculate and set EMA overlays
          const closeData = candles.map((c) => ({
            time: c.time as number,
            close: c.close as number,
          }));
          if (emaFastRef.current) {
            const fastData = calcEMA(closeData, emaFast);
            emaFastRef.current.setData(fastData.map((d) => ({ time: d.time as CandlestickData["time"], value: d.value })));
          }
          if (emaSlowRef.current) {
            const slowData = calcEMA(closeData, emaSlow);
            emaSlowRef.current.setData(slowData.map((d) => ({ time: d.time as CandlestickData["time"], value: d.value })));
          }

          chartRef.current?.timeScale().fitContent();
          // Save last candle for live updates
          const last = candles[candles.length - 1];
          lastCandleRef.current = {
            time: last.time as number,
            open: last.open as number,
            high: last.high as number,
            low: last.low as number,
            close: last.close as number,
          };
        }
      } catch (e) {
        console.error("Failed to fetch candles:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchCandles();
    const interval = setInterval(fetchCandles, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [timeframe, emaFast, emaSlow]);

  // Update last candle from tick — use the same time as the last OHLCV candle
  useEffect(() => {
    if (!tick || !seriesRef.current || !lastCandleRef.current) return;

    const price = tick.bid;
    const candle = lastCandleRef.current;

    // Update high/low/close of the current candle
    candle.high = Math.max(candle.high, price);
    candle.low = Math.min(candle.low, price);
    candle.close = price;

    try {
      seriesRef.current.update({
        time: candle.time as CandlestickData["time"],
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
    } catch {
      // Ignore errors
    }
  }, [tick]);

  return (
    <div className="relative w-full h-full min-h-[220px]">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <span className="text-muted-foreground text-sm">Loading {symbol} chart...</span>
        </div>
      )}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
