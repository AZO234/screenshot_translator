# Screenshot Translator

<img src="images/translate.png">

周期的なスクリーンショット出力を持つエミュレータ（NP2kaiなど）からスクリーンショットを取得して、
Google Vision AI API または Tsseract でOCRを行い、Google Cloud Tanslation APIで翻訳するアプリです。

## 環境

- Visual Studio 2026 (C++)
- Python3.12 + Pip
- [Tsseract](https://github.com/tesseract-ocr/tesseract)
- Google Vision AI API
- Google Cloud Tanslation API

## 準備＆インストール

### Tesseract

Tesseractコマンドが実行できるようにしておきます。

#### Windows

- Python

エイリアス解除を、管理者権限のPowerShellで実行

``` powershrll
Remove-Item "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe" -Force
Remove-Item "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe" -Force
```

環境変数のPATHに`C:\Python312`を追加する。

- vcpkg

``` powershell
git clone https://github.com/microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat
```

- Tesseract

``` powershell
.\vcpkg.exe install tesseract:x64-windows
```

環境変数のPATHに`C:\vcpkg\packages\tesseract_x64-windows\tools\tesseract`を追加する。

#### POSIX

``` bash
$ sudo apt install tesseract-ocr
```

※学習データ（`eng.traineddata`, `jpn.traineddata`）はアプリ起動時に自動的に `tessdata/` ディレクトリへダウンロードされます。

#### カスタム学習データの利用

[カスタム学習データ（例：PC98フォント用など）](https://github.com/AZO234/retro_tessdata) を使用したい場合は、`.traineddata` ファイル（`.zip`ファイルは解凍して）をプロジェクト直下の `tessdata/` ディレクトリに配置してください。アプリのUIから選択可能になります。

### Screenshot Translator その１

cloneして依存ライブラリをインストールします。

#### Windows

``` powershell
git clone https://github.com/AZO234/screenshot_translator.git
cd screenshot_translator
python -m venv .venv
.venv/bin/activate
pip install -r requirements.txt
```

#### POSIX

``` bash
$ git clone https://github.com/AZO234/screenshot_translator.git
$ cd screenshot_translator
$ python -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt
```

### Google API （任意、より高精度）

- Vision AI API

[Vison AI API](https://console.cloud.google.com/marketplace/product/google/visionai.googleapis.com) を開いて、`有効にする` をクリックします。
（無料でも、支払情報などを入力する必要があります。）

- Cloud Tanslation API

[Cloud Tanslation API](https://console.cloud.google.com/marketplace/product/google/translate.googleapis.com) を開いて、`有効にする` をクリックします。

- APIキー取得

[認証情報](https://console.cloud.google.com/apis/credentials) を開きます。  
`認証情報を作成`→ `APIキー` をクリックします。  
`名前`は`translator`など適当に入力します。  
`APIの制限の選択`で、`Cloud Vision API` と `Cloud Translation API` にチェックを入れて `OK` をクリックします。  
`作成` をクリックします。  
`AIza...` のAPIキー文字列をコピーします。  

- Screenshot Translator へAPIキー文字列を登録

Screenshot Translator の、 .env.example ファイルを、.env ファイルへ複製します。  
.envファイル内の `GOOGLE_API_KEY="AIza..."` のダブルクォート内に、APIキー文字列をペーストします。

### エミュレータ

エミュレータの周期スクリーンショット機能の設定で、  
Screenshot Translator の、imput_screenshots/screen_1.png に、  
スクリーンショットが保存されるようにして下さい。

### Screenshot Translator その２

Screenshot Translator を起動します。
``` bash
$ python main.py
```

まずは、`Capture only` をクリックして、スクリーンショットが表示される事を確認しましょう。

`Lang` で、翻訳したい言語を設定して、  
`Font` で、使用するフォントを設定します。  
文字を含んだスクリーンショットが取得できる状態で、  
`Translate` をクリックします。

Google APIの無料枠を消費して、翻訳がオーバレイされれば成功です。

成功したスクリーンショットや翻訳情報は、`Keep This` をクリックすると保存できます。

## OCR＆本屋範囲指定

画像の一部を指定して OCR＆翻訳 させるには、５つまで範囲（ROI）を設定できます。

## ライブラリ閲覧

<img src="images/library.png">

保存した翻訳情報は、ライブラリで閲覧することが出来ます。

## API無料枠について

- Vision AI API : 1000サンプルまで
- Cloud Tanslation API : 100,000文字まで
毎月１日にリセット。

ROIを５つ設定すると、一度のOCRで5サンプル消費します。  
画像全体のOCRは1サンプルです。

Screenshot Translatorでは、  
APIキーごとに、これらの消費状況をカウントします。

Tesseract は無料ですが、標準の辞書では精度が良くないです。

## ライセンス

GPL-3.0
