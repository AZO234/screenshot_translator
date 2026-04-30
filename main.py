import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
from datetime import datetime
import json
import glob
import platform

# 自作モジュール
import image_manager
import translator
import usage_tracker

class CyclicTranslatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Translator Image Focus Viewer & Library")
        self.geometry("1200x1000")

        # Tesseract学習データの準備 (バックグラウンドで実行)
        threading.Thread(target=translator.ensure_tessdata, daemon=True).start()

        # 状態管理
        self.screenshot_dir = os.path.abspath("input_screenshots")
        self.keep_dir = os.path.abspath("kept_translations")
        os.makedirs(self.keep_dir, exist_ok=True)
        
        self.show_overlay = True
        self.current_data = None # (Trans_PIL, Orig_PIL, Metadata)
        self.selected_lib_data = None # (Trans_PIL, Orig_PIL, Metadata) for library view
        self.last_action = None # "translate" or "capture"
        
        # ROI (Rubber-band) 状態
        self.rois = []
        for i in range(5):
            self.rois.append({
                "active": tk.BooleanVar(value=False),
                "coords": None,
                "label": None
            })
        
        # 選択モード状態
        self.selecting_roi_idx = -1
        self.selection_start = None
        self.current_selection_rect = None

        # 言語設定 (ISO 639-1)
        self.available_langs = ["ja", "en", "es", "zh", "tw", "ru", "ko", "fr", "de", "it", "pt", "vi", "th"]
        self.selected_lang_code = "ja"
        self.selected_ocr_engine = "tesseract"
        self.selected_tess_model = "jpn+eng"

        # フォント設定
        self.fonts_dict = self.get_available_fonts()
        
        # Noto Sans CJK JP を優先的にデフォルトにする
        self.default_font_name = "Default"
        self.selected_font_path = None
        
        priority_fonts = ["Noto Sans CJK JP", "Noto Serif CJK JP", "Noto Sans JP", "Noto Serif JP"]
        for pf in priority_fonts:
            if pf in self.fonts_dict:
                self.default_font_name = pf
                self.selected_font_path = self.fonts_dict[pf]
                break
        
        if self.default_font_name == "Default" and len(self.fonts_dict) > 1:
            # 優先フォントがない場合は "Default" 以外の最初のフォントを選択
            for name, path in self.fonts_dict.items():
                if name != "Default":
                    self.default_font_name = name
                    self.selected_font_path = path
                    break
        
        self.setup_ui()
        self.update_usage_display()
        self.bind("<Configure>", self.on_resize)

    def get_available_fonts(self):
        fonts = {"Default": None}
        system = platform.system()
        
        if system in ["Linux", "Darwin"]:
            # Linux と macOS で fc-list が使えるか試す
            try:
                output = subprocess.check_output(["fc-list", ":lang=ja", "family", "file"], text=True)
                for line in output.splitlines():
                    if ":" in line:
                        path, name = line.split(":", 1)
                        family = name.split(",")[0].strip()
                        fonts[family] = path.strip()
            except:
                pass
            
            # macOS で fc-list が失敗した場合のフォールバック
            if system == "Darwin" and len(fonts) <= 1:
                mac_font_dirs = ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
                common_mac_fonts = {
                    "Hiragino Sans": "Hiragino Sans GB.ttc",
                    "Hiragino Kaku Gothic": "ヒラギノ角ゴシック W3.ttc",
                    "Hiragino Mincho ProN": "ヒラギノ明朝 ProN.ttc",
                    "AppleGothic": "AppleGothic.ttf"
                }
                for d in mac_font_dirs:
                    if not os.path.exists(d): continue
                    for name, filename in common_mac_fonts.items():
                        path = os.path.join(d, filename)
                        if os.path.exists(path):
                            fonts[name] = path

        elif system == "Windows":
            # Windowsの標準フォントディレクトリから日本語っぽいのを探す
            font_dir = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts")
            # 代表的な日本語フォントファイル名のマッピング
            common_ja_fonts = {
                "MS Gothic": "msgothic.ttc",
                "MS PGothic": "msgothic.ttc",
                "MS UI Gothic": "msgothic.ttc",
                "Meiryo": "meiryo.ttc",
                "Yu Gothic": "yugothic.ttf",
                "Yu Gothic UI": "YuGothM.ttc"
            }
            for name, filename in common_ja_fonts.items():
                path = os.path.join(font_dir, filename)
                if os.path.exists(path):
                    fonts[name] = path
            
            # ディレクトリ内をスキャンして .ttc や .ttf を追加（簡易的）
            if os.path.exists(font_dir):
                for f in os.listdir(font_dir):
                    if f.lower().endswith((".ttc", ".ttf")) and "noto" in f.lower():
                        name = f.split(".")[0]
                        fonts[name] = os.path.join(font_dir, f)
        
        return fonts

    def setup_ui(self):
        self.tabview = ctk.CTkTabview(self, command=self.on_tab_change)
        self.tabview.pack(expand=True, fill="both", padx=10, pady=10)

        self.tab_translate = self.tabview.add("Translate")
        self.tab_library = self.tabview.add("Library")

        self.setup_translate_tab()
        self.setup_library_tab()

    def setup_translate_tab(self):
        self.tab_translate.grid_columnconfigure(0, weight=1)
        self.tab_translate.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self.tab_translate)
        header.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.lbl_dir = ctk.CTkLabel(header, text=f"Target Dir: {self.screenshot_dir}")
        self.lbl_dir.pack(side="left", padx=10)
        ctk.CTkButton(header, text="Browse", command=self.browse_directory, width=80).pack(side="right", padx=10)

        self.image_container = ctk.CTkFrame(self.tab_translate)
        self.image_container.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.canvas = tk.Canvas(self.image_container, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both")
        self.canvas.bind("<ButtonPress-1>", self.on_selection_start)
        self.canvas.bind("<B1-Motion>", self.on_selection_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_selection_end)

        self.ctrl_panel = ctk.CTkFrame(self.tab_translate)
        self.ctrl_panel.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")

        # アクション
        action_frame = ctk.CTkFrame(self.ctrl_panel, fg_color="transparent")
        action_frame.pack(fill="x", padx=5, pady=5)
        self.btn_translate = ctk.CTkButton(action_frame, text="Translate (API)", command=self.run_translation, fg_color="green", height=40)
        self.btn_translate.pack(side="left", expand=True, fill="x", padx=5)
        self.btn_capture = ctk.CTkButton(action_frame, text="Capture Only", command=self.capture_only, fg_color="#3a7ebf", height=40)
        self.btn_capture.pack(side="left", expand=True, fill="x", padx=5)

        # ROI
        roi_container = ctk.CTkFrame(self.ctrl_panel, fg_color="transparent")
        roi_container.pack(fill="x", padx=5, pady=5)
        for i in range(5):
            roi_slot = ctk.CTkFrame(roi_container)
            roi_slot.pack(side="left", expand=True, fill="x", padx=2)
            ctk.CTkSwitch(roi_slot, text=f"ROI {i+1}", variable=self.rois[i]["active"]).pack(pady=2)
            ctk.CTkButton(roi_slot, text="Set", width=50, height=24, command=lambda idx=i: self.start_roi_selection(idx)).pack(pady=2)
            self.rois[i]["label"] = ctk.CTkLabel(roi_slot, text="Not Set", font=("", 10))
            self.rois[i]["label"].pack()

        # 設定
        settings_frame = ctk.CTkFrame(self.ctrl_panel, fg_color="transparent")
        settings_frame.pack(fill="x", padx=5, pady=5)
        
        # 言語
        ctk.CTkLabel(settings_frame, text="Lang:").pack(side="left", padx=5)
        self.lang_button = ctk.CTkButton(settings_frame, text="ja", command=self.show_lang_menu, width=60)
        self.lang_button.pack(side="left", padx=5)
        self.lang_popup = tk.Menu(self, tearoff=0)
        for code in self.available_langs:
            self.lang_popup.add_command(label=code, command=lambda c=code: self.change_lang(c))

        # フォント
        ctk.CTkLabel(settings_frame, text="Font:").pack(side="left", padx=(10, 5))
        self.font_button = ctk.CTkButton(settings_frame, text=self.default_font_name, command=self.show_font_menu, width=120)
        self.font_button.pack(side="left", padx=5)
        self.font_popup = tk.Menu(self, tearoff=0)
        for name in self.fonts_dict.keys(): self.font_popup.add_command(label=name, command=lambda n=name: self.change_font(n))
        
        self.switch_overlay = ctk.CTkSwitch(settings_frame, text="Show Overlay", command=self.toggle_overlay)
        self.switch_overlay.select()
        self.switch_overlay.pack(side="left", padx=10)

        ctk.CTkLabel(settings_frame, text="OCR:").pack(side="left", padx=(10, 5))
        self.ocr_seg = ctk.CTkSegmentedButton(settings_frame, values=["google", "tesseract"], 
                                             command=self.change_ocr_engine)
        self.ocr_seg.set("google")
        self.ocr_seg.pack(side="left", padx=5)

        # Tesseractモデル選択
        self.tess_model_button = ctk.CTkButton(settings_frame, text="jpn+eng", command=self.show_tess_model_menu, width=80)
        # 初期状態では非表示にする（OCRがtesseractの時だけ意味があるため）
        # self.tess_model_button.pack(side="left", padx=5) # あとでchange_ocr_engineで制御
        
        self.tess_model_popup = tk.Menu(self, tearoff=0)
        
        self.btn_keep = ctk.CTkButton(settings_frame, text="Keep This", command=self.keep_current, fg_color="#1f538d")
        self.btn_keep.pack(side="right", padx=10)

        # 利用状況表示
        self.lbl_usage = ctk.CTkLabel(self.tab_translate, text="Usage: Loading...", font=("", 12))
        self.lbl_usage.grid(row=3, column=0, padx=20, pady=5, sticky="w")

    def setup_library_tab(self):
        self.tab_library.grid_columnconfigure(1, weight=1)
        self.tab_library.grid_rowconfigure(0, weight=1)
        self.list_frame = ctk.CTkFrame(self.tab_library, width=250)
        self.list_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(self.list_frame, text="Saved Items", font=("", 16, "bold")).pack(pady=10)
        self.scroll_list = ctk.CTkScrollableFrame(self.list_frame)
        self.scroll_list.pack(expand=True, fill="both", padx=5, pady=5)
        self.view_frame = ctk.CTkFrame(self.tab_library)
        self.view_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.lbl_lib_image = ctk.CTkLabel(self.view_frame, text="Select an item")
        self.lbl_lib_image.pack(expand=True, fill="both", padx=10, pady=10)
        self.meta_text = ctk.CTkTextbox(self.view_frame, height=150)
        self.meta_text.pack(fill="x", padx=10, pady=10)
        lib_ctrl = ctk.CTkFrame(self.view_frame)
        lib_ctrl.pack(fill="x", padx=10, pady=(0, 10))
        self.switch_lib_overlay = ctk.CTkSwitch(lib_ctrl, text="Show Overlay", command=self.render_library_image)
        self.switch_lib_overlay.select()
        self.switch_lib_overlay.pack(side="left", padx=10)
        ctk.CTkButton(lib_ctrl, text="Refresh List", command=self.refresh_library_list, width=100).pack(side="right", padx=10)

    # --- Actions ---
    def show_lang_menu(self):
        """言語選択メニューをボタンの右端に表示する"""
        x = self.lang_button.winfo_rootx() + self.lang_button.winfo_width()
        y = self.lang_button.winfo_rooty()
        self.lang_popup.post(x, y)

    def change_lang(self, lang_code):
        """言語を変更し、ボタンのテキストを更新する"""
        self.lang_button.configure(text=lang_code)
        self.selected_lang_code = lang_code
        if self.current_data and self.last_action == "translate":
            self.run_translation()

    def change_ocr_engine(self, engine):
        self.selected_ocr_engine = engine
        if engine == "tesseract":
            self.tess_model_button.pack(side="left", padx=5, after=self.ocr_seg)
        else:
            self.tess_model_button.pack_forget()

    def show_tess_model_menu(self):
        """tessdataディレクトリ内のモデルをチェックボックスで選択できるポップアップを表示する"""
        popup = ctk.CTkToplevel(self)
        popup.title("Select OCR Models")
        popup.geometry("300x400")
        popup.attributes("-topmost", True)
        
        # モデル一覧の取得
        models = ["jpn", "eng"]
        tessdata_dir = translator.TESSDATA_DIR
        if os.path.exists(tessdata_dir):
            for f in os.listdir(tessdata_dir):
                if f.endswith(".traineddata"):
                    m = f.replace(".traineddata", "")
                    if m not in models:
                        models.append(m)
        
        current_selected = self.selected_tess_model.split("+")
        
        ctk.CTkLabel(popup, text="Select Models (Multi)", font=("", 14, "bold")).pack(pady=10)
        
        scroll = ctk.CTkScrollableFrame(popup)
        scroll.pack(expand=True, fill="both", padx=10, pady=5)
        
        checkboxes = {}
        for m in models:
            var = tk.BooleanVar(value=(m in current_selected))
            cb = ctk.CTkCheckBox(scroll, text=m, variable=var)
            cb.pack(anchor="w", pady=2)
            checkboxes[m] = var
            
        def apply_selection():
            selected = [m for m, var in checkboxes.items() if var.get()]
            if not selected:
                selected = ["jpn"] # デフォルト
            new_model_str = "+".join(selected)
            self.selected_tess_model = new_model_str
            self.tess_model_button.configure(text=new_model_str)
            popup.destroy()
            if self.current_data and self.selected_ocr_engine == "tesseract":
                self.run_translation()
                
        ctk.CTkButton(popup, text="Apply", command=apply_selection).pack(pady=10)

    def change_tess_model(self, model_name):
        # このメソッドは互換性のために残すか、削除しても良い（現在は show_tess_model_menu 内で完結）
        self.selected_tess_model = model_name
        self.tess_model_button.configure(text=model_name)
        if self.current_data and self.selected_ocr_engine == "tesseract":
            self.run_translation()

    def run_translation(self):
        self.btn_translate.configure(state="disabled", text="Calling API...")
        self.update_idletasks()
        image_paths = image_manager.get_images_from_directory(self.screenshot_dir)
        if image_paths:
            latest_path = image_paths[0]
            try:
                orig_img = Image.open(latest_path).convert("RGB")
                active_rois = [r["coords"] for r in self.rois if r["active"].get() and r["coords"]]
                trans_img, meta = translator.translate_image(latest_path, font_path=self.selected_font_path, 
                                                           rois=active_rois, target_lang=self.selected_lang_code,
                                                           engine=self.selected_ocr_engine,
                                                           ocr_lang=self.selected_tess_model)
                self.current_data = (trans_img, orig_img, meta)
                self.last_action = "translate"
                self.render_translate_image()
                self.update_usage_display()
            except Exception as e: messagebox.showerror("Error", f"API Error: {e}")
        self.btn_translate.configure(state="normal", text="Translate (API)")

    def update_usage_display(self):
        api_key = translator.get_api_key()
        stats = usage_tracker.get_current_usage(api_key)
        v = stats["vision_units"]
        t = stats["translation_chars"]
        month = stats["month"]
        key_id = stats["key_id"]
        self.lbl_usage.configure(text=f"[{month}] Key:{key_id} | Vision {v}/1000, Trans {t} chars")

    def capture_only(self):
        image_paths = image_manager.get_images_from_directory(self.screenshot_dir)
        if image_paths:
            latest_path = image_paths[0]
            try:
                orig_img = Image.open(latest_path).convert("RGB")
                self.current_data = (orig_img, orig_img, [])
                self.last_action = "capture"
                self.render_translate_image()
                self.btn_capture.configure(fg_color="orange", text="Captured!")
                self.after(1000, lambda: self.btn_capture.configure(fg_color="#3a7ebf", text="Capture Only"))
            except Exception as e: messagebox.showerror("Error", f"Capture failed: {e}")

    def keep_current(self):
        if not self.current_data: return
        t, o, m = self.current_data
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base = f"keep_{timestamp}"
        try:
            o.save(os.path.join(self.keep_dir, f"{base}_orig.png"))
            data = {"timestamp": timestamp, "font": self.font_button.cget("text"), 
                    "original_file": f"{base}_orig.png", "type": self.last_action, "lang": self.selected_lang_code,
                    "ocr_engine": self.selected_ocr_engine, "tess_model": self.selected_tess_model}
            if self.last_action == "translate":
                t.save(os.path.join(self.keep_dir, f"{base}_trans.png"))
                data["translated_file"] = f"{base}_trans.png"
                # m (metadata) には既に translator.py で "translated" キーが追加されている
                data["blocks"] = [{"box": i["box"], "original": i["text"], "translated": i.get("translated", "")} for i in m]
            else:
                data["translated_file"] = None; data["blocks"] = []
            with open(os.path.join(self.keep_dir, f"{base}.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.btn_keep.configure(fg_color="orange", text="Saved!")
            self.after(1000, lambda: self.btn_keep.configure(fg_color="#1f538d", text="Keep This"))
        except Exception as e: messagebox.showerror("Error", f"Save failed: {e}")

    # --- UI Helpers ---
    def start_roi_selection(self, idx):
        if not self.current_data: 
            messagebox.showinfo("Hint", "Load an image first (Capture/Translate) to set ROI.")
            return
        self.selecting_roi_idx = idx; self.canvas.configure(cursor="cross")

    def on_selection_start(self, e):
        if self.selecting_roi_idx == -1: return
        self.selection_start = (e.x, e.y)
        if self.current_selection_rect: self.canvas.delete(self.current_selection_rect)
        self.current_selection_rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)

    def on_selection_drag(self, e):
        if self.selecting_roi_idx != -1 and self.selection_start:
            self.canvas.coords(self.current_selection_rect, self.selection_start[0], self.selection_start[1], e.x, e.y)

    def on_selection_end(self, e):
        if self.selecting_roi_idx == -1 or not self.selection_start: return
        x1, y1, x2, y2 = self.selection_start[0], self.selection_start[1], e.x, e.y
        orig_pil = self.current_data[1]
        iw, ih = orig_pil.size; vw, vh = self.canvas.winfo_width(), self.canvas.winfo_height()
        r = min(vw / iw, vh / ih); ox, oy = (vw - iw * r) / 2, (vh - ih * r) / 2
        rx1 = int((min(x1, x2) - ox) / r); ry1 = int((min(y1, y2) - oy) / r)
        rx2 = int((max(x1, x2) - ox) / r); ry2 = int((max(y1, y2) - oy) / r)
        rx1, rx2 = max(0, min(rx1, iw)), max(0, min(rx2, iw))
        ry1, ry2 = max(0, min(ry1, ih)), max(0, min(ry2, ih))
        if rx2 - rx1 > 5:
            self.rois[self.selecting_roi_idx]["coords"] = [rx1, ry1, rx2 - rx1, ry2 - ry1]
            self.rois[self.selecting_roi_idx]["active"].set(True)
            self.rois[self.selecting_roi_idx]["label"].configure(text=f"{rx2 - rx1}x{ry2 - ry1}")
        self.selecting_roi_idx = -1; self.canvas.configure(cursor=""); self.render_translate_image()

    def on_tab_change(self):
        if self.tabview.get() == "Library": self.refresh_library_list()

    def refresh_library_list(self):
        for w in self.scroll_list.winfo_children(): w.destroy()
        files = sorted(glob.glob(os.path.join(self.keep_dir, "*.json")), reverse=True)
        for f in files:
            ts = os.path.basename(f).replace("keep_", "").replace(".json", "")
            btn = ctk.CTkButton(self.scroll_list, text=ts, fg_color="transparent", anchor="w", 
                               text_color=("#000000", "#FFFFFF"), command=lambda p=f: self.load_library_item(p))
            btn.pack(fill="x", pady=2)

    def load_library_item(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
            orig = Image.open(os.path.join(self.keep_dir, data["original_file"])).convert("RGB")
            trans = Image.open(os.path.join(self.keep_dir, data["translated_file"])).convert("RGB") if data.get("translated_file") else None
            self.selected_lib_data = (trans, orig, data)
            self.meta_text.delete("1.0", "end")
            meta_info = f"Type: {data.get('type')}\nLang: {data.get('lang')}\nFont: {data.get('font')}\n"
            if data.get("ocr_engine"):
                meta_info += f"OCR: {data.get('ocr_engine')}"
                if data.get("ocr_engine") == "tesseract" and data.get("tess_model"):
                    meta_info += f" ({data.get('tess_model')})"
                meta_info += "\n"
            meta_info += "\n"
            self.meta_text.insert("end", meta_info)
            for i, b in enumerate(data.get("blocks", [])):
                self.meta_text.insert("end", f"[{i+1}] {b['original']}\n    -> {b['translated']}\n\n")
            self.render_library_image()
        except: messagebox.showerror("Error", "Load failed")

    def render_library_image(self):
        if self.selected_lib_data:
            t, o, d = self.selected_lib_data
            self._show_pil_on_label(t if (self.switch_lib_overlay.get() and t) else o, self.lbl_lib_image, self.view_frame, 200)

    def _show_pil_on_label(self, pil, lbl, container, oy=0):
        vw, vh = container.winfo_width() - 40, container.winfo_height() - oy
        if vw <= 100: vw, vh = 800, 600
        iw, ih = pil.size; r = min(vw / iw, vh / ih)
        lbl.configure(image=ctk.CTkImage(light_image=pil, dark_image=pil, size=(int(iw * r), int(ih * r))), text="")

    def on_resize(self, e):
        if e.widget == self:
            self.after(100, self.render_translate_image); self.after(100, self.render_library_image)

    def render_translate_image(self):
        if not self.current_data: return
        t, o, _ = self.current_data; pil = t if self.show_overlay else o
        vw, vh = self.canvas.winfo_width(), self.canvas.winfo_height()
        if vw <= 100: vw, vh = 800, 600
        iw, ih = pil.size; r = min(vw / iw, vh / ih); nw, nh = int(iw * r), int(ih * r)
        self.tk_img = ImageTk.PhotoImage(pil.resize((nw, nh), Image.Resampling.LANCZOS))
        self.canvas.delete("all"); self.canvas.create_image(vw/2, vh/2, image=self.tk_img, anchor="center")
        ox, oy = (vw - nw)/2, (vh - nh)/2
        for i, roi in enumerate(self.rois):
            if roi["active"].get() and roi["coords"]:
                rx, ry, rw, rh = roi["coords"]
                self.canvas.create_rectangle(rx*r+ox, ry*r+oy, (rx+rw)*r+ox, (ry+rh)*r+oy, outline="cyan", width=2)
                self.canvas.create_text(rx*r+ox+5, ry*r+oy+5, text=f"ROI {i+1}", fill="cyan", anchor="nw")

    def browse_directory(self):
        p = filedialog.askdirectory(initialdir=self.screenshot_dir)
        if p: self.screenshot_dir = p; self.lbl_dir.configure(text=f"Target Dir: {p}")

    def show_font_menu(self): self.font_popup.post(self.font_button.winfo_rootx() + self.font_button.winfo_width(), self.font_button.winfo_rooty())
    def change_font(self, n): self.font_button.configure(text=n); self.selected_font_path = self.fonts_dict.get(n); self.render_translate_image()
    def toggle_overlay(self): self.show_overlay = self.switch_overlay.get(); self.render_translate_image()

if __name__ == "__main__":
    app = CyclicTranslatorApp(); app.mainloop()
