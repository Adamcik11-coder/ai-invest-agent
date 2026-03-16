from pathlib import Path
from collections import defaultdict

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="AI Invest Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://ai-invest-dashboard-delta.vercel.app", "https://ai-invest-dashboard-p58tguk4b-adamcik11-coders-projects.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
BUY_SIGNALS_FILE = BASE_DIR / "buy_signals.csv"
COMPOSITE_FILE = BASE_DIR / "composite_report.csv"


class PortfolioPosition(BaseModel):
    ticker: str = Field(..., example="NVDA")
    shares: float = Field(..., example=10)
    buy_price: float = Field(..., example=770)


class PortfolioRequest(BaseModel):
    portfolio: list[PortfolioPosition]


class WatchlistRequest(BaseModel):
    tickers: list[str]


@app.get("/")
def root():
    return {"message": "AI Invest Agent běží"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/daily-scan")
def daily_scan():
    if not BUY_SIGNALS_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor buy_signals.csv nebyl nalezen."
        )

    df = pd.read_csv(BUY_SIGNALS_FILE)

    if df.empty:
        return {
            "count": 0,
            "top": []
        }

    records = df.fillna("").to_dict(orient="records")

    return {
        "count": len(records),
        "top": records[:20]
    }


@app.get("/stock/{ticker}")
def stock_detail(ticker: str):
    if not COMPOSITE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor composite_report.csv nebyl nalezen."
        )

    df = pd.read_csv(COMPOSITE_FILE)

    if "ticker" not in df.columns:
        raise HTTPException(
            status_code=500,
            detail="V composite_report.csv chybí sloupec 'ticker'."
        )

    row = df[df["ticker"].astype(str).str.upper() == ticker.upper()]

    if row.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker {ticker} nebyl nalezen."
        )

    return row.iloc[0].fillna("").to_dict()


def calculate_dcf_from_row(stock, ticker: str):
    try:
        price = float(stock.get("price", 0))
    except (TypeError, ValueError):
        price = 0.0

    try:
        revenue_growth = float(stock.get("revenue_growth", 0))
    except (TypeError, ValueError):
        revenue_growth = 0.0

    try:
        fcf_margin = float(stock.get("fcf_margin", 0))
    except (TypeError, ValueError):
        fcf_margin = 0.0

    try:
        quality_score = float(stock.get("quality_score", 0))
    except (TypeError, ValueError):
        quality_score = 0.0

    try:
        overheat_score = float(stock.get("overheat_score", 0))
    except (TypeError, ValueError):
        overheat_score = 0.0

    if price <= 0:
        return None

    growth_rate = max(min(revenue_growth, 0.25), 0.02)

    base_fcf_yield = 0.04

    if quality_score >= 10:
        base_fcf_yield = 0.055
    elif quality_score >= 7:
        base_fcf_yield = 0.05
    elif quality_score >= 4:
        base_fcf_yield = 0.045

    if fcf_margin > 0.20:
        base_fcf_yield += 0.01
    elif fcf_margin > 0.10:
        base_fcf_yield += 0.005

    if overheat_score >= 3:
        base_fcf_yield -= 0.005

    current_fcf_per_share = price * base_fcf_yield
    discount_rate = 0.10
    terminal_growth = 0.03

    fcf = current_fcf_per_share
    projected_fcfs = []
    discounted_fcfs = []

    for year in range(1, 6):
        fcf = fcf * (1 + growth_rate)
        projected_fcfs.append(fcf)
        discounted = fcf / ((1 + discount_rate) ** year)
        discounted_fcfs.append(discounted)

    terminal_fcf = fcf * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    discounted_terminal_value = terminal_value / ((1 + discount_rate) ** 5)

    intrinsic_value = sum(discounted_fcfs) + discounted_terminal_value
    upside_percent = ((intrinsic_value - price) / price * 100) if price > 0 else 0.0

    return {
        "ticker": ticker,
        "current_price": round(price, 2),
        "estimated_fair_value": round(intrinsic_value, 2),
        "upside_percent": round(upside_percent, 2),
        "growth_rate": round(growth_rate * 100, 2),
        "discount_rate": round(discount_rate * 100, 2),
        "terminal_growth": round(terminal_growth * 100, 2),
        "current_fcf_per_share_estimate": round(current_fcf_per_share, 2),
        "projected_fcf_per_share": [round(x, 2) for x in projected_fcfs],
    }


