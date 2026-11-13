# LLM Investment Simulator

GitHub Actions と Google Gemini を使い、セット A（安定志向）と B（利益志向）の仮想資産を運用・表示します。実際の売買は行いません。投資助言ではなく、投資判断の参考にも適しません。

## 文書

- [仕様書](specification.md)：現行動作、制約、障害時の扱い。
- [設計書](design.md)：構成、データ形式、保存と信頼境界。
- [改善計画書](plan.md)：対応内容、テスト、今後の課題。
- `data/set_*/plan.md`：LLM が更新する各セットの投資計画。上記のソフトウェア改善計画とは別です。
- `data/set_*/system_prompt.md`：運用者管理のエージェント方針。`investment_method/methods.md`：運用者管理の参考資料。

## 仕組み

平日 JST 09:00 / 13:00 / 17:00 に Actions が起動予定です（祝日判定なし）。A、B の仮想売買と保存を行い、`docs/index.html` を生成し GitHub Pages に公開します。通常、両セットが API に到達すると1日6回 Gemini を呼び出します。手動実行や失敗等により回数は変わります。

保有銘柄とウォッチ銘柄の価格を取得し、価格欠損・残高・集中比率などをコードで検証します。通貨別に集計し、為替換算はしません。API エラーは記録したうえでジョブを失敗させます。レポートは最新評価、取引状態、評価推移のほか、直近30回の API 成功・失敗を表示します。

**重要:** 外部ニュース本文・見出しと過去の LLM 生成計画は、プロンプト汚染を避けるため Gemini に渡しません。RSS の件数は記録しますが、現在ニュースの内容は投資判断に利用されません。プロンプトに記された全ての投資方針が機械的に保証されるわけではありません。許可銘柄、損切り、取得単価不明時の扱い、保存上の限界を含む詳細は [仕様書](specification.md) を参照してください。

## 構成

```text
.github/workflows/   # シミュレーション、テスト
scripts/             # simulate.py、generate_report.py
data/set_a/         # 資産、ウォッチリスト、投資計画、プロンプト、最新セッション、月別履歴
data/set_b/         # 同構成
investment_method/   # 投資メソッド（人手管理）
docs/index.html      # 自動生成レポート
requirements.txt     # Python 依存
tests/              # 外部アクセスをモックした自動テスト
```

## セットアップ・実行

1. GitHub Secret `GEMINI_API_KEY` を設定します。任意の Variable `FEE_RATE` の既定値は `0.001`（0.1%）です。
2. GitHub Pages の `Settings → Pages → Source` を **GitHub Actions** に設定し、ワークフローにコンテンツ書き込みと Pages デプロイ権限を付与します。
3. `data/set_*/assets.json` の通貨別現金・保有数量、`watchlist.json`、`system_prompt.md` と `investment_method/methods.md` を用意します。過去の JSONL は任意です。データ形式は [設計書](design.md) を参照してください。
4. 手動実行は `Actions → LLM Investment Simulator → Run workflow`。`session_override` は空欄か `1`、`2`、`3` です。空欄の手動実行は開始時刻に基づきます。

ローカルでは Python 3.11 と `requirements.txt` を使用します。

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY='利用する API キー'
python scripts/simulate.py --set a --session 1 --session-id my-session-1
python scripts/simulate.py --set b --session 1 --session-id my-session-1
python scripts/generate_report.py
python -m unittest discover -s tests -v
```

同じセットで成功済みの `--session-id` は再実行時にスキップします。省略時はローカルでは毎回新しい ID になり、Actions では同じ workflow run の再実行に同じ `GITHUB_RUN_ID` を使います。実行は `data/` を更新し、レポート生成は `docs/index.html` を上書きします。実行前にバックアップし、キーをリポジトリに保存しないでください。ログや例外文は Pages に公開される可能性があります。
