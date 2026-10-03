#!/usr/bin/env python3
"""Swing Desk indicator engine (stdlib only).

Ports of two open-source TradingView scripts, computed on daily bars:
  * Smart Money Concepts [LuxAlgo]  (CC BY-NC-SA 4.0): swing/internal structure
    (BOS, CHoCH), order blocks with ATR filter and mitigation, fair value gaps,
    premium/discount/equilibrium zones from the trailing swing range.
  * %R Trend Exhaustion [upslidedown]: fast Williams %R (21, EMA 7) and slow
    %R (112, EMA 3); joint overbought above -20, joint oversold below -80;
    reversal arrows when the joint zone breaks; %R crossovers.
Plus the desk's classic set: SMA 50/200, EMA 10/20, RSI 14/2, ADX 10, ATR 14,
20-day high pullback, 20-day volume average, the setup checks A, B, C, and the
Reversion book's rule R (RSI(2) mean reversion, see reversion()).

Usage:
  python desk_indicators.py bars.json [params.json] > report.json

bars.json is either the raw get_equity_historicals output
({"data":{"results":[{"symbol":..., "bars":[...]}]}}) or a plain
{"SYM": [{"date","open","high","low","close","volume"}, ...]} mapping.
params.json (optional) overrides the desk's tunable parameters.
"""
import json, math, sys
from datetime import datetime, timezone

DEFAULT_PARAMS = {"rsi_low": 38, "rsi_high": 55, "min_adx": 20, "max_pullback_pct": 8,
                  "target_r": 2, "trail_ema": 10, "setup_b_enabled": True, "max_daily_entries": 2,
                  # levers settled by the 144-variant sweep over 2026-06-22..09-04 (desk_backtest.py / desk_sweep.py):
                  # 2R target, 15-day time stop, volume filter on, %R level -40 -> 31 trades, +$595, +0.60R per trade
                  "stop_atr_mult": 0.25,      # stop = pullback low (A) / box bottom (C) minus this many ATR(14)
                  "hold_days_a": 15, "hold_days_b": 5, "hold_days_c": 15,
                  "require_vol_below": True,  # Setup A: yesterday's volume below the 20-day average
                  "wr_pullback_level": -40,   # Setup A: fast %R must have dipped to this within 3 bars
                  "wr_c_mode": "joint",       # Setup C: "joint" = both %R leave the oversold zone; "fast" = fast %R alone crosses up through -80 or over the slow line below -50
                  "c_tap_bars": 3,
                  "min_stop_pct": 2.0,        # skip a setup whose stop sits closer than this to the trigger (noise)
                  "scale_out": True,          # at the target sell half, stop to +1R on the rest, then trail
                  # Rule R: RSI(2) mean reversion (Connors style). Example rule, OFF by default.
                  "rev_enabled": False, "rev_rsi_max": 5, "rev_slots": 5, "rev_stop_atr": 2.0,
                  # Setup P: example of an options rule (an oscillator zone -> a defined-risk vertical spread). Replace with your own.
                  "wr_strict_os": -90,        # both %R lines must be below this (the "all the way down" zone)
                  "spread_delta_lo": 0.09, "spread_delta_hi": 0.13, "spread_delta_target": 0.11,
                  "spread_dte_min": 10, "spread_dte_max": 14,   # calendar days to expiry
                  "spread_tp": 0.75,          # close when the spread can be bought back for 25% of the credit
                  "spread_sl": 2.0,           # close when the loss reaches 200% of the credit (spread mark >= 3 x credit)
                  "spread_min_credit_pct": 5, # credit at least this % of the wing width
                  "spread_risk_usd": 500, "spread_slots": 10, "spread_per_name": 2, "spread_max_daily": 6}
INDEX_ETFS = {"SPY", "QQQ", "IWM", "DIA"}
SWING_LEN, INTERNAL_LEN = 50, 5
TAP_BARS = 3  # how many recent bars count as "tapped" a box; analyze() sets it from params
WR_FAST, WR_FAST_SMOOTH, WR_SLOW, WR_SLOW_SMOOTH, WR_THRESHOLD = 21, 7, 112, 3, 20


