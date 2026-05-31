"""
LLM Investment Simulator
Usage: python simulate.py --set a|b --session 1|2|3
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
import pytz

import feedparser
import yfinance as yf
import google.generativeai as genai

from pathlib import Path
from typing import Any

# ── 定数 ──────────────────────────────────────────────────────────────────────
JST = pytz.timezone("Asia/Tokyo")
REPO_ROOT = Path(__file__).parent.parent
FEE_RATE = float(os.environ.get("FEE_RATE", "0.001"))   # 手数料率（デフォルト0.1%）
GEMINI_MODEL = "gemini-2.0-flash"

# ── パス解決 ──────────────────────────────────────────────────────────────────
def set_dir(set_id: str) -> Path:
    return REPO_ROOT / "data" / f"set_{set_id}"

def asset_path(set_id: str) -> Path:
    return set_dir(set_id) / "assets.json"

def plan_path(set_id: str) -> Path:
    return set_dir(set_id) / "plan.md"

def watchlist_path(set_id: str) -> Path:
    return set_dir(set_id) / "watchlist.json"

def history_dir(set_id: str) -> Path:
    return set_dir(set_id) / "history"

def call_log_path(set_id: str) -> Path:
    today = datetime.now(JST).strftime("%Y-%m")
    return history_dir(set_id) / f"calls_{today}.jsonl"

def trade_log_path(set_id: str) -> Path:
    today = datetime.now(JST).strftime("%Y-%m")
    return history_dir(set_id) / f"trades_{today}.jsonl"

def method_path() -> Path:
    return REPO_ROOT / "investment_method" / "methods.md"

# ── ユーティリティ ─────────────────────────────────────────────────────────────
def now_str() -> str:
    return datetime.now(JST).isoformat()

def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

# ── ニュース取得 ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline",
    "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
]

def fetch_news(keywords: list[str], max_items: int = 30) -> list[dict]:
    """RSS + keywordsでニュースを取得"""
    articles = []
    # キーワードからGoogle News RSS
    for kw in keywords[:5]:
        url = f"https://news.google.com/rss/search?q={kw.replace(' ','+')}&hl=ja&gl=JP&ceid=JP:ja"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:6]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": kw,
                })
        except Exception as e:
            print(f"[WARN] news fetch failed for '{kw}': {e}")

    # デフォルトRSS
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": feed_url,
                })
        except Exception as e:
            print(f"[WARN] RSS fetch failed: {e}")

    return articles[:max_items]

# ── 株価取得 ───────────────────────────────────────────────────────────────────
def fetch_prices(tickers: list[str]) -> dict:
    """yfinance で最新終値・前日比・52週高低を取得"""
    result = {}
    for ticker in tickers[:20]:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            hist = t.history(period="5d")
            if hist.empty:
                continue
            close = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            result[ticker] = {
                "price": round(close, 4),
                "change_pct": round((close - prev) / prev * 100, 2) if prev else 0,
                "52w_high": round(float(info.year_high), 4) if hasattr(info, "year_high") else None,
                "52w_low": round(float(info.year_low), 4) if hasattr(info, "year_low") else None,
                "currency": getattr(info, "currency", "USD"),
            }
        except Exception as e:
            print(f"[WARN] price fetch failed for '{ticker}': {e}")
            result[ticker] = {"error": str(e)}
    return result

# ── 資産評価額計算 ─────────────────────────────────────────────────────────────
def calc_portfolio_value(assets: dict, prices: dict) -> dict:
    """資産の現在評価額を計算"""
    cash = assets.get("cash", {})
    holdings = assets.get("holdings", {})

    total_usd = cash.get("USD", 0)
    total_jpy = cash.get("JPY", 0)

    breakdown = []
    for ticker, qty in holdings.items():
        info = prices.get(ticker, {})
        price = info.get("price")
        currency = info.get("currency", "USD")
        if price and qty:
            value = price * qty
            breakdown.append({
                "ticker": ticker,
                "qty": qty,
                "price": price,
                "value": value,
                "currency": currency,
            })
            if currency == "JPY":
                total_jpy += value
            else:
                total_usd += value

    return {
        "total_usd": round(total_usd, 2),
        "total_jpy": round(total_jpy, 2),
        "breakdown": breakdown,
        "cash": cash,
    }

# ── Gemini 呼び出し ────────────────────────────────────────────────────────────
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "trades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action":  {"type": "string", "enum": ["buy", "sell", "hold"]},
                    "ticker":  {"type": "string"},
                    "quantity":{"type": "number"},
                    "reason":  {"type": "string"},
                },
                "required": ["action", "ticker", "quantity", "reason"],
            },
        },
        "updated_plan": {"type": "string"},
        "updated_watchlist": {
            "type": "object",
            "properties": {
                "news_keywords": {"type": "array", "items": {"type": "string"}},
                "tickers":       {"type": "array", "items": {"type": "string"}},
            },
            "required": ["news_keywords", "tickers"],
        },
        "summary_for_report": {"type": "string"},
    },
    "required": ["reasoning", "trades", "updated_plan", "updated_watchlist", "summary_for_report"],
}

def call_gemini(system_prompt: str, user_prompt: str, api_key: str) -> dict:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system_prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0.4,
        ),
    )
    response = model.generate_content(user_prompt)
    return json.loads(response.text)

# ── トレード実行 ───────────────────────────────────────────────────────────────
def execute_trades(assets: dict, trades: list[dict], prices: dict, fee_rate: float) -> tuple[dict, list[dict]]:
    """
    トレード指示を資産に反映する。
    assets を直接変更せず新しい dict を返す。
    """
    import copy
    assets = copy.deepcopy(assets)
    records = []

    holdings = assets.setdefault("holdings", {})
    cash = assets.setdefault("cash", {"USD": 0, "JPY": 0})

    for trade in trades:
        action  = trade.get("action")
        ticker  = trade.get("ticker", "").upper()
        qty     = float(trade.get("quantity", 0))
        price_info = prices.get(ticker, {})
        price   = price_info.get("price")
        currency= price_info.get("currency", "USD")

        if action == "hold" or qty <= 0 or not price:
            continue

        fee = price * qty * fee_rate
        total_cost = price * qty + fee  # buy
        total_gain = price * qty - fee  # sell

        record = {
            "timestamp": now_str(),
            "action": action,
            "ticker": ticker,
            "qty": qty,
            "price": price,
            "fee": round(fee, 4),
            "currency": currency,
            "reason": trade.get("reason", ""),
            "status": "ok",
        }

        if action == "buy":
            if cash.get(currency, 0) >= total_cost:
                cash[currency] = round(cash.get(currency, 0) - total_cost, 4)
                holdings[ticker] = round(holdings.get(ticker, 0) + qty, 8)
            else:
                record["status"] = "rejected_insufficient_cash"
                record["available"] = cash.get(currency, 0)
                record["required"]  = total_cost

        elif action == "sell":
            owned = holdings.get(ticker, 0)
            actual_qty = min(qty, owned)
            if actual_qty > 0:
                actual_gain = price * actual_qty - price * actual_qty * fee_rate
                cash[currency] = round(cash.get(currency, 0) + actual_gain, 4)
                new_qty = round(owned - actual_qty, 8)
                if new_qty <= 0:
                    holdings.pop(ticker, None)
                else:
                    holdings[ticker] = new_qty
                record["qty"] = actual_qty
                record["actual_gain"] = round(actual_gain, 4)
            else:
                record["status"] = "rejected_no_holdings"

        records.append(record)

    return assets, records

# ── メイン処理 ─────────────────────────────────────────────────────────────────
def run(set_id: str, session: int) -> None:
    print(f"[INFO] === Set {set_id.upper()} / Session {session} start: {now_str()} ===")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    # ── データ読み込み ──
    assets    = load_json(asset_path(set_id))
    watchlist = load_json(watchlist_path(set_id))
    plan      = load_text(plan_path(set_id))
    method    = load_text(method_path())

    keywords = watchlist.get("news_keywords", [])
    tickers  = watchlist.get("tickers", [])

    # ── 外部データ取得 ──
    print(f"[INFO] Fetching news ({len(keywords)} keywords)...")
    news = fetch_news(keywords)

    print(f"[INFO] Fetching prices ({len(tickers)} tickers)...")
    prices = fetch_prices(tickers)

    # ── ポートフォリオ評価 ──
    portfolio_value = calc_portfolio_value(assets, prices)

    # ── system prompt 読み込み ──
    system_prompt_path = set_dir(set_id) / "system_prompt.md"
    system_prompt = load_text(system_prompt_path)
    if not system_prompt:
        system_prompt = f"あなたはセット{set_id.upper()}の投資シミュレーターエージェントです。"

    # ── user prompt 組み立て ──
    news_text = "\n".join(
        f"- [{a['published']}] {a['title']} ({a['source']})\n  {a['summary']}"
        for a in news
    )
    prices_text = json.dumps(prices, ensure_ascii=False, indent=2)
    portfolio_text = json.dumps(portfolio_value, ensure_ascii=False, indent=2)
    assets_text = json.dumps(assets, ensure_ascii=False, indent=2)

    user_prompt = f"""
