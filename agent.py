import requests
import time
import pandas as pd

API_KEY = "wLm6UVSmx8bDLocG9Sz2koOEzDLYwGQh"

session = requests.Session()


def fetch_json(url):
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, list):
            return data[0] if data else None
        return data
    except Exception:
        return None


# načtení tickerů
stocks = pd.read_csv("stocks.csv")["ticker"].dropna().tolist()
stocks = sorted(set(stocks))

results = []

for ticker in stocks:

    print(f"\nNačítám {ticker}...")
    time.sleep(0.4)

    profile = fetch_json(
        f"https://financialmodelingprep.com/stable/profile?symbol={ticker}&apikey={API_KEY}"
    )

    metrics = fetch_json(
        f"https://financialmodelingprep.com/stable/key-metrics-ttm?symbol={ticker}&apikey={API_KEY}"
    )

    growth = fetch_json(
        f"https://financialmodelingprep.com/stable/financial-growth?symbol={ticker}&apikey={API_KEY}"
    )

    price_change = fetch_json(
        f"https://financialmodelingprep.com/stable/stock-price-change?symbol={ticker}&apikey={API_KEY}"
    )

    quote = fetch_json(
        f"https://financialmodelingprep.com/stable/quote?symbol={ticker}&apikey={API_KEY}"
    )

    ratios = fetch_json(
        f"https://financialmodelingprep.com/stable/ratios-ttm?symbol={ticker}&apikey={API_KEY}"
    )

    if not profile or not metrics:
        print("chybí data")
        continue

    company = profile.get("companyName")
    sector = profile.get("sector")

    price = None
    if quote:
        price = quote.get("price")

    ev_sales = metrics.get("evToSalesTTM")
    ev_fcf = metrics.get("evToFreeCashFlowTTM")
    debt = metrics.get("netDebtToEBITDATTM")
    current_ratio = metrics.get("currentRatioTTM")

    roic = metrics.get("returnOnInvestedCapitalTTM")

    gross_margin = None
    if ratios:
        gross_margin = ratios.get("grossProfitMarginTTM")

    fcf_margin = None
    if ev_sales and ev_fcf:
        try:
            if ev_fcf != 0:
                fcf_margin = ev_sales / ev_fcf
        except:
            pass

    revenue_growth = None
    eps_growth = None

    if growth:
        revenue_growth = growth.get("revenueGrowth")
        eps_growth = growth.get("epsgrowth")

    change6m = None
    change1y = None

    if price_change:
        change6m = price_change.get("6M")
        change1y = price_change.get("1Y")

    # BUY SCORE
    buy_score = 0

    if ev_sales:
        if ev_sales < 6:
            buy_score += 3
        elif ev_sales < 10:
            buy_score += 2
        elif ev_sales < 15:
            buy_score += 1

    if ev_fcf:
        if ev_fcf < 15:
            buy_score += 4
        elif ev_fcf < 25:
            buy_score += 3
        elif ev_fcf < 40:
            buy_score += 1

    if revenue_growth:
        if revenue_growth > 0.20:
            buy_score += 6
        elif revenue_growth > 0.10:
            buy_score += 4

    if eps_growth:
        if eps_growth > 0.20:
            buy_score += 4
        elif eps_growth > 0.10:
            buy_score += 2

    # QUALITY SCORE
    quality_score = 0

    if roic:
        if roic > 0.20:
            quality_score += 4
        elif roic > 0.12:
            quality_score += 3
        elif roic > 0.08:
            quality_score += 2

    if gross_margin:
        if gross_margin > 0.70:
            quality_score += 4
        elif gross_margin > 0.55:
            quality_score += 3
        elif gross_margin > 0.40:
            quality_score += 2

    if fcf_margin:
        if fcf_margin > 0.25:
            quality_score += 4
        elif fcf_margin > 0.18:
            quality_score += 3
        elif fcf_margin > 0.10:
            quality_score += 2

    composite_score = round(buy_score + quality_score, 2)

    # OVERHEAT
    overheat_score = 0

    if change6m and change6m > 40:
        overheat_score += 2

    if change1y and change1y > 70:
        overheat_score += 2

    if ev_sales and ev_sales > 20:
        overheat_score += 2

    if ev_fcf and ev_fcf > 100:
        overheat_score += 2

    signal = "WATCH"

    if composite_score >= 18 and overheat_score <= 1:
        signal = "BUY"
    elif overheat_score >= 4:
        signal = "AVOID"

    results.append({
        "ticker": ticker,
        "company": company,
        "sector": sector,
        "price": price,
        "signal": signal,
        "buy_score": buy_score,
        "quality_score": quality_score,
        "composite_score": composite_score,
        "overheat_score": overheat_score,
        "ev_to_sales": ev_sales,
        "ev_to_fcf": ev_fcf,
        "net_debt_to_ebitda": debt,
        "current_ratio": current_ratio,
        "revenue_growth": revenue_growth,
        "eps_growth": eps_growth,
        "roic": roic,
        "gross_margin": gross_margin,
        "fcf_margin": fcf_margin,
        "change_6m": change6m,
        "change_1y": change1y,
    })


df = pd.DataFrame(results)

quality_df = df.sort_values(by="quality_score", ascending=False)
composite_df = df.sort_values(by="composite_score", ascending=False)

buy_signals = df[df["signal"] == "BUY"]

quality_df.to_csv("quality_report.csv", index=False)
composite_df.to_csv("composite_report.csv", index=False)
buy_signals.to_csv("buy_signals.csv", index=False)

print("\nReport uložen.")