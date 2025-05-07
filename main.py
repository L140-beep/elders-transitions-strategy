# Новый скрипт с EMA200, RSI-фильтром и сниженным соотношением TP:SL
import backtrader as bt
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
        daily = self.datas[0]
        weekly = self.datas[1]

        # Weekly EMA and MACD
        self.emaW = bt.ind.EMA(weekly.close, period=self.p.ema_len)
        macdW = bt.ind.MACD(weekly.close, period_me1=self.p.macd_fast,
                            period_me2=self.p.macd_slow, period_signal=self.p.macd_signal)
        self.histW = macdW.macd - macdW.signal

        # Weekly ADX
        self.adxW = bt.ind.ADX(weekly, period=self.p.adx_len).adx

        # Daily indicators
        self.atr = bt.ind.ATR(daily, period=self.p.atr_len)
        self.ema200 = bt.ind.EMA(daily.close, period=self.p.ema_trend)
        self.rsi = bt.ind.RSI(daily.close, period=self.p.rsi_period)

    def next(self):
        daily = self.datas[0]
        if len(self.emaW) < 2:
            return

        curr = (1 if self.emaW[0] > self.emaW[-1] and self.histW[0] > self.histW[-1] else
                -1 if self.emaW[0] < self.emaW[-1] and self.histW[0] < self.histW[-1] else 0)
        prev = (1 if self.emaW[-1] > self.emaW[-2] and self.histW[-1] > self.histW[-2] else
                -1 if self.emaW[-1] < self.emaW[-2] and self.histW[-1] < self.histW[-2] else 0)

        if not self.position:
            size = int((self.broker.getvalue() *
                       self.p.risk_percent / 100) / self.atr[0])
            if prev == -1 and curr == 0 and self.adxW[0] > self.p.adx_threshold and self.rsi[0] > self.p.rsi_low and daily.close[0] > self.ema200[0]:
                self.buy(size=size)
                self.order_target_price = daily.close[0]
            elif prev == 1 and curr == 0 and self.adxW[0] > self.p.adx_threshold and self.rsi[0] < self.p.rsi_high and daily.close[0] < self.ema200[0]:
                self.sell(size=size)
                self.order_target_price = daily.close[0]
        else:
            if self.position.size > 0:
                tp = self.order_target_price + self.atr[0] * self.p.tp_mult
                sl = self.order_target_price - self.atr[0] * self.p.sl_mult
                self.sell(size=self.position.size,
                          exectype=bt.Order.Limit, price=tp)
                self.sell(size=self.position.size,
                          exectype=bt.Order.Stop, price=sl)
                if curr == -1:
                    self.close()
            else:
                tp = self.order_target_price - self.atr[0] * self.p.tp_mult
                sl = self.order_target_price + self.atr[0] * self.p.sl_mult
                self.buy(size=abs(self.position.size),
                         exectype=bt.Order.Limit, price=tp)
                self.buy(size=abs(self.position.size),
                         exectype=bt.Order.Stop, price=sl)
                if curr == 1:
                    self.close()


def run_backtest(tickers, start, end, initial_cash=100000):
    results = []
    for sym in tickers:
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(initial_cash)
        df = yf.download(sym, start=start, end=end,
                         auto_adjust=True, progress=False)
        df.index = df.index.tz_localize(None)
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(sym, axis=1, level=1)
        data = bt.feeds.PandasData(dataname=df, fromdate=datetime.strptime(start, "%Y-%m-%d"),
                                   todate=datetime.strptime(end, "%Y-%m-%d"), timeframe=bt.TimeFrame.Days)
        cerebro.adddata(data)
        cerebro.resampledata(data, timeframe=bt.TimeFrame.Weeks, compression=1)
        cerebro.addstrategy(ImprovedElderStrategy)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio,
                            _name='sharpe', timeframe=bt.TimeFrame.Days)
        strat = cerebro.run()[0]
        sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
        final_value = cerebro.broker.getvalue()
        profit_pct = (final_value - initial_cash) / initial_cash * 100
        results.append({'ticker': sym, 'sharpe': sharpe,
                       'profit_pct': profit_pct})
    df_res = pd.DataFrame(results).set_index('ticker')
    df_res['sharpe'] = df_res['sharpe'].astype(float)
    df_res['profit_pct'] = df_res['profit_pct'].astype(float)
    avg_sharpe = df_res['sharpe'].mean()
    avg_profit = df_res['profit_pct'].mean()
    print(df_res)
    print(
        f"\nAverage Sharpe: {avg_sharpe:.2f}\nAverage Profit (%): {avg_profit:.2f}")


# if __name__ == "__main__":
tickers = ["GAZP.ME", "SBER.ME", "LKOH.ME", "MGNT.ME", "NVTK.ME", "SNGS.ME",
           "GMKN.ME", "ROSN.ME", "NLMK.ME", "TATN.ME", "MTSS.ME", "ALRS.ME", "CHMF.ME"]
run_backtest(tickers, "2020-01-01", "2025-05-01")
