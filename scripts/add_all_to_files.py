"""自动为源文件添加 __all__ 列表 — 基于 __init__.py 的导出关系。

功能：
    1. 解析 __init__.py 的导入语句（from .module import XXX）
    2. 将导出的符号归类到对应的源文件
    3. 在文件末尾添加 __all__ = [...] 列表

使用示例：
    python scripts/add_all_to_files.py  # 自动处理所有模块
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set

# ============================================================
# 配置区
# ============================================================

# 需要处理的模块（按顺序）
MODULES_TO_PROCESS = [
    "core",
    "generation",
    "retriever",
    "utils",
    # "ingestion",   # 取消注释可启用
    # "evaluation",  # 取消注释可启用
]

# ============================================================
# 核心功能
# ============================================================

def parse_init_imports(init_path: Path) -> Dict[str, Set[str]]:
    """解析 __init__.py 的导入语句，提取每个文件导出的符号。
    
    Args:
        init_path: __init__.py 文件路径
        
    Returns:
        字典 {文件名: 导出的符号集合}
        例如: {"settings.py": {"Settings"}, "factories.py": {"create_rag_chain", ...}}
    """
    if not init_path.exists():
        return {}
    
    try:
        content = init_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        print(f"  ❌ Failed to parse {init_path}: {e}")
        return {}
    
    file_imports = {}
    
    for node in ast.walk(tree):
        # 查找 from .module import XXX 语句
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module:  # relative import with level=1
                module_name = node.module
                file_name = f"{module_name}.py"
                
                # 提取导入的符号
                imported_names = set()
                for alias in node.names:
                    # 使用 asname 或 name
                    name = alias.asname if alias.asname else alias.name
                    if not name.startswith('_'):  # 跳过私有成员
                        imported_names.add(name)
                
                if imported_names:
                    file_imports[file_name] = imported_names
    
    return file_imports


def check_file_has_all(file_path: Path) -> tuple[bool, int]:
    """检查文件是否已经有 __all__ 定义，并返回其位置。
    
    Args:
        file_path: .py 文件路径
        
    Returns:
        (has_all, line_number) - 是否有 __all__ 及其行号（1-based）
    """
    if not file_path.exists():
        return False, 0
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        for i, line in enumerate(lines, 1):
            # 匹配 __all__ = [ 或 __all__ = [
            if re.match(r'^\s*__all__\s*=', line):
                return True, i
        
        return False, 0
    except Exception:
        return False, 0


def add_all_to_file(file_path: Path, symbols: Set[str]) -> bool:
    """为文件添加或更新 __all__ 列表。
    
    Args:
        file_path: .py 文件路径
        symbols: 要导出的符号集合
        
    Returns:
        True 如果成功添加/更新
    """
    if not file_path.exists():
        return False
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        # 检查是否已有 __all__
        has_all, all_line = check_file_has_all(file_path)
        
        if has_all:
            # 删除旧的 __all__ 块（找到结束的 ]）
            new_lines = []
            skip_mode = False
            bracket_count = 0
            
            for i, line in enumerate(lines):
                line_num = i + 1
                
                if line_num == all_line:
                    # 开始跳过 __all__ 块
                    skip_mode = True
                    bracket_count = 0
                
                if skip_mode:
                    # 计算括号匹配
                    bracket_count += line.count('[') - line.count(']')
                    
                    # 当括号匹配完成（遇到结束的 ]）
                    if bracket_count <= 0 and ']' in line:
                        skip_mode = False
                        # 跳过这一行（结束的 ]）
                        continue
                else:
                    new_lines.append(line)
            
            # 清理前导/尾随空行（保持一个空行分隔）
            while new_lines and new_lines[-1].strip() == '':
                new_lines.pop()
            
            content = '\n'.join(new_lines)
            print(f"  🔄 Removed old __all__ from {file_path.name} (line {all_line})")
        
        # 确保文件末尾有换行，且有两个空行分隔
        content = content.rstrip() + '\n\n'
        
        # 排序符号（保持一致性）
        sorted_symbols = sorted(symbols)
        
        # 生成 __all__ 字符串
        all_str = '__all__ = [\n'
        for symbol in sorted_symbols:
            all_str += f'    "{symbol}",\n'
        all_str += ']\n'
        
        # 追加到文件末尾
        content += all_str
        
        # 写回文件
        file_path.write_text(content, encoding="utf-8")
        
        action = "Updated" if has_all else "Added"
        print(f"  ✅ {action} __all__ in {file_path.name} ({len(symbols)} symbols)")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to update {file_path}: {e}")
        return False


def process_module(module_dir: Path) -> int:
    """处理单个模块的所有文件。
    
    Args:
        module_dir: 模块目录（如 src/core）
        
    Returns:
        成功添加的文件数量
    """
    init_file = module_dir / "__init__.py"
    if not init_file.exists():
        print(f"⚠️  Warning: {module_dir.name} has no __init__.py")
        return 0
    
    print(f"\n📦 Processing module: {module_dir.name}")
    
    # 解析 __init__.py 的导入
    file_imports = parse_init_imports(init_file)
    
    if not file_imports:
        print(f"  ⚠️  No imports found in __init__.py")
        return 0
    
    # 处理每个文件
    success_count = 0
    for file_name, symbols in file_imports.items():
        file_path = module_dir / file_name
        
        if add_all_to_file(file_path, symbols):
            success_count += 1
    
    return success_count


# ============================================================
# 主流程
# ============================================================

def main():
    """主函数：批量为所有模块的源文件添加 __all__。"""
    
    # 路径精确定位
    SCRIPT_DIR = Path(__file__).parent
    PROJECT_ROOT = SCRIPT_DIR.parent
    SRC_DIR = PROJECT_ROOT / "src"
    
    if not SRC_DIR.exists():
        print(f"❌ Error: {SRC_DIR} not found.")
        return
    
    print("=" * 60)
    print("🔧 Auto-adding __all__ to source files")
    print("=" * 60)
    
    total_success = 0
    total_modules = 0
    
    for module_name in MODULES_TO_PROCESS:
        module_dir = SRC_DIR / module_name
        
        if not module_dir.exists():
            print(f"\n⚠️  Warning: {module_dir} not found, skipping.")
            continue
        
        success_count = process_module(module_dir)
        total_success += success_count
        total_modules += 1
    
    print("\n" + "=" * 60)
    print(f"🎉 Done! Updated {total_success} files across {total_modules} modules.")
    print("=" * 60)


if __name__ == "__main__":
    main()