# ----------------------------------------------------------------- helpers
def sma(v, n):
    out = [None] * len(v); s = 0.0
    for i, x in enumerate(v):
        if x is None: continue
        s += x
        if i >= n: s -= v[i - n] if v[i - n] is not None else 0
        if i >= n - 1: out[i] = s / n
    return out

def ema(v, n):
    out = [None] * len(v); k = 2.0 / (n + 1); prev = None; seed = []
    for i, x in enumerate(v):
        if x is None: continue
        if prev is None:
            seed.append(x)
            if len(seed) == n: prev = sum(seed) / n; out[i] = prev
            continue
        prev = x * k + prev * (1 - k); out[i] = prev
    return out

def rma(v, n):
    out = [None] * len(v); prev = None; seed = []
    for i, x in enumerate(v):
        if x is None: continue
        if prev is None:
            seed.append(x)
            if len(seed) == n: prev = sum(seed) / n; out[i] = prev
            continue
        prev = (prev * (n - 1) + x) / n; out[i] = prev
    return out

def rsi(c, n):
    up = [None]; dn = [None]
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]; up.append(max(d, 0.0)); dn.append(max(-d, 0.0))
    au, ad = rma(up, n), rma(dn, n)
    return [None if (au[i] is None or ad[i] is None) else (100.0 if ad[i] == 0 else 100 - 100 / (1 + au[i] / ad[i])) for i in range(len(c))]

def true_range(h, l, c):
    return [None] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]

def atr(h, l, c, n): return rma(true_range(h, l, c), n)

def adx(h, l, c, n):
    tr = true_range(h, l, c); pdm = [None]; ndm = [None]
    for i in range(1, len(c)):
        up = h[i] - h[i - 1]; dn = l[i - 1] - l[i]
        pdm.append(up if (up > dn and up > 0) else 0.0); ndm.append(dn if (dn > up and dn > 0) else 0.0)
    atr_, p, m = rma(tr, n), rma(pdm, n), rma(ndm, n)
    dx = [None] * len(c)
    for i in range(len(c)):
        if atr_[i] and p[i] is not None and m[i] is not None:
            pdi, ndi = 100 * p[i] / atr_[i], 100 * m[i] / atr_[i]
            dx[i] = 0.0 if (pdi + ndi) == 0 else 100 * abs(pdi - ndi) / (pdi + ndi)
    return rma(dx, n)

def highest(v, n, i): return max(v[max(0, i - n + 1): i + 1])
def lowest(v, n, i): return min(v[max(0, i - n + 1): i + 1])

def williams_r(h, l, c, n):
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        hh, ll = highest(h, n, i), lowest(l, n, i)
        out[i] = 0.0 if hh == ll else 100.0 * (c[i] - hh) / (hh - ll)
    return out

def crossover(a, b, i): return a[i] is not None and b is not None and a[i - 1] is not None and a[i] > b and a[i - 1] <= b
def crossunder(a, b, i): return a[i] is not None and b is not None and a[i - 1] is not None and a[i] < b and a[i - 1] >= b
def r2(x): return None if x is None else round(x, 2)
def r4(x): return None if x is None else round(x, 4)


