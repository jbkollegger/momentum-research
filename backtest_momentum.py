#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_momentum.py · v1.0 (09.07.2026)
The-Market-Momentum-Strategie – methodisch sauberer Backtest.

STRATEGIE (Basis, wie im Projekt umgesetzt):
  · Monatsschluss-Ranking: Score = Ø(6M-, 12M-Performance)
  · Nur Titel, deren Score über dem Benchmark-Score liegt (relative Stärke)
  · Nur Titel über ihrem 10-Monats-SMA (Exit bei Bruch, am Monatsschluss)
  · Top-N (Default 22) gleichgewichtet · gehalten bis Regelbruch,
    freie Slots mit dem nächstbesten regelkonformen Titel gefüllt
  · Kosten in Basispunkten pro Seite · Cash verzinst mit --rf

VORREGISTRIERTE VARIANTEN (Testprogramm, KEINE Nachoptimierung!):
  V1  --skip-recent 1        12-1-Momentum (letzten Monat ausschliessen)
  V2  --hyst-out 2 --confirm 2   Exit-Glättung (Hysterese + Bestätigung)
  V3  --bubble-filter        Bollinger-«Blase»-Filter AN (Ablation: Beitrag messen)
  V4  --top-n 15 / 30        Titelzahl-Sensitivität
  --grid führt das komplette vorregistrierte Programm in einem Lauf aus.

EHRLICHKEITS-HINWEISE (bewusst im Code dokumentiert):
  · SURVIVORSHIP-BIAS: Eine heutige Ticker-Liste (z. B. aktueller S&P 500)
    enthält nur Überlebende → absolute Renditen nach oben verzerrt
    (Grössenordnung Large Caps: ~1–2 %-Punkte p.a.). Verwende die Ergebnisse
    primär für RELATIVE Vergleiche (Variante A vs. B auf identischen Daten).
  · Index-Mitgliedschaft von heute auf die Vergangenheit angewandt = Look-ahead
    (Teil desselben Problems). Sauber wäre eine historische Konstituentenliste
    (Norgate u. ä.) – hier nicht verfügbar.
  · Kurse: yfinance auto_adjust=True → split-/dividendenadjustiert
    (Total-Return-Näherung), gilt auch für den Benchmark.
  · Benchmark: URTH (iShares MSCI World) existiert erst ab 2012.
    Für längere Historie --benchmark SPY (US-Proxy; Universum ist ohnehin US).
  · Signale am Monatsschluss t, Ausführung zum selben Schluss (Standard-
    Konvention, leicht optimistisch). --exec nextopen handelt am ersten
    Eröffnungskurs des Folgemonats.
  · rf ist flach (--rf); verschiebt Sharpe-NIVEAUS, nicht die Rangfolge.
  · --null ersetzt das Ranking durch Zufall: erwartetes Ergebnis ≈ Markt-
    durchschnitt minus Kosten. Wenn --null "Edge" zeigt → Pipeline-Fehler!

BEISPIELE:
  python3 backtest_momentum.py --demo                       # Synthetik-Test der Pipeline
  python3 backtest_momentum.py --fetch-sp500 --start 2005-01-01 --benchmark SPY
  python3 backtest_momentum.py --tickers-file meine_ticker.txt --benchmark URTH --start 2012-01-01
  python3 backtest_momentum.py --fetch-sp500 --grid --oos-start 2016-01-01
