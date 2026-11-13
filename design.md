# ソフトウェア設計書

[仕様書](specification.md) の動作に対応する。改善事項は [計画書](plan.md)。`data/set_*/plan.md` は LLM が管理する投資計画であり、ソフトウェアの開発計画書ではない。

## コンポーネントと処理

| 要素 | 責務 |
| --- | --- |
| `.github/workflows/simulate.yml` | cron または検証済み手動入力からセッションを決め、A・B を実行、各結果をコミットし、レポート・Pages を更新。API 等の失敗は最終的にジョブを失敗させる |
| `.github/workflows/test.yml` | push / PR 時に Python 3.11 で依存を導入し、外部サービスをモックしたテストを実行 |
| `scripts/simulate.py` | 状態検証、RSS・価格取得、Gemini 呼び出し、リスク判定、取引、ジャーナル付き保存 |
| `scripts/generate_report.py` | 両セットをロックし未完了ジャーナルを回復後、状態と履歴を安全に HTML 化。API 稼働状況を集計 |
| `data/set_a`, `data/set_b` | 独立した状態・プロンプト・月別履歴 |
| `investment_method/methods.md` | 運用者管理の参考資料。機械的ルールとは別 |
| `docs/index.html` | スクリプト生成の Pages 用 HTML。手編集しない |

処理は、ロック・回復 → 既成功のセッション確認 → 入力検証 → RSS/保有・ウォッチ価格取得 → 評価 → Gemini → 提案銘柄の価格再取得 → B 損切り → 独立した売買検証 → 評価・ログ・状態の一括回復可能な保存、の順。A/B のうち一方が失敗してももう一方は実行される。Actions は各セット後に `data/**` をコミットし、最終的に `docs/**` もコミットする。

## データ形式

UTF-8、JSON または1行1 JSON の JSONL。新規保存は NaN / Infinity を許さない。既存の旧履歴にある非有限値は修正せず、レポートのグラフでは欠損として扱う。

| ファイル | 内容 |
| --- | --- |
| `data/set_*/assets.json` | `cash`: 通貨コード→残高、`holdings`: 銘柄→数量 |
| `data/set_*/watchlist.json` | `news_keywords`, `tickers` の文字列配列。成功応答で全取引が拒否されなければ更新 |
| `data/set_*/plan.md` | LLM 作成の投資計画。上記と同じ条件で更新。次回 LLM 入力には戻さない |
| `data/set_*/system_prompt.md` | 運用者が管理するシステム指示 |
| `history/calls_YYYY-MM.jsonl` | `timestamp`, `set`, `session`, `session_id`, `status`, `elapsed_sec`, `news_count`, `tickers_fetched`, `portfolio_value`, `llm_summary` |
| `history/trades_YYYY-MM.jsonl` | `timestamp`, `action`, `ticker`, `qty`, `price`, `fee`, `currency`, `reason`, `status`, `set`, `session`, `session_id`。拒否時は `status` と、資金不足なら `available` / `required`、売却成功なら `actual_gain` を含む |
| `last_session.json` | `timestamp`, `session`, `session_id`, `status`, `reasoning`, `trades_executed`, `summary_for_report`, `portfolio_value`, `prices_snapshot` |
| `.transaction.json` | 保存対象の相対パスと完成後の内容を持つ write-ahead journal。正常完了時に削除、残存時はロックの下で再適用 |
| `.simulation.lock` | セット単位の POSIX 排他ロック。Git では無視 |

`portfolio_value` は `totals_by_currency`, `total_usd`, `total_jpy`, `complete`, `missing_tickers`, `breakdown`（`ticker`, `qty`, `price`, `value`, `currency`）, `cash` を持つ。`prices_snapshot` は成功時 `price`, `change_pct`, `52w_high`, `52w_low`, `currency`、失敗時 `error`。`tickers_fetched` は成功した銘柄の一覧ではなく価格辞書のキー一覧。タイムスタンプ・月ファイル名は JST。旧データには新フィールドがない。

## 信頼境界とリスク制御

RSS はネットワークから取得するが記事テキストを LLM に渡さず、LLM が以前生成した計画・ウォッチリストのテキストも指示として再投入しない。ティッカーは文字種・長さを検証、価格は正の有限値と通貨形式を検証し、エラー文字列はモデルへ渡さない。モデルの JSON スキーマに加え、アプリ側で構造と件数を検証する。発注はモデルと別のコードで許可リスト、残高、完全な評価、集中・現金・日次数の制限を検査する。既保有銘柄の売却は許可リスト外でも可能。

B の取得単価は時系列取引から加重平均で復元、現在の保有数量との一致を要求する。取引履歴が欠落・不正または数量不一致であれば取得単価を推定せず、B の買いを拒否する。損切りは検証できた銘柄のみ。コスト計算には手数料を含めない。リスク管理の範囲・制限は仕様書を参照。

レポートでは HTML 出力をエスケープし、`<`, `>`, `&` を Unicode エスケープした JSON を script に埋め込む。グラフは数値以外・非有限値・不完全評価を `null` とする。月単位で最大500件、連結後最大500件を読むので月200件の早期切捨てはない。最新30回の `status == ok` を成功、それ以外を失敗として件数と最新状態を表示する。

## 永続化と障害境界

同一セットのシミュレーションとレポート生成は `flock` を共有する。各ファイルは一時ファイルを書き込み・fsync して rename、親ディレクトリも fsync する。最初に完全な更新内容の journal を原子的に記録し、全ファイルを同じ内容で再適用できるため、途中中断後にロールフォワードできる。成功した `session_id` を履歴から検索し再実行をスキップする。API エラーは履歴を保存し例外を送出するため、同一 ID でも再試行できる。

Actions では同一 ref の同時実行を制御し、再実行時に対象ブランチの最新状態をチェックアウトする。ロックは他の環境や ref と共有されない。ランナー消失が Git commit/push より前の場合、ジャーナルごと失われうる。また外部のロック非対応読者には複数ファイルの途中状態が見える。これらを完全な分散トランザクションとみなさない。

## 対応 Issue と文書の整合

- #1–#4: 保有銘柄の取得・欠損表示、通貨別集計、価格欠損の拒否記録、実売却数の手数料。
- #5–#9: API 失敗の通知、独立したリスク制約、cron 由来の番号、入力検証、ジャーナル・ロック・セッション ID とセット別コミット。
- #10–#13: HTML/script のエスケープ、月200件の切捨て解消、RSS エンコード・交互選択・エラー検知、yfinance の依存明示。
- #14–#16: 有限値検証、拒否状態の表示、外部ニュースと過去の LLM 生成文を LLM の入力から隔離。

既存 A/B の投資計画はスナップショットであり現時点の構成を保証しない。B の QQQ 目標はプロンプトの40%上限と矛盾しないよう更新したが、実際の保有は超過している。README・仕様書では保証と制限を区別する。