# ------------------------------------------------------- Smart Money Concepts
def smc(o, h, l, c, dates, swing_len=SWING_LEN, internal_len=INTERNAL_LEN):
    n = len(c)
    atr200 = atr(h, l, c, 200)
    cum_range = 0.0; cmean = [None] * n
    for i in range(n):
        cum_range += h[i] - l[i]; cmean[i] = cum_range / (i + 1)

    def swings(length):
        os = 0; tops = [None] * n; btms = [None] * n
        for i in range(length, n):
            upper, lower = highest(h, length, i), lowest(l, length, i)
            prev = os
            if h[i - length] > upper: os = 0
            elif l[i - length] < lower: os = 1
            if os == 0 and prev != 0: tops[i] = (i - length, h[i - length])
            if os == 1 and prev != 1: btms[i] = (i - length, l[i - length])
        return tops, btms

    tops, btms = swings(swing_len); itops, ibtms = swings(internal_len)
    trend = itrend = 0
    top_y = btm_y = itop_y = ibtm_y = None; top_x = btm_x = itop_x = ibtm_x = 0
    top_cross = btm_cross = itop_cross = ibtm_cross = False
    trail_up, trail_dn = h[0], l[0]; trail_up_x = trail_dn_x = 0
    events = []; obs = []; iobs = []; fvgs = []; swing_points = []
    cum_delta = 0.0

    def ob_coord(use_max, loc, i):
        mn, mx, idx = float('inf'), 0.0, None
        for j in range(1, max(1, (i - loc))):
            k = i - j
            thr = atr200[k] if atr200[k] is not None else cmean[k]
            if (h[k] - l[k]) < thr * 2:
                if use_max:
                    if h[k] > mx: mx, mn, idx = h[k], l[k], k
                else:
                    if l[k] < mn: mn, mx, idx = l[k], h[k], k
        if idx is None: return None
        return {"top": mx, "btm": mn, "bar": idx, "date": dates[idx], "dir": -1 if use_max else 1}

    for i in range(1, n):
        if tops[i]:
            x, y = tops[i]; top_cross = True; top_y, top_x = y, x
            swing_points.append({"bar": x, "date": dates[x], "kind": "HH" if y > trail_up else "LH", "price": y})
            trail_up, trail_up_x = y, x
        if btms[i]:
            x, y = btms[i]; btm_cross = True; btm_y, btm_x = y, x
            swing_points.append({"bar": x, "date": dates[x], "kind": "LL" if y < trail_dn else "HL", "price": y})
            trail_dn, trail_dn_x = y, x
        if itops[i]:
            x, y = itops[i]; itop_cross = True; itop_y, itop_x = y, x
        if ibtms[i]:
            x, y = ibtms[i]; ibtm_cross = True; ibtm_y, ibtm_x = y, x
        if h[i] >= trail_up: trail_up, trail_up_x = h[i], i
        if l[i] <= trail_dn: trail_dn, trail_dn_x = l[i], i

        # internal bullish structure
        if itop_y is not None and crossover(c, itop_y, i) and itop_cross and top_y != itop_y:
            events.append({"bar": i, "date": dates[i], "level": "internal", "kind": "CHoCH" if itrend < 0 else "BOS", "dir": 1, "price": itop_y})
            itop_cross = False; itrend = 1
            ob = ob_coord(False, itop_x, i)
            if ob: iobs.insert(0, ob)
        # swing bullish structure
        if top_y is not None and crossover(c, top_y, i) and top_cross:
            events.append({"bar": i, "date": dates[i], "level": "swing", "kind": "CHoCH" if trend < 0 else "BOS", "dir": 1, "price": top_y})
            top_cross = False; trend = 1
            ob = ob_coord(False, top_x, i)
            if ob: obs.insert(0, ob)
        # internal bearish structure
        if ibtm_y is not None and crossunder(c, ibtm_y, i) and ibtm_cross and btm_y != ibtm_y:
            events.append({"bar": i, "date": dates[i], "level": "internal", "kind": "CHoCH" if itrend > 0 else "BOS", "dir": -1, "price": ibtm_y})
            ibtm_cross = False; itrend = -1
            ob = ob_coord(True, ibtm_x, i)
            if ob: iobs.insert(0, ob)
        # swing bearish structure
        if btm_y is not None and crossunder(c, btm_y, i) and btm_cross:
            events.append({"bar": i, "date": dates[i], "level": "swing", "kind": "CHoCH" if trend > 0 else "BOS", "dir": -1, "price": btm_y})
            btm_cross = False; trend = -1
            ob = ob_coord(True, btm_x, i)
            if ob: obs.insert(0, ob)

        # order block mitigation (a bullish block dies when the body closes below it)
        for lst in (obs, iobs):
            keep = []
            for ob in lst:
                if ob["bar"] == i: keep.append(ob); continue
                if ob["dir"] == 1 and min(c[i], o[i]) < ob["btm"]: continue
                if ob["dir"] == -1 and max(c[i], o[i]) > ob["top"]: continue
                keep.append(ob)
            lst[:] = keep[:5]

        # fair value gaps with the auto threshold
        delta_per = (c[i] - o[i]) / o[i] * 100 if o[i] else 0.0
        cum_delta += abs(delta_per); threshold = cum_delta / i * 2
        if i >= 2:
            if l[i] > h[i - 2] and c[i - 1] > h[i - 2] and delta_per > threshold:
                fvgs.insert(0, {"top": l[i], "btm": h[i - 2], "bar": i, "date": dates[i], "dir": 1})
            if h[i] < l[i - 2] and c[i - 1] < l[i - 2] and -delta_per > threshold:
                fvgs.insert(0, {"top": l[i - 2], "btm": h[i], "bar": i, "date": dates[i], "dir": -1})
        keep = []
        for g in fvgs:
            if g["bar"] == i: keep.append(g); continue
            if g["dir"] == 1 and l[i] < g["btm"]: continue
            if g["dir"] == -1 and h[i] > g["top"]: continue
            keep.append(g)
        fvgs = keep[:8]

    rng = trail_up - trail_dn
    pct = None if rng <= 0 else (c[-1] - trail_dn) / rng
    zone = None if pct is None else ("premium" if pct > 0.525 else "discount" if pct < 0.475 else "equilibrium")
    last_i = n - 1
    def tapped(box, k=TAP_BARS):
        return any(l[j] <= box["top"] and c[j] > box["btm"] for j in range(max(0, n - k), n))
    return {
        "swing_trend": trend, "internal_trend": itrend,
        "trail_up": r2(trail_up), "trail_dn": r2(trail_dn), "range_pct": r4(pct), "zone": zone,
        "premium_band": [r2(0.95 * trail_up + 0.05 * trail_dn), r2(trail_up)],
        "equilibrium_band": [r2(0.525 * trail_dn + 0.475 * trail_up), r2(0.525 * trail_up + 0.475 * trail_dn)],
        "discount_band": [r2(trail_dn), r2(0.95 * trail_dn + 0.05 * trail_up)],
        "events": [dict(e, price=r2(e["price"]), bars_ago=last_i - e["bar"]) for e in events[-8:]],
        "swing_points": [dict(s, price=r2(s["price"]), bars_ago=last_i - s["bar"]) for s in swing_points[-6:]],
        "swing_order_blocks": [dict(b, top=r2(b["top"]), btm=r2(b["btm"]), bars_ago=last_i - b["bar"], tapped_recently=tapped(b)) for b in obs],
        "internal_order_blocks": [dict(b, top=r2(b["top"]), btm=r2(b["btm"]), bars_ago=last_i - b["bar"], tapped_recently=tapped(b)) for b in iobs],
        "fair_value_gaps": [dict(g, top=r2(g["top"]), btm=r2(g["btm"]), bars_ago=last_i - g["bar"], tapped_recently=tapped(g)) for g in fvgs],
        "bearish_internal_choch_last5": any(e["level"] == "internal" and e["kind"] == "CHoCH" and e["dir"] == -1 and last_i - e["bar"] <= 5 for e in events),
        "bullish_internal_choch_last5": any(e["level"] == "internal" and e["kind"] == "CHoCH" and e["dir"] == 1 and last_i - e["bar"] <= 5 for e in events),
    }


