import os
import base64
import json
import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
import usage_tracker
import pytesseract

# .envファイルからGOOGLE_API_KEYを読み込む
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")

# Tesseractの学習データを配置するディレクトリ (スクリプトからの相対パス)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TESSDATA_DIR = os.path.join(SCRIPT_DIR, "tessdata")

def get_api_key():
    return API_KEY

def ensure_tessdata():
    """
    Tesseractの学習データ(eng_best, jpn_best)をローカルにダウンロードして配置する。
    """
    os.makedirs(TESSDATA_DIR, exist_ok=True)
    
    # tessdata_bestのリポジトリから取得
    base_url = "https://github.com/tesseract-ocr/tessdata_best/raw/main/"
    files = ["eng.traineddata", "jpn.traineddata"]
    
    for filename in files:
        target_path = os.path.join(TESSDATA_DIR, filename)
        if not os.path.exists(target_path):
            print(f"Downloading {filename} to {target_path}...")
            url = base_url + filename
            try:
                response = requests.get(url, stream=True)
                response.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"Successfully downloaded {filename}")
            except Exception as e:
                print(f"Failed to download {filename}: {e}")
                if os.path.exists(target_path):
                    os.remove(target_path)

def get_font_from_path(font_path, size=24):
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except:
            pass
    return ImageFont.load_default()

def _otsu_threshold(hist):
    """ヒストグラムからOtsuのしきい値を計算する。"""
    total = sum(hist)
    if total == 0:
        return 128
    sum_total = sum(i * h for i, h in enumerate(hist))
    sum_b = 0.0
    w_b = 0
    max_var = -1.0
    threshold = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) * (m_b - m_f)
        if var > max_var:
            max_var = var
            threshold = t
    return threshold


def preprocess_for_retro_ocr(img, edge_padding=0):
    """レトロPC由来のカラー画像をTesseractの学習データ分布に寄せる。
    1) グレースケール化
    2) Otsu 2値化
    3) 黒地白文字なら反転して白地黒文字に揃える (学習データの主極性に合わせる)
    4) 周囲に edge_padding px の黒余白を追加 (学習データの CELL_PAD=1 構造に合わせる、
       密着配置の実画像で行頭文字が脱落する問題への対処)
    """
    if img.mode != 'L':
        img = img.convert('L')
    threshold = _otsu_threshold(img.histogram())
    bin_img = img.point(lambda v: 255 if v > threshold else 0, mode='L')
    # 平均輝度が暗い (=黒画素が多い) なら白文字on黒地と判断し反転
    bin_hist = bin_img.histogram()
    pixels = sum(bin_hist)
    if pixels > 0:
        mean = sum(i * h for i, h in enumerate(bin_hist)) / pixels
        if mean < 128:
            bin_img = Image.eval(bin_img, lambda v: 255 - v)
    if edge_padding > 0:
        canvas = Image.new('L', (bin_img.width + edge_padding*2,
                                 bin_img.height + edge_padding*2), 0)
        canvas.paste(bin_img, (edge_padding, edge_padding))
        bin_img = canvas
    return bin_img


def _ocr_to_data(img, lang, psm=7):
    """1枚を OCR し image_to_data の dict と平均信頼度を返す。

    psm=7: 単一行を想定 (行ごとに切り出して渡すため)。
    tessedit_do_invert=0: 極性は呼び出し側の A/B で選ぶので、Tesseract 内蔵の
    自動反転 (invert_threshold) を切り、2極性が同じ結果へ収束して A/B が無意味化
    するのを防ぐ。
    """
    config = f'--tessdata-dir "{TESSDATA_DIR}" --psm {psm} -c tessedit_do_invert=0'
    data = pytesseract.image_to_data(img, lang=lang, config=config,
                                     output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, t in zip(data['conf'], data['text'])
             if t.strip() and float(c) >= 0]
    mean_conf = sum(confs) / len(confs) if confs else -1.0
    return data, mean_conf


