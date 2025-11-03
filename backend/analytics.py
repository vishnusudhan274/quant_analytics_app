from typing import Tuple
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller


def align_series(a: pd.Series, b: pd.Series) -> Tuple[pd.Series, pd.Series]:
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    return df["a"], df["b"]


def ols_hedge_ratio(y: pd.Series, x: pd.Series) -> float:
    a, b = align_series(y, x)
    if len(a) < 2:
        return 1.0
    # beta = cov(x,y)/var(x)
    x_dev = b - b.mean()
    y_dev = a - a.mean()
    var_x = (x_dev ** 2).sum()
    if var_x == 0:
        return 1.0
    cov_xy = (x_dev * y_dev).sum()
    beta = cov_xy / var_x
    return float(beta)


def spread_series(y: pd.Series, x: pd.Series, hedge_ratio: float) -> pd.Series:
    a, b = align_series(y, x)
    return a - hedge_ratio * b


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    if window <= 1:
        return pd.Series(index=series.index, dtype=float)
    roll = series.rolling(window)
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    z = (series - mu) / sigma
    return z


def rolling_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    aa, bb = align_series(a, b)
    return aa.rolling(window).corr(bb)


def adf_test(series: pd.Series) -> Tuple[float, float]:
    s = series.dropna()
    if len(s) < 10:
        return float("nan"), float("nan")
    stat, pval, *_ = adfuller(s.values)
    return float(stat), float(pval)


def simple_mr_backtest(z: pd.Series, entry: float = 2.0, exit: float = 0.0) -> pd.DataFrame:
    """
    Long spread when z < -entry; short spread when z > entry; exit when |z| < exit.
    Returns equity curve assuming unit position and zero costs.
    """
    z = z.dropna().copy()
    pos = 0  # -1 short, +1 long
    pnl = []
    prev_z = None
    for t, val in z.items():
        if pos == 0:
            if val > entry:
                pos = -1
            elif val < -entry:
                pos = 1
        else:
            if abs(val) < exit:
                pos = 0
        if prev_z is None:
            pnl.append(0.0)
        else:
            pnl.append(pos * (prev_z - val))  # profit when z mean-reverts
        prev_z = val
    eq = pd.Series(pnl, index=z.index).cumsum().rename("equity")
    return eq.to_frame()