# ---------------------------------------------------------- %R Trend Exhaustion
def wr_exhaustion(h, l, c):
    fast = ema(williams_r(h, l, c, WR_FAST), WR_FAST_SMOOTH)
    slow = ema(williams_r(h, l, c, WR_SLOW), WR_SLOW_SMOOTH)
    ob_line, os_line = -WR_THRESHOLD, -100 + WR_THRESHOLD
    n = len(c); overbought = [False] * n; oversold = [False] * n
    for i in range(n):
        if fast[i] is None or slow[i] is None: continue
        overbought[i] = fast[i] > ob_line and slow[i] > ob_line
        oversold[i] = fast[i] < os_line and slow[i] < os_line
    up_signals, down_signals, cross_up, cross_dn, fast_up = [], [], [], [], []
    for i in range(1, n):
        if oversold[i - 1] and not oversold[i]: up_signals.append(i)
        if overbought[i - 1] and not overbought[i]: down_signals.append(i)
        if fast[i] is not None and slow[i] is not None and fast[i - 1] is not None and slow[i - 1] is not None:
            if fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]: cross_up.append(i)
            if fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]: cross_dn.append(i)
        if fast[i] is not None and fast[i - 1] is not None and fast[i - 1] < os_line <= fast[i]: fast_up.append(i)
    last = n - 1
    ago = lambda lst: (last - lst[-1]) if lst else None
    return {
        "fast": r2(fast[last]), "slow": r2(slow[last]),
        "fast_prev": r2(fast[last - 1]) if last >= 1 else None,
        "zone": "overbought" if overbought[last] else "oversold" if oversold[last] else "none",
        "up_signal_bars_ago": ago(up_signals), "down_signal_bars_ago": ago(down_signals),
        "cross_up_bars_ago": ago(cross_up), "cross_down_bars_ago": ago(cross_dn),
        "fast_up_bars_ago": ago(fast_up),
        "fast_min_last3": r2(min(x for x in fast[max(0, last - 2): last + 1] if x is not None)) if fast[last] is not None else None,
        "series_fast": [r2(x) for x in fast[-60:]], "series_slow": [r2(x) for x in slow[-60:]],
    }


