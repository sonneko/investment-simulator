"""
レポート生成スクリプト
- data/set_a, set_b の各種データを読み込む
- docs/index.html を生成（GitHub Pages）
"""

import json
import os
from pathlib import Path
from datetime import datetime
import pytz

JST = pytz.timezone("Asia/Tokyo")
REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"

def now_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

def load_json(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_jsonl(path, limit=200):
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records[-limit:]

def load_all_jsonl(directory: Path, prefix: str, limit=500):
    records = []
    for p in sorted(directory.glob(f"{prefix}_*.jsonl")):
        records.extend(load_jsonl(p))
    return records[-limit:]

def read_text(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

def escape_html(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def build_trade_rows(trades):
    if not trades:
        return "<tr><td colspan='7' style='text-align:center;color:#888'>トレード記録なし</td></tr>"
    rows = []
    for t in reversed(trades[-50:]):
        status = t.get("status", "ok")
        color = "#c8f7c5" if status == "ok" else "#ffd6d6"
        rows.append(f"""
        <tr style="background:{color}">
          <td>{escape_html(t.get('timestamp','')[:16])}</td>
          <td><b>{escape_html(t.get('action',''))}</b></td>
          <td>{escape_html(t.get('ticker',''))}</td>
          <td>{t.get('qty','')}</td>
          <td>{t.get('price','')}</td>
          <td>{t.get('fee','')}</td>
          <td>{escape_html(t.get('reason',''))[:60]}</td>
        </tr>""")
    return "\n".join(rows)

def build_portfolio_table(portfolio):
    if not portfolio:
        return "<p>データなし</p>"
    bd = portfolio.get("breakdown", [])
    cash = portfolio.get("cash", {})
    rows = []
    for item in bd:
        rows.append(f"""
        <tr>
          <td>{escape_html(item['ticker'])}</td>
          <td>{item['qty']}</td>
          <td>{item['price']}</td>
          <td><b>{item['value']:.2f}</b></td>
          <td>{item['currency']}</td>
        </tr>""")
    cash_rows = "".join(
        f"<tr><td colspan='3'><b>現金 ({k})</b></td><td><b>{v:.2f}</b></td><td>{k}</td></tr>"
        for k, v in cash.items()
    )
    return f"""
    <table class='data-table'>
      <thead><tr><th>銘柄</th><th>数量</th><th>現在価格</th><th>評価額</th><th>通貨</th></tr></thead>
      <tbody>{chr(10).join(rows)}{cash_rows}</tbody>
    </table>
    <p>合計 USD: <b>{portfolio.get('total_usd',0):.2f}</b> &nbsp;|&nbsp; JPY: <b>{portfolio.get('total_jpy',0):.2f}</b></p>
    """

def build_value_history_js(set_id: str):
    """ポートフォリオ評価額の時系列データをJSに変換"""
    hist_dir = REPO_ROOT / "data" / f"set_{set_id}" / "history"
    records = load_all_jsonl(hist_dir, "calls")
    labels, values_usd, values_jpy = [], [], []
    for r in records:
        pv = r.get("portfolio_value", {})
        if pv and r.get("timestamp"):
            labels.append(r["timestamp"][:16])
            values_usd.append(pv.get("total_usd", 0))
            values_jpy.append(pv.get("total_jpy", 0))
    return json.dumps(labels), json.dumps(values_usd), json.dumps(values_jpy)

def build_set_section(set_id: str, label: str) -> str:
    base = REPO_ROOT / "data" / f"set_{set_id}"
    assets      = load_json(base / "assets.json")
    watchlist   = load_json(base / "watchlist.json")
    last_session= load_json(base / "last_session.json")
    plan        = read_text(base / "plan.md")
    hist_dir    = base / "history"
    all_trades  = load_all_jsonl(hist_dir, "trades")

    portfolio   = last_session.get("portfolio_value", {})
    reasoning   = escape_html(last_session.get("reasoning", "（まだデータなし）"))
    summary     = escape_html(last_session.get("summary_for_report", ""))
    ts          = last_session.get("timestamp", "")[:16]

    labels_js, usd_js, jpy_js = build_value_history_js(set_id)

    trade_rows = build_trade_rows(all_trades)
    portfolio_table = build_portfolio_table(portfolio)
    plan_html = escape_html(plan).replace("\\n", "<br>") if plan else "（まだ計画なし）"

    keywords_html = ", ".join(
        f"<span class='tag'>{escape_html(k)}</span>"
        for k in watchlist.get("news_keywords", [])
    )
    tickers_html = ", ".join(
        f"<span class='tag ticker'>{escape_html(t)}</span>"
        for t in watchlist.get("tickers", [])
    )

    return f"""
  <section class="set-section" id="set-{set_id}">
    <h2>{label}</h2>

    <div class="cards">
      <div class="card">
        <h3>📊 最新ポートフォリオ評価</h3>
        <p class="timestamp">最終更新: {ts}</p>
        {portfolio_table}
      </div>
      <div class="card">
        <h3>🧠 LLMの最新判断</h3>
        <p class="timestamp">{ts}</p>
        <div class="summary-box">{summary}</div>
        <details>
          <summary>詳細な思考過程を表示</summary>
          <pre class="reasoning">{reasoning}</pre>
        </details>
      </div>
    </div>

    <div class="card full-width">
      <h3>📈 評価額推移</h3>
      <canvas id="chart-{set_id}" height="100"></canvas>
    </div>

    <div class="cards">
      <div class="card">
        <h3>📋 現在の投資計画</h3>
        <div class="plan-box">{plan_html}</div>
      </div>
      <div class="card">
        <h3>🔍 注目キーワード・銘柄</h3>
        <p><b>ニュースキーワード:</b><br>{keywords_html}</p>
        <p><b>ウォッチ銘柄:</b><br>{tickers_html}</p>
      </div>
    </div>

    <div class="card full-width">
      <h3>💹 トレード履歴（直近50件）</h3>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>日時</th><th>売買</th><th>銘柄</th><th>数量</th><th>価格</th><th>手数料</th><th>理由</th></tr>
          </thead>
          <tbody>{trade_rows}</tbody>
        </table>
      </div>
    </div>
  </section>

  <script>
  (function() {{
    var ctx = document.getElementById('chart-{set_id}').getContext('2d');
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {labels_js},
        datasets: [
          {{
            label: 'USD評価額',
            data: {usd_js},
            borderColor: '#4f8ef7',
            backgroundColor: 'rgba(79,142,247,0.1)',
            tension: 0.3,
            fill: true,
            yAxisID: 'y',
          }},
          {{
            label: 'JPY評価額',
            data: {jpy_js},
            borderColor: '#f7a84f',
            backgroundColor: 'rgba(247,168,79,0.1)',
            tension: 0.3,
            fill: false,
            yAxisID: 'y2',
          }},
        ]
      }},
      options: {{
        responsive: true,
        interaction: {{ mode: 'index', intersect: false }},
        scales: {{
          y:  {{ position: 'left',  title: {{ display: true, text: 'USD' }} }},
          y2: {{ position: 'right', title: {{ display: true, text: 'JPY' }}, grid: {{ drawOnChartArea: false }} }},
          x:  {{ ticks: {{ maxTicksLimit: 20, maxRotation: 45 }} }}
        }}
      }}
    }});
  }})();
  </script>
"""

def generate_report():
    DOCS_DIR.mkdir(exist_ok=True)

    section_a = build_set_section("a", "🅰️ セットA（安定志向）")
    section_b = build_set_section("b", "🅱️ セットB（利益志向）")

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LLM Investment Simulator – Report</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #f4f6fb;
      --card-bg: #fff;
      --accent-a: #4f8ef7;
      --accent-b: #f7a84f;
      --text: #222;
      --muted: #888;
      --border: #e0e4ef;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); }}
    header {{
      background: linear-gradient(135deg, #1a1f3c 0%, #2d3561 100%);
      color: #fff; padding: 2rem 2rem 1.5rem;
    }}
    header h1 {{ font-size: 1.8rem; }}
    header p  {{ color: #aab4d4; margin-top: 0.3rem; }}
    nav {{ display: flex; gap: 1rem; margin-top: 1rem; }}
    nav a {{
      color: #fff; background: rgba(255,255,255,0.15);
      padding: 0.3rem 1rem; border-radius: 20px;
      text-decoration: none; font-size: 0.9rem;
    }}
    nav a:hover {{ background: rgba(255,255,255,0.3); }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 2rem 1rem; }}
    .set-section {{ margin-bottom: 3rem; }}
    .set-section h2 {{
      font-size: 1.4rem; margin-bottom: 1rem;
      padding-bottom: 0.5rem; border-bottom: 2px solid var(--border);
    }}
    .cards {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }}
    @media(max-width: 700px) {{ .cards {{ grid-template-columns: 1fr; }} }}
    .card {{
      background: var(--card-bg); border-radius: 10px;
      padding: 1.2rem; border: 1px solid var(--border);
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }}
    .card.full-width {{ margin-bottom: 1rem; }}
    .card h3 {{ font-size: 1rem; margin-bottom: 0.7rem; color: #333; }}
    .timestamp {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 0.5rem; }}
    .summary-box {{
      background: #f0f4ff; border-left: 4px solid var(--accent-a);
      padding: 0.7rem 1rem; border-radius: 0 6px 6px 0;
      font-size: 0.95rem; line-height: 1.6;
    }}
    .reasoning {{ font-size: 0.82rem; white-space: pre-wrap; background: #f8f9fc; padding: 0.8rem; border-radius: 6px; margin-top: 0.5rem; max-height: 300px; overflow-y: auto; }}
    .plan-box {{ font-size: 0.88rem; white-space: pre-wrap; line-height: 1.7; max-height: 260px; overflow-y: auto; }}
    .tag {{
      display: inline-block; background: #eef2ff; color: #3a4ab0;
      padding: 2px 8px; border-radius: 12px; font-size: 0.8rem; margin: 2px;
    }}
    .tag.ticker {{ background: #fff3e0; color: #b05a00; }}
    .table-wrap {{ overflow-x: auto; }}
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    .data-table th {{ background: #f0f4ff; padding: 6px 8px; text-align: left; white-space: nowrap; }}
    .data-table td {{ padding: 5px 8px; border-bottom: 1px solid var(--border); }}
    details summary {{ cursor: pointer; color: var(--accent-a); font-size: 0.85rem; margin-top: 0.5rem; }}
    footer {{ text-align: center; color: var(--muted); font-size: 0.8rem; padding: 2rem; }}
  </style>
</head>
<body>
  <header>
    <h1>🤖 LLM Investment Simulator</h1>
    <p>Generated: {now_str()}</p>
    <nav>
      <a href="#set-a">🅰️ セットA (安定志向)</a>
      <a href="#set-b">🅱️ セットB (利益志向)</a>
    </nav>
  </header>
  <main>
    {section_a}
    {section_b}
  </main>
  <footer>
    <p>このレポートはGitHub Actionsにより自動生成されています。投資助言ではありません。</p>
  </footer>
</body>
</html>"""

    out = DOCS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"[INFO] Report generated: {out}")

if __name__ == "__main__":
    generate_report()
