# LLM Investment Simulator

GitHub Actions + Google Gemini Flash を使った **投資シミュレーター**。  
実際の売買は行わず、仮想の資産を LLM が運用します。

## 仕組み

```
GitHub Actions (平日 1日3回起動)
  ├─ Set A シミュレーション (安定志向プロンプト)
  │    ├─ ニュース取得 (feedparser / Google News RSS)
  │    ├─ 株価取得 (yfinance)
  │    ├─ Gemini API 呼び出し → トレード指示 + 計画更新
  │    └─ data/set_a/ へ結果保存
  ├─ Set B シミュレーション (利益志向プロンプト)
  │    └─ data/set_b/ へ結果保存
  └─ GitHub Pages レポート生成 → docs/index.html
```

1日3セッション × 2セット = **Gemini API を1日6回呼び出し**

## ディレクトリ構成

```
.
├── .github/workflows/simulate.yml   # GitHub Actionsワークフロー
├── scripts/
│   ├── simulate.py                  # シミュレーション本体
│   └── generate_report.py           # HTMLレポート生成
├── data/
│   ├── set_a/                       # セットA（安定志向）
│   │   ├── assets.json              # 現在の資産
│   │   ├── plan.md                  # LLMの投資計画
│   │   ├── watchlist.json           # 注目銘柄・キーワード
│   │   ├── system_prompt.md         # エージェントへのシステムプロンプト
│   │   ├── last_session.json        # 直近セッション結果
│   │   └── history/                 # 月別ログ
│   │       ├── calls_YYYY-MM.jsonl  # API呼び出し履歴
│   │       └── trades_YYYY-MM.jsonl # トレード履歴
│   └── set_b/                       # セットB（利益志向）
│       └── ...（同構成）
├── investment_method/
│   └── methods.md                   # 投資理論参考資料（手動で記入）
├── docs/
│   └── index.html                   # GitHub Pages レポート（自動生成）
└── requirements.txt
```

## セットアップ

### 1. リポジトリの設定

#### Secrets
| 名前 | 説明 |
|------|------|
| `GEMINI_API_KEY` | Google Gemini API キー |

#### Variables（任意）
| 名前 | デフォルト | 説明 |
|------|-----------|------|
| `FEE_RATE` | `0.001` | 手数料率（0.1%） |

### 2. GitHub Pages の有効化
`Settings → Pages → Source: GitHub Actions`

### 3. 初期データの準備（ユーザーが用意するもの）

#### 投資メソッド
`investment_method/methods.md` に投資理論を記入してください。

#### 初期資産
`data/set_a/assets.json` と `data/set_b/assets.json` の `cash` 欄を編集してください。

#### 過去データ
`data/set_*/history/` 以下に初期の履歴ファイルを配置できます（任意）。

#### プロンプトのカスタマイズ
`data/set_a/system_prompt.md` と `data/set_b/system_prompt.md` を編集してください。

### 4. 手動実行
`Actions → LLM Investment Simulator → Run workflow` でいつでも手動実行できます。

## 注意事項
- このシミュレーターは実際の投資を行いません
- 投資判断の参考にしないでください
- Gemini API の無料枠（1日あたりのリクエスト数）に注意してください