# ------------------------------------------------------------------ classic
def classic(o, h, l, c, v, dates):
    n = len(c); last = n - 1
    s50, s200, e10, e20 = sma(c, 50), sma(c, 200), ema(c, 10), ema(c, 20)
    r14, r2_, a10, at14 = rsi(c, 14), rsi(c, 2), adx(h, l, c, 10), atr(h, l, c, 14)
    high20 = highest(h, 20, last)
    vol20 = (sum(v[last - 20: last]) / 20) if last >= 20 else None
    touched = False
    for j in range(max(1, last - 2), last + 1):
        if (e10[j] is not None and l[j] <= e10[j]) or (e20[j] is not None and l[j] <= e20[j]): touched = True
    return {
        "date": dates[last], "close": r2(c[last]), "open": r2(o[last]), "high": r2(h[last]), "low": r2(l[last]),
        "prev_close": r2(c[last - 1]) if last >= 1 else None,
        "change_pct": r2((c[last] / c[last - 1] - 1) * 100) if last >= 1 else None,
        "gap_pct": r2((o[last] / c[last - 1] - 1) * 100) if last >= 1 else None,
        "sma50": r2(s50[last]), "sma200": r2(s200[last]), "ema10": r2(e10[last]), "ema20": r2(e20[last]),
        "ema10_prev": r2(e10[last - 1]) if last >= 1 else None,
        "rsi14": r2(r14[last]), "rsi2": r2(r2_[last]), "adx10": r2(a10[last]), "atr14": r2(at14[last]),
        "high20": r2(high20), "pullback_pct": r2((1 - c[last] / high20) * 100),
        "pullback_low": r2(lowest(l, 5, last)),
        "vol_avg20": None if vol20 is None else round(vol20), "volume": v[last],
        "volume_below_avg": (v[last] < vol20) if vol20 else None,
        "touched_ema_last3": touched, "yesterday_high": r2(h[last]),
        "prev_high": r2(h[last - 1]) if last >= 1 else None,
        "close_above_prev_high": (c[last] > h[last - 1]) if last >= 1 else False,
        "bars": n,
    }


