# Улучшенный скрипт с разделением результатов по категориям
import backtrader as bt
import csv
import yfinance as yf
import pandas as pd
from datetime import datetime


class ImprovedElderStrategy(bt.Strategy):
    params = dict(
        ema_len=13, macd_fast=12, macd_slow=26, macd_signal=9,
        adx_len=14, adx_threshold=15,
        atr_len=14, risk_percent=1.0,
        tp_mult=1.5, sl_mult=1.0,
        rsi_period=14, rsi_low=30, rsi_high=70,
        ema_trend=200
    )

    def __init__(self):
        daily, weekly = self.datas[0], self.datas[1]
        self.emaW = bt.ind.EMA(weekly.close, period=self.p.ema_len)
        macdW = bt.ind.MACD(weekly.close, period_me1=self.p.macd_fast,
                            period_me2=self.p.macd_slow, period_signal=self.p.macd_signal)
        self.histW = macdW.macd - macdW.signal
        self.adxW = bt.ind.ADX(weekly, period=self.p.adx_len).adx
        self.atr = bt.ind.ATR(daily, period=self.p.atr_len)
        self.ema200 = bt.ind.EMA(daily.close, period=self.p.ema_trend)
        self.rsi = bt.ind.RSI(daily.close, period=self.p.rsi_period)
        self.debugfile = "eurjpy_debug.csv"

    def start(self):
        self.ticker = self.datas[0]._name or "UNKNOWN"
        if self.ticker == "EURJPY=X":
            self.logfile = "eurjpy_trades.csv"
            with open(self.logfile, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["date", "ticker", "type",
                                "price", "size", "status"])
            with open(self.debugfile, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["date", "close", "atr", "cash",
                                "risk_per_trade", "raw_size", "final_size"])

    def debug_log(self, dt, close, atr, cash, risk_per_trade, raw_size, final_size):
        with open(self.debugfile, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                dt.strftime("%Y-%m-%d"),
                f"{close:.5f}",
                f"{atr:.5f}",
                f"{cash:.2f}",
                f"{risk_per_trade:.2f}",
                raw_size,
                final_size
            ])

    def next(self):
        daily = self.datas[0]
        if len(self.emaW) < 2:
            return

        dt = self.data.datetime.date(0)
        curr = (1 if self.emaW[0] > self.emaW[-1] and self.histW[0] > self.histW[-1] else
                -1 if self.emaW[0] < self.emaW[-1] and self.histW[0] < self.histW[-1] else 0)
        prev = (1 if self.emaW[-1] > self.emaW[-2] and self.histW[-1] > self.histW[-2] else
                -1 if self.emaW[-1] < self.emaW[-2] and self.histW[-1] < self.histW[-2] else 0)

        if not self.position:
            close_price = daily.close[0]
            atr_val = self.atr[0]
            cash = self.broker.getcash()
            risk_per_trade = self.broker.getvalue() * self.p.risk_percent / 100

            raw_size = risk_per_trade / atr_val
            final_size = int(raw_size)
            position_cost = close_price * final_size

            # Проверяем, хватает ли денег
            while final_size > 0 and position_cost > cash:
                final_size -= 1
                position_cost = close_price * final_size

            # Запись отладочной информации
            if getattr(self, 'ticker', '') == "EURJPY=X":
                with open("eurjpy_debug.csv", mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        self.data.datetime.date(0),
                        cash, risk_per_trade, atr_val, raw_size, final_size,
                        position_cost, close_price
                    ])

            if final_size > 0:
                if prev == -1 and curr == 0 and self.adxW[0] > self.p.adx_threshold and self.rsi[0] > self.p.rsi_low and close_price > self.ema200[0]:
                    self.buy(size=final_size)
                    self.entry_price = close_price
                elif prev == 1 and curr == 0 and self.adxW[0] > self.p.adx_threshold and self.rsi[0] < self.p.rsi_high and close_price < self.ema200[0]:
                    self.sell(size=final_size)
                    self.entry_price = close_price


def run_backtest(category_tickers, start, end, initial_cash=100000):
    results = []
    for category, tickers in category_tickers.items():
        for sym in tickers:
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(initial_cash)
            df = yf.download(sym, start=start, end=end,
                             auto_adjust=True, progress=False)
            df.index = df.index.tz_localize(None)
            if isinstance(df.columns, pd.MultiIndex):
                df = df.xs(sym, axis=1, level=1)
            data = bt.feeds.PandasData(dataname=df, fromdate=datetime.strptime(start, "%Y-%m-%d"),
                                       todate=datetime.strptime(end, "%Y-%m-%d"), name=sym, timeframe=bt.TimeFrame.Days)
            cerebro.adddata(data)
            cerebro.resampledata(
                data, timeframe=bt.TimeFrame.Weeks, compression=1)
            cerebro.addstrategy(ImprovedElderStrategy)
            cerebro.addanalyzer(bt.analyzers.SharpeRatio,
                                _name='sharpe', timeframe=bt.TimeFrame.Days)
            strat = cerebro.run()[0]
            sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
            final_value = cerebro.broker.getvalue()
            profit_pct = (final_value - initial_cash) / initial_cash * 100
            results.append({'category': category, 'ticker': sym,
                           'sharpe': sharpe, 'profit_pct': profit_pct})

    df_res = pd.DataFrame(results).set_index(['category', 'ticker'])
    print(df_res)

    print("\nСредние значения по категориям:")
    print(df_res.groupby('category').mean())
    print("\nСредние значения по всем категориям:")
    print(df_res.mean())


if __name__ == "__main__":
    category_tickers = {
        "Stocks": [
            "GAZP.ME", "LKOH.ME", "MGNT.ME", "NVTK.ME",
            "SNGS.ME", "GMKN.ME", "ROSN.ME", "NLMK.ME", "TATN.ME",
            "ALRS.ME", "CHMF.ME", "AFKS.ME",
            "FEES.ME", "IRAO.ME",
            "PHOR.ME", "RUAL.ME", "TRNFP.ME", "HYDR.ME", "MAGN.ME",
            "PIKK.ME", "QIWI.ME", "ETLN.ME"
        ],
        "Forex": [
            "JPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X", "USDCAD=X",
            "USDCHF=X", "EURJPY=X", "GBPJPY=X", "EURGBP=X", "AUDJPY=X",
            "USDRUB=X", "EURRUB=X", "GBPRUB=X", "JPYRUB=X"
        ],
        "Metals": ["GC=F", "SI=F", "HG=F", "PL=F", "PA=F"]
    }
    run_backtest(category_tickers, "2020-01-01", "2025-05-01")

    # category_tickers = {
    #     "Stocks": [
    #         "GAZP.ME", "LKOH.ME", "MGNT.ME", "NVTK.ME",
    #         "SNGS.ME", "GMKN.ME", "ROSN.ME", "NLMK.ME", "TATN.ME",
    #         "ALRS.ME", "CHMF.ME", "AFKS.ME",
    #         "FEES.ME", "IRAO.ME",
    #         "PHOR.ME", "RUAL.ME", "TRNFP.ME", "HYDR.ME", "MAGN.ME",
    #         "PIKK.ME", "QIWI.ME", "ETLN.ME"
    #     ],
    #     "Forex": [
    #         "JPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X", "USDCAD=X",
    #         "USDCHF=X", "EURJPY=X", "GBPJPY=X", "EURGBP=X", "AUDJPY=X",
    #         "USDRUB=X", "EURRUB=X", "GBPRUB=X", "JPYRUB=X"
    #     ],
    #     "Metals": ["GC=F", "SI=F", "HG=F", "PL=F", "PA=F"]
    # }
