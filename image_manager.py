import os
import glob

def get_images_from_directory(dir_path):
    """
    指定ディレクトリ内の全画像ファイルのパスを取得する。
    """
    if not os.path.isdir(dir_path):
        return []
    
    # 一般的な画像拡張子
    extensions = ['*.png', '*.jpg', '*.jpeg', '*.bmp', '*.gif']
    image_paths = []
    
    for ext in extensions:
        # 大文字小文字の両方を探す
        image_paths.extend(glob.glob(os.path.join(dir_path, ext)))
        image_paths.extend(glob.glob(os.path.join(dir_path, ext.upper())))
    
    # 更新日時順にソート（新しい順）
    image_paths.sort(key=os.path.getmtime, reverse=True)
    
    return image_paths
