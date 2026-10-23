#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
momentum_screener.py · v1.0 (10.07.2026)
Monatlicher The-Market-Momentum-Screen – kostenlos, ersetzt das 40-CHF-Abo.

WAS ES MACHT
  1. Universum laden: S&P 500 (US) + Stoxx Europe 600 (EU) + SPI/SMI (CH)
     → wie The Market (~1300 Titel). Quelle Wikipedia, mit Fallback-Listen.
  2. Alle Kurse in USD umrechnen (FX via yfinance). WICHTIG: Ohne das
     vergleicht man CHF-/EUR-Aktien mit einem USD-Index – genau der Fehler,
     der im Pine-Indikator als Caveat steht. Hier ist er behoben.
  3. Momentum-Score = Ø aus 6M- und 12M-Kursveränderung (Monatsschluss).
  4. Filter: (a) stärker als Benchmark, (b) über 10-Monats-Durchschnitt.
  5. Bollinger-Kategorie NUR als Information (Backtest 07/2026: harter
     Blase-Ausschluss kostete Rendite → gestrichen, siehe Analyse Abschnitt 4).
  6. Status der eigenen Positionen: halten / verkaufen (Regelbruch).
  7. Portfolio-Vorschlag mit Themen-Deckel (Sektoren via yfinance, nur für
     die Top-Kandidaten → schnell).

BENCHMARK-HÜRDE (zwei Härtegrade)
  --benchmark URTH        weich: stärker als MSCI World (Standard bisher;
                          im Artikel 10.07.2026 schaffen das 507/1300 = 39 %)
  --hard-benchmark        hart: stärker als der STÄRKSTE Leitindex
                          (Proxies EWJ/EEM/QQQ/URTH/SPY – Cortés' eigentliche
                          Messlatte; im Artikel nur 97/1300 = 7,5 %)
  Ehrlich: Die harte Hürde ist NICHT backgetestet. Erst mit
  backtest_momentum.py prüfen (--benchmark QQQ o. ä.), dann glauben.

BEISPIELE
  python3 momentum_screener.py --demo                     # Selbsttest, kein Netz
  python3 momentum_screener.py                            # US+EU+CH, MSCI World
  python3 momentum_screener.py --universe us              # nur US (wie bisher)
  python3 momentum_screener.py --hard-benchmark --top 40
  python3 momentum_screener.py --holdings meine_titel.txt # Status eigener Positionen
