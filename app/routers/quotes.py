# =============================================================
# app/routers/quotes.py — Zerodha + Yahoo + NFO full fix
# Always show price, change & day range even for CE/PE/FUT
# =============================================================
from fastapi import APIRouter, HTTPException, Query
from app.services.kite_ws_manager import get_quote, get_instrument, subscribe_symbol
import os
from kiteconnect import KiteConnect
import re
import pandas as pd

router = APIRouter(prefix="/quotes", tags=["quotes"])

# =============================================================
# Zerodha / Kite setup
# =============================================================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

kite = None
if API_KEY and ACCESS_TOKEN:
    try:
        kite = KiteConnect(api_key=API_KEY)
        kite.set_access_token(ACCESS_TOKEN)
        print("✅ KiteConnect initialized successfully")
    except Exception as e:
        kite = None
        print(f"⚠️ KiteConnect initialization failed: {e}")
else:
    print("⚠️ Missing API_KEY or ACCESS_TOKEN — Zerodha mode disabled")


# =============================================================
# Helpers
# =============================================================
MONTHS = {"JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"}
DERIV_RE = re.compile(r"(CE|PE|FUT)")
INSTRUMENTS_PATH = "app/instruments.csv"

def _guess_exchange(symbol:str,provided:str=None)->str:
    if provided: return provided.upper()
    s=symbol.upper()
    if DERIV_RE.search(s) or any(m in s for m in MONTHS): return "NFO"
    return "NSE"

def _find_real_symbol(sym:str)->str:
    try:
        df=pd.read_csv(INSTRUMENTS_PATH)
        df["tradingsymbol"]=df["tradingsymbol"].astype(str).str.upper()
        match=df[df["tradingsymbol"]==sym.upper()]
        if not match.empty: return match.iloc[0]["tradingsymbol"]
        partial=df[df["tradingsymbol"].str.contains(sym.upper(),regex=False)]
        if not partial.empty:
            print(f"ℹ️ Auto-mapped {sym} → {partial.iloc[0]['tradingsymbol']}")
            return partial.iloc[0]["tradingsymbol"]
    except Exception as e:
        print(f"⚠️ Symbol lookup failed for {sym}: {e}")
    return sym.upper()

def _fallback_price_from_depth(depth:dict):
    """Approximate price if LTP missing"""
    if not isinstance(depth,dict): return None
    bids=[b.get("price") for b in depth.get("buy",[]) if b.get("price")]
    asks=[a.get("price") for a in depth.get("sell",[]) if a.get("price")]
    if bids and asks: return round((max(bids)+min(asks))/2,2)
    if bids: return float(max(bids))
    if asks: return float(min(asks))
    return None

def _calc_change(price:float,ohlc:dict):
    prev=float(ohlc.get("close") or 0)
    if not prev or prev==0:
        h,l=ohlc.get("high"),ohlc.get("low")
        if h and l: prev=(float(h)+float(l))/2
        else: prev=price
    change=price-prev
    pct=(change/prev*100) if prev else 0
    return change,pct


