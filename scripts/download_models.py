"""下载本地模型权重（BGE-M3）辅助脚本。

优先使用国内镜像源（ModelScope）高速下载，失败时可回退 HuggingFace。
上线前在宿主机运行一次即可就绪：
    python scripts/download_models.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 BGE-M3 模型权重到本地")
    parser.add_argument(
        "--target-dir",
        default="./models/bge-m3",
        help="目标保存路径（默认 ./models/bge-m3）",
    )
    parser.add_argument(
        "--source",
        choices=["modelscope", "huggingface"],
        default="modelscope",
        help="下载源：modelscope（国内极速推荐）或 huggingface",
    )
    args = parser.parse_args()

    target_path = Path(args.target_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    print(f"📥 开始下载 BAAI/bge-m3 到 {target_path} ...")

    if args.source == "modelscope":
        try:
            from modelscope import snapshot_download
        except ImportError:
            print("⚠️ 未检测到 modelscope 库，正在安装: pip install modelscope ...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "modelscope"])
            from modelscope import snapshot_download

        model_dir = snapshot_download("BAAI/bge-m3", local_dir=str(target_path))
        print(f"✅ 下载完成！权重已保存在: {model_dir}")
    else:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            print("⚠️ 未检测到 huggingface_hub 库，正在安装: pip install huggingface_hub ...")
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub"])
            from huggingface_hub import snapshot_download

        model_dir = snapshot_download(repo_id="BAAI/bge-m3", local_dir=str(target_path))
        print(f"✅ 下载完成！权重已保存在: {model_dir}")


if __name__ == "__main__":
    main()