def _detect_line_bands(bin_img, min_line=6):
    """black-on-white 画像から文字行の (y0, y1) リストを返す。

    横投影 (各行の黒=インク画素数) で文字行の帯を検出し、行間の谷で分割する。
    全画面 psm6 の自動レイアウト解析は密着レイアウトで行分離に失敗するため、
    自前で行を切り出して 1 行ずつ OCR するための前段。密着して 1 帯に融合した
    複数行は、行高の中央値で等分割する (PC-98 等の行間ゼロ縦密着への対処)。
    """
    w, h = bin_img.size
    px = bin_img.load()
    proj = [sum(1 for x in range(w) if px[x, y] < 128) for y in range(h)]
    if not proj or max(proj) == 0:
        return [(0, h)]
    # 文字行の条件: 下限 thr (空行除外) < 塗り < 上限 rule (横罫線/枠ボーダー除外)。
    # ほぼ全幅が埋まる行 (>=65%) はダイアログ枠の横罫線で、文字行ではない。これを
    # 非文字扱いにすると罫線帯が min_line 未満に分断され自動的に消える (文字行は実測
    # で塗り <=40% なので巻き込まない)。下限は幅基準の絶対値 (max基準だと高密度行に
    # 引っ張られ薄い行が脱落するため)。
    thr = max(3, int(w * 0.02))
    rule = int(w * 0.65)
    text_rows = [thr < v < rule for v in proj]
    bands = []
    s = None
    for y, on in enumerate(text_rows):
        if on and s is None:
            s = y
        elif not on and s is not None:
            if y - s >= min_line:
                bands.append((s, y))
            s = None
    if s is not None and h - s >= min_line:
        bands.append((s, h))
    if not bands:
        return [(0, h)]
    heights = sorted(b[1] - b[0] for b in bands)
    med = heights[len(heights) // 2]
    line_h = med if 8 <= med <= 28 else 16
    out = []
    for y0, y1 in bands:
        n = max(1, round((y1 - y0) / line_h))
        if n == 1:
            out.append((y0, y1))
        else:
            step = (y1 - y0) / n
            for i in range(n):
                out.append((int(y0 + i * step), int(y0 + (i + 1) * step)))
    return out


def _x_cut(bin_img, gap_min=24, min_block=4):
    """black-on-white 画像を縦投影し、大きな横ギャップで列ブロックに分割する。

    ダイアログ本文・右パネル値・重なったキャラ絵などを別ブロックに切り分ける前段。
    列を先に切ることで、テキストに横方向で重なったグラフィック塊が後段の行検出
    (横投影) を汚染するのを防ぐ。日本語の字間 (CELL_PAD 0-3px) では割らないよう
    gap_min は 1 文字幅弱に取る。
    """
    w, h = bin_img.size
    px = bin_img.load()
    proj = [sum(1 for y in range(h) if px[x, y] < 128) for x in range(w)]
    if not proj or max(proj) == 0:
        return [(0, w)]
    thr = max(2, int(h * 0.02))
    on = [v > thr for v in proj]
    blocks = []
    s = None
    gap = 0
    for x, v in enumerate(on):
        if v:
            if s is None:
                s = x
            gap = 0
        elif s is not None:
            gap += 1
            if gap >= gap_min:
                blocks.append((s, x - gap + 1))
                s = None
                gap = 0
    if s is not None:
        blocks.append((s, w - gap))
    blocks = [(a, b) for a, b in blocks if b - a >= min_block]
    return blocks or [(0, w)]


def _ocr_line(line_img, lang, polarity_ab):
    """1 行画像を OCR し (テキスト, x0, x1, 平均信頼度) を返す。語が無ければ None。

    polarity_ab=True なら反対極性でも OCR し平均信頼度の高い方を採る
    (mean<128 極性判定の誤りや反転ハイライト行の救済)。
    """
    data, mean_conf = _ocr_to_data(line_img, lang, psm=7)
    if polarity_ab:
        inv_data, inv_mean = _ocr_to_data(Image.eval(line_img, lambda v: 255 - v),
                                          lang, psm=7)
        if inv_mean > mean_conf:
            data, mean_conf = inv_data, inv_mean
    words, lefts, rights = [], [], []
    for i in range(len(data['text'])):
        t = data['text'][i].strip()
        if not t or float(data['conf'][i]) < 0:
            continue
        words.append(t)
        lefts.append(data['left'][i])
        rights.append(data['left'][i] + data['width'][i])
    if not words:
        return None
    text = " ".join(words)
    if any(ord(c) > 127 for c in text):  # CJK はスペースを詰める
        text = text.replace(" ", "")
    return text, min(lefts), max(rights), mean_conf


def detect_text_tesseract(image_content, lang="jpn+eng", edge_padding=0,
                          polarity_ab=True, min_block_conf=40):
    """
    Tesseract OCR でテキストを検出する。XY カット方式:
      1) 縦投影で大きな横ギャップを境に「列ブロック」へ分割 (_x_cut)。本文・右パネル・
         重なったキャラ絵などが別ブロックに分かれる。
      2) 各列ブロックを横投影で「行」に分割 (_detect_line_bands)。列を先に切るので、
         重なったグラフィック塊が行検出を汚染しない。
      3) 各行を psm7 で個別 OCR (行単位の極性 A/B 付き)。
      4) ブロック平均信頼度が min_block_conf 未満のブロックは破棄 (キャラ絵塊などの
         非テキストはゴミ低信頼になるため自動除去)。
    各行を per-line 検出として返し、呼び出し側の merge_nearby_detections で隣接行が
    文章ブロックへ再結合される。
    lang: 学習データ (例 "jpn+eng", "pc98")
    edge_padding: preprocess の黒余白 px (box 座標から差し引く)
    polarity_ab: 各行を両極性 OCR し高信頼側を採用 (極性誤判定・反転行の救済)
    min_block_conf: 列ブロック平均信頼度の下限。下回るブロックは非テキストとして破棄
    """
    import io
    img = Image.open(io.BytesIO(image_content))
    bin_img = preprocess_for_retro_ocr(img, edge_padding=edge_padding)

    detections = []
    for bx0, bx1 in _x_cut(bin_img):
        block = bin_img.crop((bx0, 0, bx1, bin_img.height))
        block_dets, confs = [], []
        for y0, y1 in _detect_line_bands(block):
            line = block.crop((0, max(0, y0 - 1),
                               block.width, min(block.height, y1 + 1)))
            res = _ocr_line(line, lang, polarity_ab)
            if res is None:
                continue
            text, lx0, lx1, conf = res
            confs.append(conf)
            block_dets.append({
                "text": text,
                "box": (max(0, bx0 + lx0 - edge_padding),
                        max(0, y0 - edge_padding),
                        lx1 - lx0,
                        y1 - y0),
            })
        # 非テキスト (キャラ絵塊など) ブロックは平均信頼度で破棄
        if block_dets and sum(confs) / len(confs) >= min_block_conf:
            detections.extend(block_dets)
    return detections

def detect_text_api(image_content):
    """
    Google Cloud Vision API (REST) を使用してテキストを検出する。
    段落 (Paragraph) 単位でテキストを抽出し、文脈を維持する。
    """
    if not API_KEY:
        raise Exception("GOOGLE_API_KEY not found in .env file.")

    usage_tracker.record_vision(API_KEY, 1)
    url = f"https://vision.googleapis.com/v1/images:annotate?key={API_KEY}"
    
    image_base64 = base64.b64encode(image_content).decode('utf-8')
    
    payload = {
        "requests": [
            {
                "image": {"content": image_base64},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}]
            }
        ]
    }
    
    response = requests.post(url, json=payload)
    result = response.json()
    
    if "error" in result:
        raise Exception(f"Vision API Error: {result['error']['message']}")

    detections = []
    responses = result.get("responses", [])
    if not responses or "fullTextAnnotation" not in responses[0]:
        return detections

    # fullTextAnnotation から構造的にテキストを取得
    for page in responses[0]["fullTextAnnotation"]["pages"]:
        for block in page["blocks"]:
            for paragraph in block["paragraphs"]:
                # 段落内の言葉を連結
                para_text = ""
                for word in paragraph["words"]:
                    for symbol in word["symbols"]:
                        para_text += symbol["text"]
                        # 記号の後にスペースを入れるべきかの判定（簡易的）
                        if "property" in symbol and "detectedBreak" in symbol["property"]:
                            break_type = symbol["property"]["detectedBreak"]["type"]
                            if break_type in ["SPACE", "SURE_SPACE"]:
                                para_text += " "
                            elif break_type in ["EOL_SURE_SPACE", "LINE_BREAK"]:
                                para_text += " "
                
                # 段落の外枠座標を計算
                vertices = paragraph["boundingBox"]["vertices"]
                x_coords = [v.get("x", 0) for v in vertices]
                y_coords = [v.get("y", 0) for v in vertices]
                x, y = min(x_coords), min(y_coords)
                w, h = max(x_coords) - x, max(y_coords) - y
                
                if para_text.strip():
                    detections.append({
                        "text": para_text.strip(),
                        "box": (x, y, w, h)
                    })
    
    return detections