# ------------------------------------------------------------------- setups
def setups(sym, cl, sm, wr, params, regime_ok=True):
    reasons_a, reasons_b, reasons_c = [], [], []
    p = dict(DEFAULT_PARAMS); p.update(params or {})
    need = lambda cond, why, lst: (None if cond else lst.append(why))
    # Setup A: trend pullback, confirmed by SMC and %R
    ok = all(x is not None for x in (cl["sma50"], cl["sma200"], cl["adx10"], cl["rsi14"], cl["atr14"]))
    if not ok: reasons_a.append("not enough history")
    else:
        need(regime_ok, "regime gate off", reasons_a)
        need(cl["close"] > cl["sma50"] > cl["sma200"], "close > sma50 > sma200 fails", reasons_a)
        need(cl["adx10"] >= p["min_adx"], "adx %.1f < %s" % (cl["adx10"], p["min_adx"]), reasons_a)
        need(p["rsi_low"] <= cl["rsi14"] <= p["rsi_high"], "rsi %.1f outside %s-%s" % (cl["rsi14"], p["rsi_low"], p["rsi_high"]), reasons_a)
        need(cl["touched_ema_last3"], "no ema10/20 touch in last 3 sessions", reasons_a)
        need(cl["pullback_pct"] <= p["max_pullback_pct"], "pullback %.1f%% > %s%%" % (cl["pullback_pct"], p["max_pullback_pct"]), reasons_a)
        need(cl["volume_below_avg"] or not p.get("require_vol_below", True), "pullback volume not below 20d average", reasons_a)
        need(not sm["bearish_internal_choch_last5"], "SMC bearish internal CHoCH in last 5 bars", reasons_a)
        need(not (sm["swing_trend"] == -1 and sm["internal_trend"] == -1), "SMC swing and internal structure both bearish", reasons_a)
        need(sm["range_pct"] is None or sm["range_pct"] <= 0.95, "at the top of the SMC range (strong premium)", reasons_a)
        lvl = p.get("wr_pullback_level", -50)
        need(wr["fast_min_last3"] is not None and wr["fast_min_last3"] <= lvl, "%%R fast never below %s in last 3 bars (no pullback)" % lvl, reasons_a)
        need(wr["zone"] != "overbought", "%R joint overbought (extended)", reasons_a)
    # Setup B: index dip
    if sym not in INDEX_ETFS: reasons_b.append("not an index ETF")
    elif not p.get("setup_b_enabled", True): reasons_b.append("setup B disabled")
    elif cl["sma200"] is None or cl["rsi2"] is None: reasons_b.append("not enough history")
    else:
        need(cl["close"] > cl["sma200"], "close below sma200", reasons_b)
        need(cl["rsi2"] < 10, "rsi2 %.1f >= 10" % cl["rsi2"], reasons_b)
        need(wr["fast"] is not None and wr["fast"] < -80, "%R fast not below -80", reasons_b)
    # Setup C: SMC order block / FVG tap with %R exhaustion reversal
    stop_ref = None
    if cl["sma200"] is None or cl["atr14"] is None: reasons_c.append("not enough history")
    else:
        need(regime_ok, "regime gate off", reasons_c)
        # the 50-bar swing structure lags on daily charts, so price above both averages also counts as bullish context
        trend_ok = sm["swing_trend"] == 1 or (cl["close"] > cl["sma200"] and cl["sma50"] is not None and cl["close"] > cl["sma50"])
        need(trend_ok, "SMC swing structure not bullish and price not above sma50/sma200", reasons_c)
        boxes = [b for b in sm["internal_order_blocks"] + sm["swing_order_blocks"] + sm["fair_value_gaps"] if b["dir"] == 1 and b["tapped_recently"]]
        need(bool(boxes), "no bullish order block or FVG tapped in last 3 bars", reasons_c)
        if boxes: stop_ref = min(b["btm"] for b in boxes)
        if p.get("wr_c_mode", "joint") == "fast":
            wr_ok = (wr.get("fast_up_bars_ago") is not None and wr["fast_up_bars_ago"] <= 3) or \
                    (wr["cross_up_bars_ago"] is not None and wr["cross_up_bars_ago"] <= 3 and wr["fast"] is not None and wr["fast"] < -50)
            need(wr_ok, "no fast %R cross up through -80 (or over slow below -50) in last 3 bars", reasons_c)
        else:
            wr_ok = (wr["up_signal_bars_ago"] is not None and wr["up_signal_bars_ago"] <= 3) or \
                    (wr["cross_up_bars_ago"] is not None and wr["cross_up_bars_ago"] <= 3 and wr["slow"] is not None and wr["slow"] < -50)
            need(wr_ok, "no %R exhaustion up-signal or oversold cross in last 3 bars", reasons_c)
        need(wr["zone"] != "overbought", "%R joint overbought", reasons_c)
        need(cl["close"] > cl["sma50"] if cl["sma50"] else True, "close below sma50", reasons_c)
    atr_ = cl["atr14"] or 0; k_atr = p.get("stop_atr_mult", 0.25)
    out = {
        "A": {"ok": not reasons_a, "reasons": reasons_a, "hold_days": p.get("hold_days_a", 10),
              "trigger": cl["yesterday_high"], "stop": r2(cl["pullback_low"] - k_atr * atr_) if cl["pullback_low"] else None},
        "B": {"ok": not reasons_b, "reasons": reasons_b, "hold_days": p.get("hold_days_b", 5),
              "trigger": cl["yesterday_high"], "stop": r2(cl["yesterday_high"] * 0.96) if cl["yesterday_high"] else None},
        "C": {"ok": not reasons_c, "reasons": reasons_c, "hold_days": p.get("hold_days_c", 10),
              "trigger": cl["yesterday_high"], "stop": r2(stop_ref - k_atr * atr_) if stop_ref else None, "stop_ref": stop_ref},
    }
    for k in out:
        s = out[k]
        if s["trigger"] and s["stop"] and s["trigger"] > s["stop"]:
            s["target"] = r2(s["trigger"] + p["target_r"] * (s["trigger"] - s["stop"]))
            s["risk_per_share"] = r2(s["trigger"] - s["stop"])
            s["stop_distance_pct"] = r2((s["trigger"] - s["stop"]) / s["trigger"] * 100)
            if s["stop_distance_pct"] > 8:
                s["ok"] = False; s["reasons"].append("stop %.1f%% below trigger, box too wide for a swing" % s["stop_distance_pct"])
            if s["stop_distance_pct"] < p.get("min_stop_pct", 2.0):
                s["ok"] = False; s["reasons"].append("stop only %.1f%% below trigger, inside the noise" % s["stop_distance_pct"])
        elif s["ok"]:
            s["ok"] = False; s["reasons"].append("no valid stop")
    return out