Abhängigkeiten:  pip3 install yfinance pandas numpy lxml
"""

import argparse
import datetime as dt
import io
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CACHE = "cache_screener.pkl"

# Währung je Ticker-Endung (deterministisch, kein langsamer .info-Abruf)
CCY_BY_SUFFIX = {
    ".SW": "CHF", ".VX": "CHF",
    ".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".MI": "EUR", ".MC": "EUR",
    ".AS": "EUR", ".BR": "EUR", ".LS": "EUR", ".HE": "EUR", ".VI": "EUR",
    ".IR": "EUR",
    ".L": "GBP",          # Achtung: London notiert in PENCE → /100
    ".ST": "SEK", ".CO": "DKK", ".OL": "NOK", ".WA": "PLN", ".T": "JPY",
}

# Fallback-Listen (falls Wikipedia nicht erreichbar). Bewusst Large/Mid Caps
# mit gängigen yfinance-Endungen. Fehlerhafte Ticker werden beim Laden
# gemeldet und übersprungen – die Liste ist erweiterbar.
FALLBACK_EU = """
ASML.AS ADYEN.AS HEIA.AS INGA.AS PRX.AS PHIA.AS WKL.AS DSFIR.AS AD.AS AKZA.AS
SIE.DE SAP.DE ALV.DE MUV2.DE BAS.DE BAYN.DE BMW.DE MBG.DE VOW3.DE DTE.DE
RHM.DE HEN3.DE ADS.DE IFX.DE MRK.DE LIN.DE DHL.DE EOAN.DE RWE.DE DB1.DE
MTX.DE ZAL.DE HNR1.DE SRT3.DE KNIN.SW
MC.PA OR.PA TTE.PA SAN.PA AIR.PA SU.PA AI.PA BNP.PA CS.PA DG.PA
RMS.PA KER.PA SAF.PA EL.PA ORA.PA VIE.PA STLAP.PA ACA.PA GLE.PA PUB.PA
ENI.MI ISP.MI UCG.MI ENEL.MI G.MI STLAM.MI TEN.MI SPM.MI BAMI.MI RACE.MI
SAN.MC BBVA.MC IBE.MC ITX.MC REP.MC CABK.MC TEF.MC AENA.MC FER.MC AMS.MC
SHEL.L AZN.L HSBA.L ULVR.L BP.L GSK.L RIO.L BATS.L LSEG.L REL.L
DGE.L NG.L GLEN.L BARC.L LLOY.L PRU.L SDR.L AAL.L IMB.L CPG.L
NOVO-B.CO NVO MAERSK-B.CO DSV.CO CARL-B.CO ORSTED.CO
ATCO-A.ST VOLV-B.ST SAND.ST INVE-B.ST ERIC-B.ST HM-B.ST ASSA-B.ST SEB-A.ST
EQNR.OL DNB.OL TGS.OL NHY.OL
RBI.VI OMV.VI VER.VI
""".split()

FALLBACK_CH = """
NESN.SW ROG.SW NOVN.SW UBSG.SW ZURN.SW ABBN.SW SIKA.SW LONN.SW GIVN.SW HOLN.SW
ALC.SW SCMN.SW SREN.SW SLHN.SW GEBN.SW PGHN.SW SOON.SW BAER.SW VACN.SW STMN.SW
KNIN.SW SCHP.SW BALN.SW EMSN.SW SIGN.SW TEMN.SW LOGN.SW ADEN.SW BUCN.SW SFSN.SW
BOSN.SW ACLN.SW HUBN.SW SENS.SW ALSN.SW BCVN.SW GALD.SW AERO.SW DAE.SW ARBN.SW
KARN.SW BELL.SW BION.SW CLN.SW COTN.SW DKSH.SW FHZN.SW FORN.SW GALE.SW GLKBN.SW
HELN.SW IMPN.SW INRN.SW ISN.SW KOMN.SW LEHN.SW LISN.SW LUKN.SW MBTN.SW METN.SW
MOVE.SW OERL.SW PSPN.SW RIEN.SW SGSN.SW SPSN.SW SQN.SW SUN.SW SWON.SW TECN.SW
UHR.SW VETN.SW VZN.SW YPSN.SW ZEHN.SW ZUGER.SW
""".split()

# Proxy-ETFs für die «harte» Hürde (stärkster Leitindex, Cortés-Logik)
HARD_INDICES = {"EWJ": "Japan (Nikkei-Proxy)", "EEM": "MSCI EM",
                "QQQ": "Nasdaq 100", "URTH": "MSCI World", "SPY": "S&P 500"}


# ───────────────────────────── Universum ─────────────────────────────────────

def _wiki_tables(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    return pd.read_html(io.StringIO(html))


def get_us():
    try:
        t = _wiki_tables("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        syms = t["Symbol"].astype(str).str.replace(".", "-", regex=False)
        sect = dict(zip(syms, t["GICS Sector"].astype(str))) if "GICS Sector" in t else {}
        return sorted(syms.unique().tolist()), sect
    except Exception as e:
        print(f"  ! S&P-500-Liste nicht ladbar ({e}) – US wird übersprungen")
        return [], {}


def get_eu():
    try:
        for t in _wiki_tables("https://en.wikipedia.org/wiki/STOXX_Europe_600"):
            if "Ticker" in t.columns:
                syms = [s for s in t["Ticker"].astype(str).tolist() if 1 < len(s) < 12]
                if len(syms) > 100:
                    print(f"  · Stoxx Europe 600: {len(syms)} Ticker von Wikipedia")
                    return sorted(set(syms)), {}
        raise ValueError("keine Ticker-Spalte gefunden")
    except Exception as e:
        print(f"  · Stoxx-600-Liste nicht ladbar ({e}) → Fallback-Liste")
        return sorted(set(FALLBACK_EU)), {}


def get_ch():
    return sorted(set(FALLBACK_CH)), {}


def build_universe(which):
    tickers, sectors = [], {}
    if "us" in which:
        s, sec = get_us(); tickers += s; sectors.update(sec)
    if "eu" in which:
        s, sec = get_eu(); tickers += s; sectors.update(sec)
    if "ch" in which:
        s, sec = get_ch(); tickers += s; sectors.update(sec)
    return sorted(set(tickers)), sectors


# ─────────────────────────── Kurse & Währung ─────────────────────────────────

def ccy_of(ticker):
    for suf, c in CCY_BY_SUFFIX.items():
        if ticker.endswith(suf):
            return c
    return "USD"


def download(tickers, start, chunk=60, pause=2.0):
    """Chunked Download mit Pause (Yahoo-Rate-Limit!). Meldet Ausfälle –
    stiller Datenverlust hat uns in Lauf B schon einmal 400 Titel gekostet."""
    import yfinance as yf
    frames = []
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        for attempt in (1, 2):
            try:
                d = yf.download(part, start=start, auto_adjust=True,
                                progress=False, group_by="column", threads=False)
                c = d["Close"] if isinstance(d.columns, pd.MultiIndex) else \
                    d[["Close"]].rename(columns={"Close": part[0]})
                frames.append(c)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ! Chunk {i}-{i+len(part)} fehlgeschlagen: {e}")
                else:
                    time.sleep(5)
        print(f"  … {min(i+chunk, len(tickers))}/{len(tickers)}")
        time.sleep(pause)
    if not frames:
        sys.exit("Kein einziger Kurs geladen – Netzwerk/Rate-Limit prüfen.")
    return pd.concat(frames, axis=1).sort_index()


def to_usd(close, verbose=True):
    """Alle Kursreihen in USD. London (.L) notiert in Pence → /100."""
    import yfinance as yf
    needed = sorted({ccy_of(c) for c in close.columns} - {"USD"})
    fx = {}
    for c in needed:
        try:
            s = yf.download(f"{c}USD=X", start=close.index[0], auto_adjust=True,
                            progress=False)["Close"]
            fx[c] = s.reindex(close.index).ffill()
        except Exception as e:
            print(f"  ! FX {c}USD fehlgeschlagen ({e}) – Titel dieser Währung entfallen")
    out = {}
    for col in close.columns:
        c = ccy_of(col)
        px = close[col]
        if col.endswith(".L"):
            px = px / 100.0                     # Pence → Pfund
        if c == "USD":
            out[col] = px
        elif c in fx:
            f = fx[c]
            out[col] = px * (f.iloc[:, 0] if isinstance(f, pd.DataFrame) else f)
    if verbose and needed:
        print(f"  · Währungsumrechnung: {', '.join(needed)} → USD")
    return pd.DataFrame(out)


def monthly_from(close):
    try:
        return close.resample("ME").last()
    except ValueError:
        return close.resample("M").last()       # pandas < 2.2


# ───────────────────────────── Kennzahlen ────────────────────────────────────

def score_of(monthly):
    m6 = monthly / monthly.shift(6) - 1
    m12 = monthly / monthly.shift(12) - 1
    return (m6 + m12) / 2 * 100, m6 * 100, m12 * 100


def category(monthly, tight_p=25, bubble_p=85, laggard_pct=75):
    """Bollinger-Einordnung – NUR INFORMATION (kein Filter, s. Analyse Abschn. 4)."""
    mid = monthly.rolling(20).mean()
    sd = monthly.rolling(20).std()
    bw = (4 * sd / mid) * 100
    rk = bw.rolling(36).rank(pct=True) * 100
    hi5 = monthly.rolling(60).max()
    upper = mid + 2 * sd
    last = monthly.iloc[-1]
    was_tight = (rk.shift(1) < tight_p) | (rk.shift(2) < tight_p) | (rk.shift(3) < tight_p)
    out = {}
    for c in monthly.columns:
        try:
            if was_tight[c].iloc[-1] and last[c] > upper[c].iloc[-1]:
                out[c] = "Ausbruch"
            elif rk[c].iloc[-1] >= bubble_p and last[c] > mid[c].iloc[-1]:
                out[c] = "Blase"
            elif last[c] < hi5[c].iloc[-1] * laggard_pct / 100:
                out[c] = "Nachzügler"
            elif last[c] > mid[c].iloc[-1]:
                out[c] = "Stabiler Trend"
            else:
                out[c] = "Schwach"
        except Exception:
            out[c] = "—"
    return pd.Series(out)


def sectors_for(tickers, known):
    """Sektor nur für die Top-Kandidaten holen (schnell genug)."""
    import yfinance as yf
    out = {}
    for t in tickers:
        if t in known and str(known[t]) != "nan":
            out[t] = known[t]
            continue
        try:
            info = yf.Ticker(t).info
            out[t] = info.get("sector") or "—"
        except Exception:
            out[t] = "—"
    return out


# ──────────────────────────── Demo (Selbsttest) ──────────────────────────────

def demo_data(n=120, months=90, seed=11):
    rng = np.random.default_rng(seed)
    try:
        idx = pd.date_range("2019-01-31", periods=months, freq="ME")
    except ValueError:
        idx = pd.date_range("2019-01-31", periods=months, freq="M")
    cols = ([f"US{i:03d}" for i in range(n // 3)] +
            [f"EU{i:03d}.DE" for i in range(n // 3)] +
            [f"CH{i:03d}.SW" for i in range(n - 2 * (n // 3))])
    data = {}
    for i, c in enumerate(cols):
        drift = rng.choice([-0.008, 0.002, 0.012, 0.022])
        r = drift + rng.normal(0, 0.06, months)
        data[c] = 100 * np.cumprod(1 + r)
    m = pd.DataFrame(data, index=idx)
    bench = m.mean(axis=1).rename("BENCH")
    return m, bench


# ───────────────────────────────── Main ──────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--universe", default="us,eu,ch", help="us / eu / ch, kommasepariert")
    p.add_argument("--benchmark", default="URTH", help="weiche Hürde (Default MSCI World)")
    p.add_argument("--hard-benchmark", action="store_true",
                   help="harte Hürde: stärkster Leitindex (Cortés-Logik, UNGETESTET)")
    p.add_argument("--top", type=int, default=40, help="Anzahl angezeigter Kandidaten")
    p.add_argument("--portfolio-size", type=int, default=22)
    p.add_argument("--theme-cap", type=int, default=4, help="max. Titel je Sektor")
    p.add_argument("--holdings", help="Datei mit aktuellen Positionen (ein Ticker/Zeile)")
    p.add_argument("--years", type=int, default=7, help="Kurshistorie in Jahren")
    p.add_argument("--refresh", action="store_true", help="Cache ignorieren")
    p.add_argument("--no-sectors", action="store_true", help="Sektor-Abruf überspringen")
    p.add_argument("--demo", action="store_true", help="Selbsttest ohne Netz")
    a = p.parse_args()

    today = dt.date.today().isoformat()
    print(f"\n=== Momentum-Screen {today} ===")

    if a.demo:
        print("DEMO: synthetische Daten – prüft nur die Pipeline, keine echten Titel.")
        monthly, bench_m = demo_data()
        sect_known, hard_scores = {}, {}
    else:
        start = (dt.date.today() - dt.timedelta(days=365 * a.years)).isoformat()
        which = [x.strip() for x in a.universe.split(",")]
        print(f"Universum: {which}")
        tickers, sect_known = build_universe(which)
        print(f"  · {len(tickers)} Ticker im Universum")
        bench_list = list(HARD_INDICES) if a.hard_benchmark else [a.benchmark]
        need = tickers + bench_list

        if os.path.exists(CACHE) and not a.refresh:
            key, close = pd.read_pickle(CACHE)
            if key != (tuple(need), start):
                close = None
            else:
                print(f"[Cache] {CACHE}")
        else:
            close = None
        if close is None:
            print("[Download] (Pausen gegen Rate-Limit – dauert einige Minuten)")
            close = download(need, start)
            pd.to_pickle(((tuple(need), start), close), CACHE)

        close = close.dropna(axis=1, how="all")
        got = [t for t in tickers if t in close.columns]
        miss = len(tickers) - len(got)
        print(f"  · Kurse erhalten: {len(got)} Titel" +
              (f"  (⚠ {miss} ohne Daten – falsche Ticker oder Rate-Limit)" if miss else ""))
        close = to_usd(close)
        monthly = monthly_from(close).dropna(axis=1, thresh=14)
        bench_cols = [b for b in bench_list if b in monthly.columns]
        if not bench_cols:
            sys.exit("Benchmark ohne Daten – anderen Ticker wählen.")
        bench_all = monthly[bench_cols]
        monthly = monthly.drop(columns=bench_cols)

    # ── Scores ──
    sc, m6, m12 = score_of(monthly)
    if a.demo:
        bs, _, _ = score_of(bench_m.to_frame("B"))
        hurdle, hurdle_name = bs["B"].iloc[-1], "Demo-Benchmark"
    else:
        bs, _, _ = score_of(bench_all)
        last_b = bs.iloc[-1]
        hurdle = float(last_b.max())
        hurdle_name = (f"{last_b.idxmax()} ({HARD_INDICES.get(last_b.idxmax(), '')})"
                       if a.hard_benchmark else a.benchmark)

    ma10 = monthly.rolling(10).mean()
    above = monthly.iloc[-1] > ma10.iloc[-1]
    cat = category(monthly)

    df = pd.DataFrame({
        "Score %": sc.iloc[-1].round(1),
        "6M %": m6.iloc[-1].round(1),
        "12M %": m12.iloc[-1].round(1),
        "Über 10M-MA": above.map({True: "ja", False: "nein"}),
        "Stärker als Hürde": (sc.iloc[-1] > hurdle).map({True: "ja", False: "nein"}),
        "Kategorie (Info)": cat,
        "Kurs USD": monthly.iloc[-1].round(2),
    }).dropna(subset=["Score %"]).sort_values("Score %", ascending=False)

    regel = df[(df["Über 10M-MA"] == "ja") & (df["Stärker als Hürde"] == "ja")]
    print(f"\nHürde: Score > {hurdle:.1f} %  [{hurdle_name}]")
    print(f"Regelkonform: {len(regel)} von {len(df)} Titeln ({len(regel)/max(len(df),1)*100:.0f} %)")

    f_rank = f"screen_ranking_{today}.csv"
    df.to_csv(f_rank)
    print(f"Vollständige Rangliste → {f_rank}")

    # ── Sektoren + Portfolio-Vorschlag mit Themen-Deckel ──
    cand = regel.head(max(a.top, a.portfolio_size * 3)).index.tolist()
    if a.no_sectors or a.demo:
        sec = {t: sect_known.get(t, "—") for t in cand}
    else:
        print(f"  · Sektoren für {len(cand)} Kandidaten …")
        sec = sectors_for(cand, sect_known)
    regel = regel.copy()
    regel["Sektor"] = pd.Series(sec).reindex(regel.index).fillna("—")

    pick, counts = [], {}
    for t in regel.index:
        s = regel.loc[t, "Sektor"]
        if s != "—" and counts.get(s, 0) >= a.theme_cap:
            continue
        pick.append(t)
        counts[s] = counts.get(s, 0) + 1
        if len(pick) >= a.portfolio_size:
            break
    vorschlag = regel.loc[pick]
    f_pf = f"screen_portfolio_{today}.csv"
    vorschlag.to_csv(f_pf)

    print(f"\n── Vorschlag: {len(vorschlag)} Titel, Themen-Deckel {a.theme_cap} ──")
    print(vorschlag[["Score %", "Über 10M-MA", "Kategorie (Info)", "Sektor"]].to_string())
    print(f"\nSektor-Verteilung: {dict(sorted(counts.items(), key=lambda x: -x[1]))}")
    print(f"Vorschlag → {f_pf}")

    # ── Status der eigenen Positionen ──
    if a.holdings and os.path.exists(a.holdings):
        held = [l.strip() for l in open(a.holdings) if l.strip() and not l.startswith("#")]
        rows = []
        for t in held:
            if t not in df.index:
                rows.append((t, None, "?", "?", "—", "KEINE DATEN – manuell prüfen"))
                continue
            r = df.loc[t]
            ok = r["Über 10M-MA"] == "ja" and r["Stärker als Hürde"] == "ja"
            grund = ("halten" if ok else
                     "VERKAUFEN – unter 10M-MA" if r["Über 10M-MA"] == "nein" else
                     "VERKAUFEN – aus dem Screen gefallen")
            rows.append((t, r["Score %"], r["Über 10M-MA"], r["Stärker als Hürde"],
                         r["Kategorie (Info)"], grund))
        st = pd.DataFrame(rows, columns=["Ticker", "Score %", "Über 10M-MA",
                                         "Stärker als Hürde", "Kategorie (Info)", "Aktion"])
        f_st = f"screen_status_{today}.csv"
        st.to_csv(f_st, index=False)
        n_sell = int((st["Aktion"].str.startswith("VERKAUFEN")).sum())
        print(f"\n── Status deiner {len(held)} Positionen: {n_sell} Verkaufssignale ──")
        print(st.to_string(index=False))
        print(f"Status → {f_st}")

    print("\nHinweise: Kategorie ist NUR Information (Blase-Filter gestrichen, "
          "Backtest 07/2026).\nRegelbasierte Sortierhilfe, keine Anlageberatung.")


if __name__ == "__main__":
    main()