@app.get("/stock/{ticker}/dcf")
def stock_dcf(ticker: str):
    if not COMPOSITE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor composite_report.csv nebyl nalezen."
        )

    df = pd.read_csv(COMPOSITE_FILE).fillna("")

    if "ticker" not in df.columns:
        raise HTTPException(
            status_code=500,
            detail="V composite_report.csv chybí sloupec 'ticker'."
        )

    row = df[df["ticker"].astype(str).str.upper() == ticker.upper()]

    if row.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker {ticker} nebyl nalezen."
        )

    stock = row.iloc[0]
    dcf_result = calculate_dcf_from_row(stock, ticker.upper())

    if dcf_result is None:
        raise HTTPException(
            status_code=400,
            detail=f"Ticker {ticker} nemá dostupnou cenu pro DCF výpočet."
        )

    upside_percent = dcf_result["upside_percent"]

    if upside_percent >= 25:
        rating = "Strong Buy"
    elif upside_percent >= 10:
        rating = "Buy"
    elif upside_percent >= -10:
        rating = "Hold"
    else:
        rating = "Risk / Overvalued"

    ai_comment = generate_dcf_comment(
        ticker=ticker.upper(),
        upside_percent=upside_percent,
        growth_rate=dcf_result["growth_rate"] / 100,
        discount_rate=dcf_result["discount_rate"] / 100,
        terminal_growth=dcf_result["terminal_growth"] / 100,
    )

    return {
        "ticker": dcf_result["ticker"],
        "current_price": dcf_result["current_price"],
        "estimated_fair_value": dcf_result["estimated_fair_value"],
        "upside_percent": dcf_result["upside_percent"],
        "rating": rating,
        "assumptions": {
            "growth_rate": dcf_result["growth_rate"],
            "discount_rate": dcf_result["discount_rate"],
            "terminal_growth": dcf_result["terminal_growth"],
            "current_fcf_per_share_estimate": dcf_result["current_fcf_per_share_estimate"],
        },
        "projected_fcf_per_share": dcf_result["projected_fcf_per_share"],
        "ai_comment": ai_comment,
    }


@app.post("/portfolio/analyze")
def analyze_portfolio(request: PortfolioRequest):
    if not COMPOSITE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor composite_report.csv nebyl nalezen."
        )

    df = pd.read_csv(COMPOSITE_FILE).fillna("")

    if "ticker" not in df.columns:
        raise HTTPException(
            status_code=500,
            detail="V composite_report.csv chybí sloupec 'ticker'."
        )

    positions_output = []
    total_value = 0.0
    total_cost = 0.0
    weighted_score_sum = 0.0
    sector_values = defaultdict(float)
    missing_tickers = []

    for position in request.portfolio:
        ticker = position.ticker.upper()
        row = df[df["ticker"].astype(str).str.upper() == ticker]

        if row.empty:
            missing_tickers.append(ticker)
            continue

        stock = row.iloc[0]

        current_price = stock.get("price", 0)
        sector = stock.get("sector", "Unknown")
        signal = stock.get("signal", "")
        composite_score = stock.get("composite_score", 0)

        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            current_price = 0.0

        try:
            composite_score = float(composite_score)
        except (TypeError, ValueError):
            composite_score = 0.0

        shares = float(position.shares)
        buy_price = float(position.buy_price)

        current_value = shares * current_price
        cost_value = shares * buy_price
        profit_loss = current_value - cost_value
        profit_loss_pct = (profit_loss / cost_value * 100) if cost_value > 0 else 0.0

        total_value += current_value
        total_cost += cost_value
        weighted_score_sum += composite_score * current_value
        sector_values[sector] += current_value

        positions_output.append({
            "ticker": ticker,
            "shares": shares,
            "buy_price": round(buy_price, 2),
            "current_price": round(current_price, 2),
            "current_value": round(current_value, 2),
            "cost_value": round(cost_value, 2),
            "profit_loss": round(profit_loss, 2),
            "profit_loss_pct": round(profit_loss_pct, 2),
            "sector": sector,
            "signal": signal,
            "composite_score": round(composite_score, 2),
        })

    total_profit = total_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0
    portfolio_score = (weighted_score_sum / total_value) if total_value > 0 else 0.0

    diversification = []
    for sector, value in sector_values.items():
        weight_pct = (value / total_value * 100) if total_value > 0 else 0.0
        diversification.append({
            "sector": sector,
            "value": round(value, 2),
            "weight_pct": round(weight_pct, 2)
        })

    diversification = sorted(diversification, key=lambda x: x["value"], reverse=True)

    ai_comment = generate_portfolio_comment(
        portfolio_score=portfolio_score,
        diversification=diversification
    )

    return {
        "portfolio_summary": {
            "positions_count": len(positions_output),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": round(total_profit, 2),
            "total_profit_pct": round(total_profit_pct, 2),
            "portfolio_score": round(portfolio_score, 2),
        },
        "positions": positions_output,
        "sector_diversification": diversification,
        "missing_tickers": missing_tickers,
        "ai_comment": ai_comment
    }


