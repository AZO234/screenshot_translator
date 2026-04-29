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

def detect_text_tesseract(image_content, lang="jpn+eng"):
    """
    Tesseract OCR を使用してテキストを検出する。
    lang: 使用する学習データ (例: "jpn+eng", "pc98")
    """
    import io
    img = Image.open(io.BytesIO(image_content))
    
    # ローカルのtessdataを使用するように設定
    config = f'--tessdata-dir "{TESSDATA_DIR}"'
    
    # 段落情報を取得するために image_to_data を使用
    data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    
    detections = []
    n_boxes = len(data['text'])
    
    # (block_num, par_num) をキーにして単語をグループ化
    paragraphs = {}
    for i in range(n_boxes):
        text = data['text'][i].strip()
        if not text:
            continue
            
        block_id = data['block_num'][i]
        par_id = data['par_num'][i]
        key = (block_id, par_id)
        
        if key not in paragraphs:
            paragraphs[key] = {
                "texts": [],
                "left": data['left'][i],
                "top": data['top'][i],
                "right": data['left'][i] + data['width'][i],
                "bottom": data['top'][i] + data['height'][i]
            }
        
        p = paragraphs[key]
        p["texts"].append(text)
        p["left"] = min(p["left"], data['left'][i])
        p["top"] = min(p["top"], data['top'][i])
        p["right"] = max(p["right"], data['left'][i] + data['width'][i])
        p["bottom"] = max(p["bottom"], data['top'][i] + data['height'][i])

    for p in paragraphs.values():
        combined_text = " ".join(p["texts"])
        # 日本語の場合はスペースを詰める
        if any(ord(c) > 127 for c in combined_text):
            combined_text = combined_text.replace(" ", "")
            
        detections.append({
            "text": combined_text,
            "box": (p["left"], p["top"], p["right"] - p["left"], p["bottom"] - p["top"])
        })
        
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

def translate_image(image_path, font_path=None, rois=None, target_lang="ja", engine="tesseract", ocr_lang="jpn+eng"):
    """
    OCRエンジンを選択して画像を翻訳する。
    engine: "google" or "tesseract"
    ocr_lang: Tesseract用の言語指定
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
            for rx, ry, rw, rh in rois:
                crop = orig_img.crop((rx, ry, rx + rw, ry + rh))
                import io
                buf = io.BytesIO()
                crop.save(buf, format='PNG')
                roi_detections = run_ocr(buf.getvalue())
                for d in roi_detections:
                    dx, dy, dw, dh = d["box"]
                    d["box"] = (dx + rx, dy + ry, dw, dh)
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
