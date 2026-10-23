# Momentum Research: a pre-registered backtest of a retail momentum strategy

**Question:** Does a published, rules-based momentum strategy for stocks actually beat simply holding the market once you control for costs and data bias?

**Short answer:** The momentum *ranking* carries real signal (it beats a random ranking in every test), but a net edge of the full system over equal-weight buy-and-hold could **not** be demonstrated. Most of the headline outperformance is explained by survivorship bias and the equal-weight tilt.

This repo contains the backtester, the monthly screener I use, and the raw results. Code comments are in German.

---

## Strategy under test

Based on the momentum approach published by *The Market* (themarket.ch, Alfons Cortés), which builds on Jegadeesh/Titman (1993) and Faber (2007):

| Rule | Implementation |
|---|---|
| Momentum score | Average of 6-month and 12-month price return, month-end |
| Relative strength | Only stocks scoring above the benchmark (MSCI World / S&P 500) |
| Trend filter / exit | Price above its 10-month moving average, checked at month-end |
| Portfolio | Top 22, equal-weighted, max. 4 per sector |
| Costs | 10 bps per side (sensitivity: 5 / 20 bps) |

## Method

- **Pre-registered variants.** Four variants were fixed *before* the first run (12-1 momentum, exit hysteresis, Bollinger "bubble" filter ablation, portfolio size 15/22/30). No parameter was tuned after looking at out-of-sample results.
- **In-sample / out-of-sample split** at 2016-01-01. A variant only counts as an improvement if it helps in both periods *and* survives 5 and 20 bps costs.
- **Null test.** The momentum ranking is replaced by a random ranking with all filters still active. If the null run shows "alpha", the pipeline is leaking.
- **No look-ahead in signals.** Signals use data up to month-end t only.
- **Bias accounting.** Today's S&P 500 constituents are survivors. Absolute returns are therefore inflated; only *relative* comparisons between variants on identical data are treated as reliable. The bias is then estimated against a live equal-weight ETF (RSP).

## Results

Run A: S&P 500 (current constituents) vs. SPY, 2005–2025, 244 months. Run B: vs. URTH (MSCI World), 2013–2025, 160 months.

| Run A, full period | CAGR | Sharpe | Max drawdown |
|---|---:|---:|---:|
| Strategy (base) | 18.3 % | 0.89 | −45.8 % |
| SPY buy-and-hold | 11.0 % | — | −50.8 % |

Raw outperformance of +7.3 pts p.a. is **well above** the 2–4 pts that the academic literature leads one to expect. That alone flags bias rather than skill.

| Run B, decomposed | CAGR | Sharpe | Max drawdown |
|---|---:|---:|---:|
| Strategy (monthly rotation) | 16.5 % | 0.99 | −21.2 % |
| Equal-weight buy-and-hold, same universe | 17.3 % | 1.01 | −22.0 % |
| Top-22 selected, held 12 months (no exits) | 18.4 % | 1.04 | −20.4 % |
| URTH buy-and-hold | 11.6 % | 0.71 | −25.5 % |

**Findings**

1. **The ranking has signal.** It beats a random ranking by +6.7 pts p.a. (Run A) and +1.9 pts (Run B). The null test behaves as expected (random ranking wins in 50.0 % of months).
2. **The full system shows no net edge over equal-weight buy-and-hold** of the same universe (−0.8 pts in Run B). Selection adds about +1.1 pts; monthly rotation costs about −1.9 pts through whipsaw and trading costs.
3. **Survivorship bias is large.** Estimated at 6–8 pts p.a. for Run B and 2–4 pts for Run A.
4. **The trend filter does not protect in a systemic crash.** Max drawdown in 2008/09 was −45.8 % vs. −50.8 % for the market.
5. **Pre-registered variants:** 12-1 momentum rejected (worse in IS and OOS); exit hysteresis cuts turnover by 19 % but worsens the 2008 drawdown (−56.8 %) and is direction-inconsistent; the Bollinger bubble filter is **removed** because it lowers return *and* raises turnover; portfolio size shows a flat plateau, 22 kept.

**Conclusion:** The useful output of the system is a disciplined, rules-based selection process, not a proven return premium. Realistic forward expectation vs. buy-and-hold: roughly −1 to +3 pts p.a., not statistically distinguishable from zero.

## Limitations

Free Yahoo Finance data only; no survivorship-free constituent history (e.g. Norgate). Run B ran on 87 tickers after a rate-limit during download, alphabetically skewed. Flat risk-free rate of 2 %. No withholding-tax modelling.

## Usage

```bash
pip install -r requirements.txt

# pipeline self-test on synthetic data, no network
python3 backtest_momentum.py --demo

# full pre-registered programme
python3 backtest_momentum.py --fetch-sp500 --start 2005-01-01 --benchmark SPY --grid
python3 backtest_momentum.py --fetch-sp500 --start 2012-01-01 --benchmark URTH --null

# monthly screen: S&P 500 + Stoxx 600 + SPI, FX-adjusted to USD
python3 momentum_screener.py --universe us,eu,ch
```

`momentum_check.pine` is a TradingView indicator showing the same month-end signal on a chart.

## Next steps

Rerun Run A with an equal-weight benchmark and holding-period variants (monthly / 6 / 12 months) on the full universe, including 2008.

---

*For research and education only. Not investment advice.*