Abhängigkeiten:  pip3 install yfinance pandas numpy
"""

import argparse
import os
import sys
import math
import numpy as np
import pandas as pd

CACHE = "cache_prices.pkl"


# ───────────────────────────── Daten ─────────────────────────────────────────

def fetch_sp500_tickers():
    """Aktuelle S&P-500-Liste von Wikipedia (ACHTUNG: Survivorship-Bias).
    Wikipedia blockiert den Standard-Python-User-Agent (403) → wir melden
    uns als Browser und übergeben das HTML selbst an pandas."""
    import io
    import urllib.request
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        tables = pd.read_html(io.StringIO(html))
    except Exception as e:
        sys.exit(f"S&P-500-Liste konnte nicht geladen werden ({e}).\n"
                 "Alternative: eigene Liste als Textdatei (ein Ticker pro Zeile) "
                 "und --tickers-file meine_ticker.txt verwenden.")
    syms = tables[0]["Symbol"].astype(str).str.replace(".", "-", regex=False)
    return sorted(syms.unique().tolist())


def load_prices(tickers, start, end, cache=CACHE, refresh=False):
    """Adjustierte Schluss-/Eröffnungskurse via yfinance, mit lokalem Cache."""
    import yfinance as yf
    key = (tuple(tickers), str(start), str(end))
    if os.path.exists(cache) and not refresh:
        try:
            k, close, opn = pd.read_pickle(cache)
            if k == key:
                print(f"[Cache] {cache} verwendet ({close.shape[1]} Titel)")
                return close, opn
        except Exception:
            pass
    print(f"[Download] {len(tickers)} Ticker …")
    frames_c, frames_o = [], []
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        d = yf.download(chunk, start=start, end=end, auto_adjust=True,
                        progress=False, group_by="column")
        c = d["Close"] if isinstance(d.columns, pd.MultiIndex) else d[["Close"]].rename(columns={"Close": chunk[0]})
        o = d["Open"] if isinstance(d.columns, pd.MultiIndex) else d[["Open"]].rename(columns={"Open": chunk[0]})
        frames_c.append(c)
        frames_o.append(o)
        print(f"  … {min(i+100, len(tickers))}/{len(tickers)}")
    close = pd.concat(frames_c, axis=1).sort_index()
    opn = pd.concat(frames_o, axis=1).sort_index()
    close = close.dropna(axis=1, how="all")
    opn = opn.reindex(columns=close.columns)
    pd.to_pickle((key, close, opn), cache)
    return close, opn


def make_demo_data(n=80, months=252, seed=7):
    """Synthetisches Universum mit persistenten Drift-Regimen (Momentum-Signal)
    + reine Zufalls-Titel. Zweck: Pipeline-Validierung, KEIN Markt-Ersatz."""
    rng = np.random.default_rng(seed)
    try:
        idx = pd.date_range("2005-01-31", periods=months, freq="ME")
    except ValueError:                                   # pandas < 2.2
        idx = pd.date_range("2005-01-31", periods=months, freq="M")
    prices = {}
    for i in range(n):
        mu = 0.006
        drift = np.zeros(months)
        state = rng.choice([-0.010, 0.0, 0.012])
        for t in range(months):
            if rng.random() < 0.04:                      # Regimewechsel
                state = rng.choice([-0.012, 0.0, 0.014])
            drift[t] = state
        r = mu + drift + rng.normal(0, 0.07, months)
        prices[f"SYN{i:03d}"] = 100 * np.cumprod(1 + r)
    close = pd.DataFrame(prices, index=idx)
    bench = close.mean(axis=1).rename("BENCH")
    return close, bench


# ───────────────────────── Signal-Logik ──────────────────────────────────────

def momentum_score(monthly, skip_recent=0):
    """Score = Ø(6M, 12M). skip_recent=1 → 12-1-Konvention (t-1 als Endpunkt)."""
    p_end = monthly.shift(skip_recent)
    m6 = p_end / monthly.shift(6 + skip_recent) - 1
    m12 = p_end / monthly.shift(12 + skip_recent) - 1
    return (m6 + m12) / 2 * 100


def ma_state_machine(monthly, ma_len=10, hyst_out=0.0, hyst_in=0.0, confirm=1):
    """Über/Unter-MA als STATUS je Titel (Monatsschluss-Auswertung),
    mit optionaler Hysterese und Bestätigung über n Monatsschlüsse.
    Entspricht TheMarket_Momentum_Check.pine v1.1."""
    sma = monthly.rolling(ma_len).mean()
    state = pd.DataFrame(index=monthly.index, columns=monthly.columns, dtype="float64")
    for col in monthly.columns:
        px, ma = monthly[col].values, sma[col].values
        held, init, c_out, c_in = np.nan, False, 0, 0
        out = np.full(len(px), np.nan)
        for t in range(len(px)):
            if np.isnan(px[t]) or np.isnan(ma[t]):
                out[t] = held
                continue
            if not init:
                held, init = float(px[t] > ma[t]), True
            elif held == 1.0:
                c_out = c_out + 1 if px[t] < ma[t] * (1 - hyst_out / 100) else 0
                if c_out >= confirm:
                    held, c_out = 0.0, 0
            else:
                c_in = c_in + 1 if px[t] > ma[t] * (1 + hyst_in / 100) else 0
                if c_in >= confirm:
                    held, c_in = 1.0, 0
            out[t] = held
        state[col] = out
    return state == 1.0


def bubble_flag(monthly, win=20, rank_win=36, pct=85):
    """Bollinger-«Blase»: Bandbreite über Perzentil UND Kurs über Mittellinie."""
    mid = monthly.rolling(win).mean()
    sd = monthly.rolling(win).std()
    bw = (4 * sd / mid) * 100
    rk = bw.rolling(rank_win).rank(pct=True) * 100
    return (rk >= pct) & (monthly > mid)


# ───────────────────────── Portfolio-Simulation ──────────────────────────────

def simulate(monthly, bench_m, args, rng=None):
    """Monatsschleife. Rückgabe: DataFrame mit Strategie-/Benchmark-Monatsrenditen,
    Positionen, Turnover."""
    score = momentum_score(monthly, args.skip_recent)
    bscore = momentum_score(bench_m.to_frame("B"), args.skip_recent)["B"]
    ma_ok = ma_state_machine(monthly, 10, args.hyst_out, args.hyst_in, args.confirm)
    bub = bubble_flag(monthly) if args.bubble_filter else None
    if args.null and rng is None:
        rng = np.random.default_rng(42)

    rets = monthly.pct_change()
    dates = monthly.index
    hold = []                                    # aktuelle Ticker
    rows = []
    start_t = 14 + args.skip_recent              # genug Historie für 12M+MA
    for t in range(start_t, len(dates) - 1):
        dt, nxt = dates[t], dates[t + 1]
        sc = score.iloc[t]
        if args.null:                            # Zufalls-Ranking (Null-Test)
            v = sc.dropna()
            sc = pd.Series(rng.permutation(v.values), index=v.index).reindex(sc.index)
        eligible = sc.notna() & ma_ok.iloc[t] & (sc > bscore.iloc[t])
        if args.bubble_filter:
            eligible &= ~bub.iloc[t].fillna(False)
        elig_set = set(eligible.index[eligible])

        # Verkäufe: Regelbruch (MA-Status ODER relative Stärke ODER Blase)
        hold = [h for h in hold if h in elig_set]
        # Käufe: beste Nicht-Gehaltene bis Top-N voll
        if len(hold) < args.top_n:
            cand = sc[eligible].drop(index=hold, errors="ignore").sort_values(ascending=False)
            hold += list(cand.index[: args.top_n - len(hold)])

        w_new = pd.Series(1.0 / args.top_n, index=hold, dtype=float)  # EW, Rest Cash
        prev = rows[-1]["w"] if rows else pd.Series(dtype=float)
        r_next = rets.loc[nxt]
        # Drift der Vormonats-Gewichte für Turnover-Berechnung
        if len(prev):
            gross = prev * (1 + rets.loc[dt].reindex(prev.index).fillna(0))
            prev_d = gross / max(gross.sum() + (1 - prev.sum()), 1e-12)
        else:
            prev_d = prev
        allw = w_new.reindex(w_new.index.union(prev_d.index), fill_value=0.0)
        allp = prev_d.reindex(allw.index, fill_value=0.0)
        turnover = float((allw - allp).abs().sum()) / 2
        cost = turnover * 2 * args.cost_bps / 1e4          # beide Seiten
        invested = float(w_new.sum())
        gross_ret = float((w_new * r_next.reindex(w_new.index).fillna(0)).sum())
        net = gross_ret + (1 - invested) * args.rf / 12 - cost
        rows.append(dict(date=nxt, ret=net, bench=float(bench_m.pct_change().loc[nxt]),
                         n=len(hold), turnover=turnover, w=w_new))
    df = pd.DataFrame(rows).set_index("date")
    return df.drop(columns="w")


# ───────────────────────────── Kennzahlen ────────────────────────────────────

def metrics(df, rf=0.02, label=""):
    r, b = df["ret"], df["bench"]
    n = len(r)
    if n < 12:
        return {"Label": label, "Monate": n}
    eq = (1 + r).cumprod()
    yrs = n / 12
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = r.std() * math.sqrt(12)
    dd = (eq / eq.cummax() - 1).min()
    rm = rf / 12
    sharpe = (r.mean() - rm) / r.std() * math.sqrt(12) if r.std() > 0 else np.nan
    downside = r[r < rm]
    sortino = (r.mean() - rm) / downside.std() * math.sqrt(12) if len(downside) > 1 else np.nan
    calmar = cagr / abs(dd) if dd < 0 else np.nan
    ex_r, ex_b = r - rm, b - rm
    beta = ex_r.cov(ex_b) / ex_b.var() if ex_b.var() > 0 else np.nan
    alpha = (ex_r.mean() - beta * ex_b.mean()) * 12
    beq = (1 + b).cumprod()
    bcagr = beq.iloc[-1] ** (1 / yrs) - 1
    return {
        "Label": label, "Monate": n,
        "CAGR %": round(cagr * 100, 2), "Bench-CAGR %": round(bcagr * 100, 2),
        "Vol %": round(vol * 100, 1), "Sharpe": round(sharpe, 2),
        "Sortino": round(sortino, 2), "Calmar": round(calmar, 2),
        "MaxDD %": round(dd * 100, 1),
        "MaxDD Bench %": round((beq / beq.cummax() - 1).min() * 100, 1),
        "Treffer % (Monat>0)": round((r > 0).mean() * 100, 1),
        "vs. Bench % (Monat)": round((r > b).mean() * 100, 1),
        "Alpha % p.a.": round(alpha * 100, 2), "Beta": round(beta, 2),
        "Turnover p.a. (1-seitig)": round(df["turnover"].mean() * 12, 2),
        "Ø Positionen": round(df["n"].mean(), 1),
    }


def report(df, args, label):
    out = [metrics(df, args.rf, f"{label} · gesamt")]
    if args.oos_start:
        cut = pd.Timestamp(args.oos_start)
        out.append(metrics(df[df.index < cut], args.rf, f"{label} · IS  (<{args.oos_start})"))
        out.append(metrics(df[df.index >= cut], args.rf, f"{label} · OOS (≥{args.oos_start})"))
    return out


# ───────────────────────────── Hauptprogramm ─────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(description="The-Market-Momentum-Backtest (siehe Docstring)",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("Daten")
    src.add_argument("--tickers-file", help="Textdatei, ein Ticker pro Zeile")
    src.add_argument("--fetch-sp500", action="store_true", help="aktuelle S&P-500-Liste (Survivorship-Bias!)")
    src.add_argument("--benchmark", default="URTH", help="Benchmark-Ticker (URTH ab 2012, sonst SPY)")
    src.add_argument("--start", default="2012-01-01")
    src.add_argument("--end", default=None)
    src.add_argument("--refresh", action="store_true", help="Cache ignorieren, neu laden")
    st = p.add_argument_group("Strategie")
    st.add_argument("--top-n", type=int, default=22)
    st.add_argument("--skip-recent", type=int, default=0, choices=[0, 1], help="1 = 12-1-Momentum (V1)")
    st.add_argument("--hyst-out", type=float, default=0.0, help="Exit erst x %% unter MA (V2)")
    st.add_argument("--hyst-in", type=float, default=0.0, help="Einstieg erst x %% über MA (V2)")
    st.add_argument("--confirm", type=int, default=1, help="Bestätigung über n Monatsschlüsse (V2)")
    st.add_argument("--bubble-filter", action="store_true", help="Bollinger-Blase-Filter AN (V3-Ablation)")
    st.add_argument("--cost-bps", type=float, default=10.0, help="Kosten je Seite in bps (Default 10)")
    st.add_argument("--rf", type=float, default=0.02, help="risikofreier Satz p.a., flach (Default 2 %%)")
    st.add_argument("--exec", dest="exec_mode", default="close", choices=["close"],
                    help="Ausführung am Signal-Monatsschluss (Konvention; leicht optimistisch)")
    ev = p.add_argument_group("Auswertung")
    ev.add_argument("--oos-start", default="2016-01-01", help="Out-of-Sample-Beginn ('' = kein Split)")
    ev.add_argument("--grid", action="store_true", help="komplettes vorregistriertes Testprogramm")
    ev.add_argument("--null", action="store_true", help="Null-Test: Zufalls-Ranking statt Momentum")
    ev.add_argument("--demo", action="store_true", help="Synthetik-Daten (Pipeline-Test, kein Markt)")
    ev.add_argument("--csv", default="backtest_ergebnisse.csv", help="Kennzahlen-Ausgabedatei")
    return p


VARIANTS = [
    ("Basis (22, 0-Hyst, ohne Blasenfilter)", {}),
    ("V1 · 12-1-Momentum", {"skip_recent": 1}),
    ("V2 · Hysterese 2 % + Bestätigung 2", {"hyst_out": 2.0, "confirm": 2}),
    ("V3 · + Bollinger-Blase-Filter", {"bubble_filter": True}),
    ("V4a · 15 Titel", {"top_n": 15}),
    ("V4b · 30 Titel", {"top_n": 30}),
    ("Kosten-Sensitivität · 5 bps", {"cost_bps": 5.0}),
    ("Kosten-Sensitivität · 20 bps", {"cost_bps": 20.0}),
    ("NULL-TEST · Zufalls-Ranking", {"null": True}),
]


def main():
    args = build_parser().parse_args()
    if args.oos_start == "":
        args.oos_start = None
    args.null = getattr(args, "null", False)

    if args.demo:
        print("=== DEMO: synthetische Daten – validiert NUR die Pipeline ===")
        monthly, bench_m = make_demo_data()
    else:
        if args.fetch_sp500:
            tickers = fetch_sp500_tickers()
        elif args.tickers_file:
            tickers = [l.strip() for l in open(args.tickers_file) if l.strip() and not l.startswith("#")]
        else:
            sys.exit("Bitte --tickers-file oder --fetch-sp500 angeben (oder --demo).")
        close, _ = load_prices(tickers + [args.benchmark], args.start, args.end, refresh=args.refresh)
        if args.benchmark not in close.columns:
            sys.exit(f"Benchmark {args.benchmark} ohne Daten – anderen Ticker wählen (z. B. SPY).")
        try:
            monthly = close.resample("ME").last()
        except ValueError:
            monthly = close.resample("M").last()
        bench_m = monthly.pop(args.benchmark)
        monthly = monthly.dropna(axis=1, thresh=int(len(monthly) * 0.5))
        print(f"Universum: {monthly.shape[1]} Titel · {monthly.index[0]:%Y-%m} bis {monthly.index[-1]:%Y-%m}"
              f" · Benchmark {args.benchmark}")
        print("!! Survivorship-Hinweis: heutige Ticker-Liste → absolute Zahlen nach oben verzerrt;"
              " Varianten-VERGLEICHE sind belastbarer.")

    results = []
    if args.grid:
        for label, overrides in VARIANTS:
            a = argparse.Namespace(**vars(args))
            for k, v in overrides.items():
                setattr(a, k, v)
            df = simulate(monthly, bench_m, a)
            results += report(df, a, label)
            print(f"  ✓ {label}")
    else:
        label = "NULL-TEST" if args.null else "Lauf"
        df = simulate(monthly, bench_m, args)
        results += report(df, args, label)
        df.drop(columns=[], errors="ignore").to_csv("equity_monatsrenditen.csv")
        print("Monatsrenditen → equity_monatsrenditen.csv")

    tab = pd.DataFrame(results)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 40)
    print("\n", tab.to_string(index=False))
    tab.to_csv(args.csv, index=False)
    print(f"\nKennzahlen → {args.csv}")
    print("\nEinordnung: Punktschätzungen enthalten Survivorship-/Look-ahead-Reste."
          "\nEin guter Backtest ist ein Hypothesen-Check, KEIN Beweis künftiger Profitabilität.")


if __name__ == "__main__":
    main()
