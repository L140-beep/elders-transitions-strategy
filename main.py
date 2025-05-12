# Улучшенный скрипт с разделением результатов по категориям
import backtrader as bt
import csv
import os
import yfinance as yf
import pandas as pd
import math
from datetime import datetime
from datetime import datetime

started = False


class ImprovedElderStrategy(bt.Strategy):
    params = dict(
        ema_len=13, macd_fast=12, macd_slow=26, macd_signal=9,
        adx_len=14, adx_threshold=15,
        atr_len=14, atr_min=0.1, atr_max=5.0,
        risk_percent=1.0,
        soft_margin_leverage=1.5,
        tp_mult=1.5, sl_mult=1.0,
        rsi_period=14, rsi_low=30, rsi_high=70,
        ema_trend=200
    )

    def __init__(self):
        daily, weekly = self.datas[0], self.datas[1]

        self.emaW = bt.ind.EMA(weekly.close, period=self.p.ema_len)
        macdW = bt.ind.MACD(
            weekly.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal
        )
        self.histW = macdW.macd - macdW.signal
        self.adxW = bt.ind.ADX(weekly, period=self.p.adx_len).adx

        self.atr = bt.ind.ATR(daily, period=self.p.atr_len)
        self.ema200 = bt.ind.EMA(daily.close, period=self.p.ema_trend)
        self.rsi = bt.ind.RSI(daily.close, period=self.p.rsi_period)

        self.logfile = "backtest_log.csv"
        self.ticker = self.datas[0]._name

    def start(self):
        # Заголовок единого лога
        with open(self.logfile, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "date", "ticker", "record_type",
                "close", "atr_raw", "atr_bnd",
                "equity", "risk_amt",
                "raw_size", "ceil_size", "max_afford", "final_size",
                "order_type", "order_price", "order_size", "order_status"
            ])

    def log_debug(self, **kwargs):
        # kwargs: date, close, atr_raw, atr_bnd, equity, risk_amt,
        #         raw_size, ceil_size, max_afford, final_size
        row = [
            kwargs.pop("date"),
            self.ticker,
            "DEBUG"
        ] + [kwargs.get(col, "") for col in [
            "close", "atr_raw", "atr_bnd",
            "equity", "risk_amt",
            "raw_size", "ceil_size", "max_afford", "final_size"
        ]] + [""]*4  # placeholders for order_* columns
        with open(self.logfile, 'a', newline='') as f:
            csv.writer(f).writerow(row)

    def notify_order(self, order):
        dt = self.data.datetime.date(0)
        status = order.getstatusname()
        otype = "BUY" if order.isbuy() else "SELL"
        price = f"{order.executed.price:.5f}" if order.status == order.Completed else ""
        size = order.executed.size if order.status == order.Completed else ""
        row = [
            dt, self.ticker, "TRADE",
            "", "", "", "", "", "", "", "", "",
            otype, price, size, status
        ]
        with open(self.logfile, 'a', newline='') as f:
            csv.writer(f).writerow(row)

    def next(self):
        dt = self.data.datetime.date(0)
        daily = self.datas[0]

        if len(self.emaW) < 2:
            return

        # тренд+импульс
        curr = (1 if self.emaW[0] > self.emaW[-1] and self.histW[0] > self.histW[-1]
                else -1 if self.emaW[0] < self.emaW[-1] and self.histW[0] < self.histW[-1]
                else 0)
        prev = (1 if self.emaW[-1] > self.emaW[-2] and self.histW[-1] > self.histW[-2]
                else -1 if self.emaW[-1] < self.emaW[-2] and self.histW[-1] < self.histW[-2]
                else 0)

        if not self.position:
            close = daily.close[0]
            atr_raw = self.atr[0]
            atr_bnd = max(self.p.atr_min, min(self.p.atr_max, atr_raw))

            equity = self.broker.getvalue()
            risk_amt = equity * self.p.risk_percent / 100

            raw_size = risk_amt / atr_bnd
            ceil_size = math.ceil(raw_size)

            cash = self.broker.getcash()
            max_afford = min(
                math.floor(cash/close),
                math.floor(equity*(self.p.soft_margin_leverage-1)/close)
            )
            final_size = min(ceil_size, max_afford)

            # лог DEBUG
            self.log_debug(
                date=dt, close=f"{close:.5f}",
                atr_raw=f"{atr_raw:.5f}", atr_bnd=f"{atr_bnd:.5f}",
                equity=f"{equity:.2f}", risk_amt=f"{risk_amt:.2f}",
                raw_size=f"{raw_size:.2f}", ceil_size=ceil_size,
                max_afford=max_afford, final_size=final_size
            )

            # вход
            if final_size > 0 and self.adxW[0] > self.p.adx_threshold:
                if prev == -1 and curr == 0 and close > self.ema200[0] and self.rsi[0] > self.p.rsi_low:
                    self.buy(size=final_size)
                    self.entry_price = close
                elif prev == 1 and curr == 0 and close < self.ema200[0] and self.rsi[0] < self.p.rsi_high:
                    self.sell(size=final_size)
                    self.entry_price = close

        else:
            atr_bnd = max(self.p.atr_min, min(self.p.atr_max, self.atr[0]))
            if self.position.size > 0:
                tp = self.entry_price + atr_bnd*self.p.tp_mult
                sl = self.entry_price - atr_bnd*self.p.sl_mult
                self.sell(size=self.position.size,
                          exectype=bt.Order.Limit, price=tp)
                self.sell(size=self.position.size,
                          exectype=bt.Order.Stop,  price=sl)
                if curr == -1:
                    self.close()
            else:
                tp = self.entry_price - atr_bnd*self.p.tp_mult
                sl = self.entry_price + atr_bnd*self.p.sl_mult
                self.buy(size=abs(self.position.size),
                         exectype=bt.Order.Limit, price=tp)
                self.buy(size=abs(self.position.size),
                         exectype=bt.Order.Stop,  price=sl)
                if curr == 1:
                    self.close()


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
        # "Stocks": [
        #     "GAZP.ME", "LKOH.ME", "MGNT.ME", "NVTK.ME",
        #     "SNGS.ME", "GMKN.ME", "ROSN.ME", "NLMK.ME", "TATN.ME",
        #     "ALRS.ME", "CHMF.ME", "AFKS.ME",
        #     "FEES.ME", "IRAO.ME",
        #     "PHOR.ME", "RUAL.ME", "TRNFP.ME", "HYDR.ME", "MAGN.ME",
        #     "PIKK.ME", "QIWI.ME", "ETLN.ME"
        # ],
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