def translate_texts_api(texts, target_lang="ja"):
    """
    Google Cloud Translation API (REST) を使用して一括翻訳する。
    """
    if not texts:
        return []
    if not API_KEY:
        raise Exception("GOOGLE_API_KEY not found in .env file.")

    usage_tracker.record_translation(API_KEY, texts)
    url = f"https://translation.googleapis.com/language/translate/v2?key={API_KEY}"
    
    payload = {
        "q": texts,
        "target": target_lang
    }
    
    response = requests.post(url, json=payload)
    result = response.json()
    
    if "error" in result:
        raise Exception(f"Translation API Error: {result['error']['message']}")
        
    translations = result.get("data", {}).get("translations", [])
    return [t["translatedText"] for t in translations]

def merge_nearby_detections(detections, threshold=15):
    """
    位置が近い、または重なっているブロックを一つの文章として結合する。
    """
    if not detections:
        return []
    
    def is_cjk(text):
        # 日本語などのCJK文字が含まれているか判定
        return any(ord(c) > 0x3000 for c in text)

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(detections):
            j = i + 1
            while j < len(detections):
                d1 = detections[i]
                d2 = detections[j]
                b1 = d1["box"]
                b2 = d2["box"]
                
                # 判定用のバウンディングボックスを少し広げる (しきい値分)
                p = threshold
                # 衝突判定
                overlap = (b1[0] - p < b2[0] + b2[2] and
                           b1[0] + b1[2] + p > b2[0] and
                           b1[1] - p < b2[1] + b2[3] and
                           b1[1] + b1[3] + p > b2[1])
                
                if overlap:
                    # 2つのブロックを結合
                    x = min(b1[0], b2[0])
                    y = min(b1[1], b2[1])
                    w = max(b1[0] + b1[2], b2[0] + b2[2]) - x
                    h = max(b1[1] + b1[3], b2[1] + b2[3]) - y
                    
                    # テキストの結合（上下関係を見て順序を決める）
                    sep = "" if is_cjk(d1["text"]) else " "
                    if b1[1] < b2[1]:
                        new_text = d1["text"] + sep + d2["text"]
                    else:
                        new_text = d2["text"] + sep + d1["text"]
                    
                    detections[i] = {"text": new_text, "box": (x, y, w, h)}
                    detections.pop(j)
                    changed = True
                else:
                    j += 1
            i += 1
    return detections

