import os
import subprocess
from pathlib import Path

def modify_requirements():
    req_path = Path("requirements.txt")
    
    if not req_path.exists():
        print(f"[ERROR] {req_path.name} が見つかりません。パスを確認してください。")
        return

    print(f"[INFO] {req_path.name} から yfinance を除去中...")
    
    # 1. requirements.txt を読み込み、yfinance の行を除外する
    with open(req_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    new_lines = []
    removed = False
    for line in lines:
        # 空白を除去して、yfinanceで始まる行（バージョン指定含む）をスキップ
        if line.strip().startswith("yfinance"):
            removed = True
            continue
        new_lines = line

    # 2. 変更があった場合のみファイルを上書き保存
    if removed:
        with open(req_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"[OK] {req_path.name} から yfinance を削除しました。")
    else:
        print(f"[INFO] {req_path.name} 内に yfinance の記述はありませんでした。")

if __name__ == "__main__":
    modify_requirements()
