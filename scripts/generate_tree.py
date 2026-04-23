# scripts/generate_tree.py
import os
from pathlib import Path

# ===== 配置区域：按需修改 =====
INCLUDE_DIRS = ["src", "tests", "data"]  # 只展示这些目录，为空则全部展示
EXCLUDE_DIRS = {
    "__pycache__", "langchain_docs_separated", "langchain_python_separated",
    
}
EXCLUDE_FILES = {".DS_Store", "*.pyc", "*.log"}  # 支持通配符
# =============================

def should_include(path: Path, root: Path) -> bool:
    """判断路径是否应该包含在树中。"""
    # 排除隐藏文件和目录
    if path.name.startswith(".") and path.name not in (".env", ".gitignore"):
        return False
    # 排除指定目录
    if path.is_dir() and path.name in EXCLUDE_DIRS:
        return False
    # 排除指定文件（支持简单通配符）
    if path.is_file():
        for pattern in EXCLUDE_FILES:
            if pattern.startswith("*") and path.suffix == pattern[1:]:
                return False
            elif path.name == pattern:
                return False
    # 如果指定了包含目录，只处理这些目录下的内容
    if INCLUDE_DIRS and path != root:
        rel_path = path.relative_to(root)
        top_dir = rel_path.parts[0] if rel_path.parts else ""
        if top_dir not in INCLUDE_DIRS:
            return False
    return True

def tree(dir_path: Path, prefix: str = "", root: Path = None) -> str:
    if root is None:
        root = dir_path
    lines = []
    contents = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name))
    filtered = [p for p in contents if should_include(p, root)]
    for i, path in enumerate(filtered):
        connector = "└── " if i == len(filtered) - 1 else "├── "
        lines.append(f"{prefix}{connector}{path.name}")
        if path.is_dir():
            extension = "    " if i == len(filtered) - 1 else "│   "
            lines.append(tree(path, prefix + extension, root))
    return "\n".join(lines)

if __name__ == "__main__":
    root = Path(__file__).parent.parent
    output = f"{root.name}/\n{tree(root)}"
    # 在末尾追加一行 ... （或在特定位置插入）
    print(output)