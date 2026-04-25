# Screenshot Translator

<img src="images/translate.png">

周期的なスクリーンショット出力を持つエミュレータ（NP2kaiなど）からスクリーンショットを取得して、
Google Vision AI API または Tsseract でOCRを行い、Google Cloud Tanslation APIで翻訳するアプリです。

## 環境

- Python3 + Pip
- [Tsseract](https://github.com/tesseract-ocr/tesseract)
- Google Vision AI API
- Google Cloud Tanslation API

## 準備＆インストール

### Tesseract

Tesseractコマンドが実行できるようにしておきます。

``` bash
sudo apt install tesseract-ocr tesseract-ocr-jpn
```

### Screenshot Translator その１

cloneして依存ライブラリをインストールします。

``` bash
$ git clone https://github.com/AZO234/screenshot_translator.git
$ cd screenshot_translator
$ python -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt
```

### Google API

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

エミュレータの周期スクリーンショットの設定で、  
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

Tesseract は無料ですが、制度が良くないです。

Screenshot Translatorでは、  
APIキーごとに、これらの消費状況をカウントします。

## ライセンス

GPL-3.0