def reversion(sym, cl, params):
    """Rule R, the Reversion book: RSI(2) below rev_rsi_max with the close above the 200-day SMA.
    Entry at the next open (the scan runs on bars through yesterday); exit at the open after a close
    above the prior day's high; GTC stop rev_stop_atr x ATR(14) below the fill. Ranked by NATR, highest first."""
    p = dict(DEFAULT_PARAMS); p.update(params or {})
    reasons = []
    if not p.get("rev_enabled", True): reasons.append("reversion book disabled")
    elif cl["sma200"] is None or cl["rsi2"] is None or cl["atr14"] is None: reasons.append("not enough history")
    else:
        if not cl["close"] > cl["sma200"]: reasons.append("close below sma200")
        if not cl["rsi2"] < p["rev_rsi_max"]: reasons.append("rsi2 %.1f >= %s" % (cl["rsi2"], p["rev_rsi_max"]))
        if sym in INDEX_ETFS: reasons.append("index ETF belongs to Setup B")
    natr = r2(cl["atr14"] / cl["close"] * 100) if cl.get("atr14") and cl.get("close") else None
    return {"ok": not reasons, "reasons": reasons, "rsi2": cl["rsi2"], "natr_pct": natr,
            "stop_distance": r2(p["rev_stop_atr"] * cl["atr14"]) if cl.get("atr14") else None,
            "exit_signal": bool(cl.get("close_above_prev_high")),
            "prev_close": cl["close"], "limit_for_open": r2(cl["close"] * 1.02)}