## 現在日時
{now_str()}  (セッション {session}/3)

## 現在の資産
```json
{assets_text}
```

## ポートフォリオ評価額
```json
{portfolio_text}
```

## 現在の投資計画
{plan}

## 最新ニュース
{news_text}

## 最新株価・ETF価格
```json
{prices_text}
```

## 一般的に言われる投資メソッド（あくまでも参考にせよ）
```
{method}
```

---
上記の情報をもとに、以下をJSON形式で返してください。
- reasoning: 今回の判断の詳細な思考過程（日本語）
- trades: 実行するトレードのリスト（buyまたはsell、holdは不要）
- updated_plan: 更新後の投資計画（Markdown）
- updated_watchlist: 次回確認したいnews_keywordsとtickers
- summary_for_report: 人間向けレポート用の今回の判断サマリー（日本語200字程度）

手数料率: {FEE_RATE*100:.2f}%
"""

    # ── Gemini 呼び出し ──
    print("[INFO] Calling Gemini API...")
    t0 = time.time()
    try:
        llm_result = call_gemini(system_prompt, user_prompt, api_key)
        elapsed = round(time.time() - t0, 2)
        api_status = "ok"
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        api_status = f"error: {e}"
        print(f"[ERROR] Gemini call failed: {e}")
        traceback.print_exc()
        # エラーでも空の結果を入れてログ記録
        llm_result = {
            "reasoning": f"APIエラー: {e}",
            "trades": [],
            "updated_plan": plan,
            "updated_watchlist": watchlist,
            "summary_for_report": f"APIエラーのためスキップ: {e}",
        }

    # ── API呼び出し履歴ログ ──
    call_record = {
        "timestamp": now_str(),
        "set": set_id,
        "session": session,
        "status": api_status,
        "elapsed_sec": elapsed,
        "news_count": len(news),
        "tickers_fetched": list(prices.keys()),
        "portfolio_value": portfolio_value,
        "llm_summary": llm_result.get("summary_for_report", ""),
    }
    append_jsonl(call_log_path(set_id), call_record)

    # ── トレード実行 ──
    new_assets, trade_records = execute_trades(
        assets, llm_result.get("trades", []), prices, FEE_RATE
    )

    # ── トレード履歴ログ ──
    for tr in trade_records:
        tr["set"] = set_id
        tr["session"] = session
        append_jsonl(trade_log_path(set_id), tr)

    # ── 資産・計画・ウォッチリスト保存 ──
    save_json(asset_path(set_id), new_assets)

    new_plan = llm_result.get("updated_plan", plan)
    plan_path(set_id).write_text(new_plan, encoding="utf-8")

    new_watchlist = llm_result.get("updated_watchlist", watchlist)
    save_json(watchlist_path(set_id), new_watchlist)

    # ── セッション結果サマリー保存（レポート生成用） ──
    session_summary_path = set_dir(set_id) / "last_session.json"
    save_json(session_summary_path, {
        "timestamp": now_str(),
        "session": session,
        "reasoning": llm_result.get("reasoning", ""),
        "trades_executed": trade_records,
        "summary_for_report": llm_result.get("summary_for_report", ""),
        "portfolio_value": portfolio_value,
        "prices_snapshot": prices,
    })

    print(f"[INFO] Trades executed: {len(trade_records)}")
    print(f"[INFO] === Set {set_id.upper()} / Session {session} done: {now_str()} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", required=True, choices=["a", "b"])
    parser.add_argument("--session", required=True, type=int, choices=[1, 2, 3])
    args = parser.parse_args()
    run(args.set, args.session)
