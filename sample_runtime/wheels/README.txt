このフォルダ（ホイールハウス）には、manifest.json の packages に対応する
.whl ファイルを配置します。同期処理は下記コマンド相当を実行します:

    <target_python> -m pip install --no-index --find-links=<このフォルダ> name==version

デモ用に six==1.16.0 / certifi==2024.7.4 の実物の .whl を同梱しています
（軽量・純Python・依存なしのため動作確認がしやすいパッケージを選定）。
実運用では requests / numpy / pandas 等、組織で承認したパッケージの
.whl（依存パッケージ分も含む）をここに配置してください。