@app.post("/watchlist/analyze")
def analyze_watchlist(request: WatchlistRequest):
    if not COMPOSITE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor composite_report.csv nebyl nalezen."
        )

    df = pd.read_csv(COMPOSITE_FILE).fillna("")

    if "ticker" not in df.columns:
        raise HTTPException(
            status_code=500,
            detail="V composite_report.csv chybí sloupec 'ticker'."
        )

    items = []
    missing_tickers = []

    for ticker in request.tickers:
        symbol = str(ticker).upper()
        row = df[df["ticker"].astype(str).str.upper() == symbol]

        if row.empty:
            missing_tickers.append(symbol)
            continue

        stock = row.iloc[0]

        items.append({
            "ticker": stock.get("ticker", ""),
            "company": stock.get("company", ""),
            "sector": stock.get("sector", ""),
            "price": stock.get("price", ""),
            "signal": stock.get("signal", ""),
            "composite_score": stock.get("composite_score", ""),
            "quality_score": stock.get("quality_score", ""),
            "overheat_score": stock.get("overheat_score", ""),
            "revenue_growth": stock.get("revenue_growth", ""),
            "roic": stock.get("roic", ""),
            "gross_margin": stock.get("gross_margin", ""),
            "fcf_margin": stock.get("fcf_margin", ""),
        })

    return {
        "count": len(items),
        "items": items,
        "missing_tickers": missing_tickers
    }


@app.get("/alerts")
def get_alerts():
    if not COMPOSITE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor composite_report.csv nebyl nalezen."
        )

    df = pd.read_csv(COMPOSITE_FILE).fillna("")
    alerts = []

    for _, stock in df.iterrows():
        ticker = str(stock.get("ticker", "")).upper()
        company = stock.get("company", "")

        try:
            composite_score = float(stock.get("composite_score", 0))
        except (TypeError, ValueError):
            composite_score = 0.0

        try:
            quality_score = float(stock.get("quality_score", 0))
        except (TypeError, ValueError):
            quality_score = 0.0

        try:
            overheat_score = float(stock.get("overheat_score", 0))
        except (TypeError, ValueError):
            overheat_score = 0.0

        signal = str(stock.get("signal", "")).upper()

        if signal == "BUY" and composite_score >= 20 and overheat_score <= 2:
            alerts.append({
                "ticker": ticker,
                "company": company,
                "type": "BUY_ZONE",
                "message": f"{ticker} entered BUY zone with strong composite score."
            })

        if overheat_score >= 4:
            alerts.append({
                "ticker": ticker,
                "company": company,
                "type": "OVERHEATED",
                "message": f"{ticker} shows overheating signals and may be too extended."
            })

        if quality_score >= 10:
            alerts.append({
                "ticker": ticker,
                "company": company,
                "type": "HIGH_QUALITY",
                "message": f"{ticker} stands out as a very high-quality business."
            })

        if composite_score >= 24:
            alerts.append({
                "ticker": ticker,
                "company": company,
                "type": "STRONG_COMPOSITE",
                "message": f"{ticker} has an exceptionally strong composite score."
            })

    return {
        "count": len(alerts),
        "alerts": alerts[:50]
    }