# --------------------------------------------------------------------- main
def credit_spread(sym, cl, wr, params):
    """Setup P (example): an oscillator zone -> a defined-risk vertical spread. Your STRATEGY section replaces this."""
    p = dict(DEFAULT_PARAMS); p.update(params or {})
    reasons = []
    if wr["fast"] is None or wr["slow"] is None: reasons.append("not enough history for %R")
    else:
        lvl = p["wr_strict_os"]
        if not wr["fast"] < lvl: reasons.append("fast %%R %.1f not below %s" % (wr["fast"], lvl))
        if not wr["slow"] < lvl: reasons.append("slow %%R %.1f not below %s" % (wr["slow"], lvl))
    if cl["close"] is not None and cl["close"] < 10: reasons.append("price under $10")
    return {"ok": not reasons, "reasons": reasons, "wr_fast": wr["fast"], "wr_slow": wr["slow"], "close": cl["close"],
            "natr_pct": r2(cl["atr14"] / cl["close"] * 100) if cl.get("atr14") and cl["close"] else None,
            "delta_lo": p["spread_delta_lo"], "delta_hi": p["spread_delta_hi"], "delta_target": p["spread_delta_target"],
            "dte_min": p["spread_dte_min"], "dte_max": p["spread_dte_max"], "tp": p["spread_tp"], "sl": p["spread_sl"],
            "min_credit_pct": p["spread_min_credit_pct"]}

def load_bars(obj):
    out = {}
    if isinstance(obj, dict) and "data" in obj and "results" in obj["data"]:
        for r in obj["data"]["results"]:
            rows = []
            for b in r.get("bars", []):
                if b.get("interpolated"): continue
                rows.append({"date": b["begins_at"][:10], "open": float(b["open_price"]), "high": float(b["high_price"]),
                             "low": float(b["low_price"]), "close": float(b["close_price"]), "volume": float(b.get("volume") or 0)})
            out[r["symbol"]] = rows
    else:
        for sym, rows in obj.items():
            out[sym] = [{"date": str(x.get("date", x.get("begins_at", "")))[:10], "open": float(x["open"]), "high": float(x["high"]),
                         "low": float(x["low"]), "close": float(x["close"]), "volume": float(x.get("volume") or 0)} for x in rows]
    return out

def analyze(sym, rows, params=None, regime_ok=True):
    global TAP_BARS
    TAP_BARS = int((params or {}).get("c_tap_bars", 3))
    if len(rows) < 30: return {"symbol": sym, "error": "fewer than 30 bars"}
    o = [r["open"] for r in rows]; h = [r["high"] for r in rows]; l = [r["low"] for r in rows]
    c = [r["close"] for r in rows]; v = [r["volume"] for r in rows]; d = [r["date"] for r in rows]
    cl = classic(o, h, l, c, v, d); sm = smc(o, h, l, c, d); wr = wr_exhaustion(h, l, c)
    return {"symbol": sym, "classic": cl, "smc": sm, "wr_exhaustion": wr, "setups": setups(sym, cl, sm, wr, params, regime_ok),
            "reversion": reversion(sym, cl, params), "spread": credit_spread(sym, cl, wr, params)}

def regime(report_spy):
    cl = report_spy["classic"]
    ok = cl["sma50"] is not None and cl["close"] > cl["sma50"] and (cl["change_pct"] is None or cl["change_pct"] > -2.0)
    return {"ok": bool(ok), "spy_close": cl["close"], "spy_sma50": cl["sma50"], "spy_change_pct": cl["change_pct"]}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    bars = load_bars(json.load(open(sys.argv[1], encoding="utf-8")))
    params = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else {}
    reg = None
    if "SPY" in bars:
        reg = regime(analyze("SPY", bars["SPY"], params))
    regime_ok = reg["ok"] if reg else True
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "regime": reg, "params": {**DEFAULT_PARAMS, **params},
              "symbols": {sym: analyze(sym, rows, params, regime_ok) for sym, rows in bars.items()}}
    print(json.dumps(report, indent=1))