def translate_image(image_path, font_path=None, rois=None, target_lang="ja", engine="tesseract", ocr_lang="jpn+eng", roi_expansion=0):
    """
    OCRエンジンを選択して画像を翻訳する。
    engine: "google" or "tesseract"
    ocr_lang: Tesseract用の言語指定
    roi_expansion: 各 ROI を外側に拡張する px 数。デフォルト 0 = 描いた枠を1ドットも
                   膨らませず「ドットバイドット」でそのまま使う (枠外の罫線・グラフィックを
                   巻き込まない)。文字端が枠で切れる場合のみ 1〜2 を指定。
                   ※ 枠内の処理 (行分割・横罫線フィルタ・余白トリム) は
                   detect_text_tesseract 側 (XY/行カット) が担うため、拡張は不要。
    """
    try:
        orig_img = Image.open(image_path).convert("RGBA")
        draw = ImageDraw.Draw(orig_img)
        font = get_font_from_path(font_path, 24)

        all_detections = []

        # 1. OCRの実行
        def run_ocr(content):
            if engine == "tesseract":
                return detect_text_tesseract(content, lang=ocr_lang)
            else:
                return detect_text_api(content)

        if not rois:
            with open(image_path, 'rb') as f:
                content = f.read()
            all_detections = run_ocr(content)
        else:
            img_w, img_h = orig_img.size
            for rx, ry, rw, rh in rois:
                # ROI を外側に roi_expansion px 拡張 (画像範囲でクランプ)
                exp = roi_expansion
                ex1 = max(0, rx - exp)
                ey1 = max(0, ry - exp)
                ex2 = min(img_w, rx + rw + exp)
                ey2 = min(img_h, ry + rh + exp)
                crop = orig_img.crop((ex1, ey1, ex2, ey2))
                import io
                buf = io.BytesIO()
                crop.save(buf, format='PNG')
                roi_detections = run_ocr(buf.getvalue())
                for d in roi_detections:
                    dx, dy, dw, dh = d["box"]
                    # 拡張クロップ内座標 → 元画像座標
                    d["box"] = (dx + ex1, dy + ey1, dw, dh)
                    all_detections.append(d)

        if not all_detections:
            return orig_img.convert("RGB"), []

        # 1.5 近接ブロックの結合
        all_detections = merge_nearby_detections(all_detections)

        # 2. 翻訳
        original_texts = [d["text"] for d in all_detections]
        translated_texts = translate_texts_api(original_texts, target_lang=target_lang)
        
        # 3. 描画
        import html
        for i, item in enumerate(all_detections):
            trans_text = html.unescape(translated_texts[i])
            x, y, _, _ = item["box"]
            
            bbox = draw.textbbox((x, y), trans_text, font=font)
            p = 5
            rect = [bbox[0]-p, bbox[1]-p, bbox[2]+p, bbox[3]+p]
            draw.rectangle(rect, fill=(0, 0, 0, 180))
            draw.text((x, y), trans_text, font=font, fill=(255, 255, 255, 255))
            item["translated"] = trans_text
            
        return orig_img.convert("RGB"), all_detections
    except Exception as e:
        print(f"Error: {e}")
        return None, []

def translate_text(text, target_lang="ja"):
    """互換性のための単発翻訳"""
    results = translate_texts_api([text], target_lang=target_lang)
    return results[0] if results else text