@app.post("/watchlist/alerts")
def watchlist_alerts(request: WatchlistRequest):
    if not COMPOSITE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Soubor composite_report.csv nebyl nalezen."
        )

    df = pd.read_csv(COMPOSITE_FILE).fillna("")

    if "ticker" not in df.columns:
        raise HTTPException(
            status_code=500,
            detail="V composite_report.csv chybí sloupec 'ticker'."
        )

    alerts = []
    missing_tickers = []

    for ticker in request.tickers:
        symbol = str(ticker).upper()
        row = df[df["ticker"].astype(str).str.upper() == symbol]

        if row.empty:
            missing_tickers.append(symbol)
            continue

        stock = row.iloc[0]
        company = stock.get("company", "")

        try:
            composite_score = float(stock.get("composite_score", 0))
        except (TypeError, ValueError):
            composite_score = 0.0

        try:
            quality_score = float(stock.get("quality_score", 0))
        except (TypeError, ValueError):
            quality_score = 0.0

        try:
            overheat_score = float(stock.get("overheat_score", 0))
        except (TypeError, ValueError):
            overheat_score = 0.0

        signal = str(stock.get("signal", "")).upper()

        if signal == "BUY" and composite_score >= 20 and overheat_score <= 2:
            alerts.append({
                "ticker": symbol,
                "company": company,
                "type": "BUY_ZONE",
                "message": f"{symbol} entered BUY zone with strong composite score."
            })

        if overheat_score >= 4:
            alerts.append({
                "ticker": symbol,
                "company": company,
                "type": "OVERHEATED",
                "message": f"{symbol} shows overheating signals and may be too extended."
            })

        if quality_score >= 10:
            alerts.append({
                "ticker": symbol,
                "company": company,
                "type": "HIGH_QUALITY",
                "message": f"{symbol} stands out as a very high-quality business."
            })

        if composite_score >= 24:
            alerts.append({
                "ticker": symbol,
                "company": company,
                "type": "STRONG_COMPOSITE",
                "message": f"{symbol} has an exceptionally strong composite score."
            })

        dcf_result = calculate_dcf_from_row(stock, symbol)

        if dcf_result is not None:
            upside_percent = dcf_result["upside_percent"]
            fair_value = dcf_result["estimated_fair_value"]
            current_price = dcf_result["current_price"]

            if upside_percent >= 20:
                alerts.append({
                    "ticker": symbol,
                    "company": company,
                    "type": "DCF_UPSIDE",
                    "message": f"{symbol} trades meaningfully below estimated fair value ({round(current_price, 2)} vs {round(fair_value, 2)})."
                })

            if upside_percent <= -15:
                alerts.append({
                    "ticker": symbol,
                    "company": company,
                    "type": "DCF_OVERVALUED",
                    "message": f"{symbol} appears above estimated fair value ({round(current_price, 2)} vs {round(fair_value, 2)})."
                })

    return {
        "count": len(alerts),
        "alerts": alerts,
        "missing_tickers": missing_tickers
    }


def generate_portfolio_comment(portfolio_score: float, diversification: list[dict]) -> str:
    if not diversification:
        return "Portfolio zatím neobsahuje analyzovatelné pozice."

    top_sector = diversification[0]
    top_weight = top_sector["weight_pct"]

    if portfolio_score >= 22:
        base_comment = "Portfolio má velmi silné fundamentální skóre."
    elif portfolio_score >= 18:
        base_comment = "Portfolio působí kvalitně a má solidní investiční profil."
    elif portfolio_score >= 14:
        base_comment = "Portfolio je průměrné a zaslouží detailnější kontrolu jednotlivých pozic."
    else:
        base_comment = "Portfolio je spíše slabší a obsahuje rizikovější nebo méně kvalitní pozice."

    if top_weight >= 60:
        concentration_comment = (
            f" Portfolio je silně koncentrované v sektoru {top_sector['sector']} "
            f"({round(top_weight, 1)} %)."
        )
    elif top_weight >= 40:
        concentration_comment = (
            f" Portfolio má zvýšenou koncentraci v sektoru {top_sector['sector']} "
            f"({round(top_weight, 1)} %)."
        )
    else:
        concentration_comment = " Sektorová diverzifikace je zatím relativně vyvážená."

    return base_comment + concentration_comment


def generate_dcf_comment(
    ticker: str,
    upside_percent: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
) -> str:
    if upside_percent >= 25:
        valuation_text = "vypadá výrazně podhodnoceně"
    elif upside_percent >= 10:
        valuation_text = "vypadá mírně podhodnoceně"
    elif upside_percent >= -10:
        valuation_text = "se obchoduje poblíž férové hodnoty"
    else:
        valuation_text = "vypadá nadhodnoceně"

    return (
        f"DCF model naznačuje, že {ticker} {valuation_text}. "
        f"Model pracuje s růstem {round(growth_rate * 100, 1)} %, "
        f"diskontní sazbou {round(discount_rate * 100, 1)} % "
        f"a terminálním růstem {round(terminal_growth * 100, 1)} %."
    )
