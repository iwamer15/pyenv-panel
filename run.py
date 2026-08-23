"""PyInstallerのエントリポイント用ラッパー。

app/main.py を直接Analysisの起点にすると、PyInstallerがそれを
トップレベルスクリプト（パッケージに属さない `main` モジュール）として
実行してしまい、app パッケージ内の相対importが失敗する
（ImportError: attempted relative import with no known parent package）。

そのため、`app` パッケージを正しくimportしてから main() を呼ぶ
薄いラッパーをエントリポイントにする。
"""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