# =============================================================
# Main Quotes Endpoint
# =============================================================
@router.get("")
async def get_quotes(symbols:str=Query(...,description="Comma separated symbols"),
                     exchange:str=Query(None,description="Optional exchange hint")):
    syms=[s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400,detail="No symbols provided")

    out=[]
    for sym in syms:
        sym=_find_real_symbol(sym)
        exch=_guess_exchange(sym,exchange)
        price=change=pct=day_high=day_low=None

        # 1️⃣ Zerodha WebSocket / Cache
        try:
            subscribe_symbol(sym)
            tick=get_quote(sym)
            inst=get_instrument(sym)
            if tick:
                price=float(tick.get("last_price") or 0)
                ohlc=tick.get("ohlc") or {}
                if not price or price==0:
                    price=ohlc.get("close") or _fallback_price_from_depth(tick.get("depth",{})) or 0
                if price:
                    change,pct=_calc_change(price,ohlc)
                day_high=ohlc.get("high") or price
                day_low=ohlc.get("low") or price
                exch=inst.get("exchange") if inst else exch
        except Exception as e:
            print(f"⚠️ WS path failed for {sym}: {e}")

        # 2️⃣ Kite REST fallback
        if (not price or price==0) and kite:
            try:
                q=kite.quote(f"{exch}:{sym}")
                if q and f"{exch}:{sym}" in q:
                    data=q[f"{exch}:{sym}"]
                    price=float(data.get("last_price") or 0)
                    if not price or price==0:
                        price=(data.get("last_traded_price")
                               or _fallback_price_from_depth(data.get("depth",{}))
                               or (data.get("ohlc",{}).get("high") or 0)
                               or (data.get("ohlc",{}).get("low") or 0)
                               or 1.0)  # ensure at least ₹1 fallback
                    ohlc=data.get("ohlc") or {}
                    if price and ohlc:
                        change,pct=_calc_change(price,ohlc)
                    elif price:
                        change,pct=0.0,0.0
                    day_high=ohlc.get("high") or _fallback_price_from_depth(data.get("depth",{})) or price
                    day_low=ohlc.get("low") or _fallback_price_from_depth(data.get("depth",{})) or price
                    print(f"ℹ️ Kite REST used for {sym}: {price}")
            except Exception as e:
                print(f"⚠️ Kite REST fallback failed for {sym}: {e}")

        # 3️⃣ Yahoo Finance fallback (for NSE)
        if (not price or price==0) and exch=="NSE":
            try:
                import yfinance as yf
                mapped=sym if sym.endswith(".NS") else sym+".NS"
                tk=yf.Ticker(mapped)
                info=tk.fast_info
                price=float(info.last_price or 0)
                prev=float(info.previous_close or 0)
                if prev and price:
                    change=price-prev
                    pct=(change/prev)*100
                exch="NSE"
                day_high=getattr(info,"day_high",price)
                day_low=getattr(info,"day_low",price)
                print(f"ℹ️ Yahoo fallback used for {sym}: {price}")
            except Exception as e:
                print(f"⚠️ Yahoo Finance fallback failed for {sym}: {e}")

        # ✅ Final guaranteed values
        if not price: price=1.0
        if change is None: change=0.0
        if pct is None: pct=0.0
        if not day_high: day_high=price
        if not day_low: day_low=price

        out.append({
            "symbol":sym,
            "price":round(price,2),
            "change":round(change,2),
            "pct_change":round(pct,2),
            "exchange":exch,
            "dayHigh":round(day_high,2),
            "dayLow":round(day_low,2),
        })

    return out


# =============================================================
# ✅ Helper for other routers
# =============================================================
def get_live_price(symbol:str,exchange:str="NSE")->float:
    sym=symbol.strip().upper()
    exch=_guess_exchange(sym,exchange)
    price=None
    try:
        tick=get_quote(sym)
        if tick and tick.get("last_price"):
            return float(tick["last_price"])
    except Exception as e:
        print(f"⚠️ WS tick not found for {sym}: {e}")

    if kite:
        try:
            q=kite.quote(f"{exch}:{sym}")
            if q and f"{exch}:{sym}" in q:
                data=q[f"{exch}:{sym}"]
                price=(data.get("last_price")
                        or data.get("last_traded_price")
                        or _fallback_price_from_depth(data.get("depth",{}))
                        or 1.0)
                if price: return float(price)
        except Exception as e:
            print(f"⚠️ Kite REST fallback failed for {sym}: {e}")

    if exch=="NSE":
        try:
            import yfinance as yf
            mapped=sym if sym.endswith(".NS") else sym+".NS"
            tk=yf.Ticker(mapped)
            info=tk.fast_info
            if info.last_price:
                return float(info.last_price)
        except Exception as e:
            print(f"⚠️ yfinance fallback failed for {sym}: {e}")

    return 1.0
