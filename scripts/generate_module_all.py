"""增强版 __all__ 生成脚本 — 基于模块内部导入关系分析。

功能：
    1. 扫描模块内所有文件的相对导入（from .module import XXX）
    2. 构建模块内部的依赖关系图
    3. 为每个文件生成完整的模块级 __all__（包括被其他文件引用的接口）
    4. 保持 __init__.py 中定义的包级公共 API 顺序

设计原则：
    - 文件的 __all__ = 模块级公共 API（包内部 + 包外部都可见）
    - __init__.py 的 __all__ = 包级公共 API（只导出给外部使用的，是文件 __all__ 的子集）
    - 两者的关系：包级 API ⊆ 模块级 API

使用示例：
    python scripts/generate_module_all.py  # 处理所有配置的模块
    python scripts/generate_module_all.py --module workflow  # 只处理 workflow 模块
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ============================================================
# 配置区
# ============================================================

# 需要处理的模块（按顺序）
MODULES_TO_PROCESS = [
    "core",
    # "generation",
    "retriever",
    "utils",
    "workflow",
    # "ingestion",   # 取消注释可启用
    # "evaluation",  # 取消注释可启用
]

# ============================================================
# 核心功能：导入关系分析
# ============================================================

def extract_file_exports(file_path: Path) -> List[str]:
    """从文件的现有 __all__ 中提取导出符号列表。
    
    Args:
        file_path: .py 文件路径
        
    Returns:
        导出符号列表（保持原始顺序）
    """
    if not file_path.exists():
        return []
    
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception:
        return []
    
    # 查找 __all__ 赋值语句
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    # 提取列表中的字符串元素
                    if isinstance(node.value, ast.List):
                        api_names = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                api_names.append(elt.value)
                        return api_names
    
    return []



def scan_module_imports(module_dir: Path, src_dir: Path) -> Dict[str, List[Tuple[str, List[str]]]]:
    """扫描模块内所有文件的导入（支持绝对导入和相对导入），构建依赖关系图。
    
    性能优化：
        - 只解析每个文件一次
        - 使用 ast.iter_child_nodes() 而非 ast.walk()，只扫描顶层导入语句
    
    Args:
        module_dir: 模块目录（如 src/workflow）
        src_dir: src 目录路径（用于解析绝对导入）
        
    Returns:
        字典 {目标文件: [(源文件, [导入的符号]), ...]}
        例如: {"nodes.py": [("routing.py", ["classify_intent"]), ...]}
    """
    dependency_graph = {}
    module_name = module_dir.name
    
    # 扫描所有 .py 文件（排除 __init__.py）
    py_files = [f for f in module_dir.iterdir() if f.is_file() and f.name.endswith('.py') and f.name != '__init__.py']
    
    for source_file in py_files:
        try:
            content = source_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except Exception:
            continue
        
        # ✅ 性能优化：只扫描顶层节点（import 语句通常在模块级别）
        for node in ast.iter_child_nodes(tree):
            # 只关注导入语句
            if not isinstance(node, ast.ImportFrom):
                continue
            
            target_module = None
            
            # 方式 1：相对导入 from .module import XXX
            if node.level == 1 and node.module:
                target_module = node.module
            
            # 方式 2：绝对导入 from src.workflow.module import XXX
            elif node.level == 0 and node.module:
                # 检查是否以 src.{module_name}. 开头
                prefix = f"src.{module_name}."
                if node.module.startswith(prefix):
                    # 提取模块名：src.workflow.routing -> routing
                    target_module = node.module[len(prefix):]
            
            if target_module:
                target_file = f"{target_module}.py"
                imported_names = [alias.name for alias in node.names if not alias.name.startswith('_')]
                
                if imported_names:
                    if target_file not in dependency_graph:
                        dependency_graph[target_file] = []
                    dependency_graph[target_file].append((source_file.name, imported_names))
    
    return dependency_graph


def compute_complete_exports(
    file_path: Path,
    dependency_graph: Dict[str, List[Tuple[str, List[str]]]],
    init_imports: Dict[str, List[str]]
) -> List[str]:
    """计算文件的完整导出列表（模块级公共 API）。
    
    策略：
        1. 收集所有被其他文件导入的符号（保持导入顺序）
        2. 合并 __init__.py 中导入的符号（包级公共 API）
        3. 去重并保持合理顺序：
           - 优先保持 __init__.py 的顺序（包级 API）
           - 然后按首次出现的顺序添加内部使用的符号
    
    Args:
        file_path: 目标文件路径
        dependency_graph: 依赖关系图
        init_imports: __init__.py 中的导入（保持顺序）
        
    Returns:
        完整的导出符号列表
    """
    file_name = file_path.name
    
    # 第1步：收集所有被其他文件导入的符号（保持首次出现的顺序）
    internal_usage = []
    seen_internal = set()
    if file_name in dependency_graph:
        for source_file, imported_names in dependency_graph[file_name]:
            for name in imported_names:
                if name not in seen_internal:
                    internal_usage.append(name)
                    seen_internal.add(name)
    
    # 第2步：获取 __init__.py 中导入的符号（包级 API）
    init_exports = init_imports.get(file_name, [])
    init_exports_set = set(init_exports)
    
    # 第3步：合并，保持顺序
    # 策略：先放 __init__.py 的（包级 API），再放内部使用的（按首次出现顺序）
    complete_exports = []
    seen = set()
    
    # 优先：__init__.py 的导入顺序
    for name in init_exports:
        if name not in seen:
            complete_exports.append(name)
            seen.add(name)
    
    # 其次：内部使用的符号（按首次出现顺序，而非字母序）
    for name in internal_usage:
        if name not in seen:
            complete_exports.append(name)
            seen.add(name)
    
    return complete_exports


def parse_init_imports(init_path: Path) -> Dict[str, List[str]]:
    """解析 __init__.py 的导入语句，提取每个文件导出的符号（保持原始顺序）。
    
    Args:
        init_path: __init__.py 文件路径
        
    Returns:
        字典 {文件名: 导出的符号列表}（保持 __init__.py 中的导入顺序）
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
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module:
                module_name = node.module
                file_name = f"{module_name}.py"
                
                imported_names = []
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    if not name.startswith('_'):
                        imported_names.append(name)
                
                if imported_names:
                    file_imports[file_name] = imported_names
    
    return file_imports


def add_all_to_file(file_path: Path, symbols: List[str]) -> bool:
    """为文件添加或更新 __all__ 列表。
    
    Args:
        file_path: .py 文件路径
        symbols: 要导出的符号列表
        
    Returns:
        True 如果成功添加/更新
    """
    if not file_path.exists():
        return False
    
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        # 检查是否已有 __all__
        has_all = False
        all_line = 0
        for i, line in enumerate(lines, 1):
            if re.match(r'^\s*__all__\s*=', line):
                has_all = True
                all_line = i
                break
        
        if has_all:
            # 删除旧的 __all__ 块
            new_lines = []
            skip_mode = False
            bracket_count = 0
            
            for i, line in enumerate(lines):
                line_num = i + 1
                
                if line_num == all_line:
                    skip_mode = True
                    bracket_count = 0
                
                if skip_mode:
                    bracket_count += line.count('[') - line.count(']')
                    if bracket_count <= 0 and ']' in line:
                        skip_mode = False
                        continue
                else:
                    new_lines.append(line)
            
            # 清理尾随空行
            while new_lines and new_lines[-1].strip() == '':
                new_lines.pop()
            
            content = '\n'.join(new_lines)
            print(f"  🔄 Removed old __all__ from {file_path.name}")
        
        # 确保文件末尾有换行
        content = content.rstrip() + '\n\n'
        
        # 生成新的 __all__
        all_str = '__all__ = [\n'
        for symbol in symbols:
            all_str += f'    "{symbol}",\n'
        all_str += ']\n'
        
        content += all_str
        file_path.write_text(content, encoding="utf-8")
        
        action = "Updated" if has_all else "Added"
        print(f"  ✅ {action} __all__ in {file_path.name} ({len(symbols)} symbols)")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to update {file_path}: {e}")
        return False


def process_module(module_dir: Path, src_dir: Path) -> int:
    """处理单个模块的所有文件。
    
    Args:
        module_dir: 模块目录（如 src/workflow）
        src_dir: src 目录路径
        
    Returns:
        成功添加的文件数量
    """
    init_file = module_dir / "__init__.py"
    if not init_file.exists():
        print(f"⚠️  Warning: {module_dir.name} has no __init__.py")
        return 0
    
    print(f"\n📦 Processing module: {module_dir.name}")
    
    # 第1步：解析 __init__.py 的导入（包级 API）
    init_imports = parse_init_imports(init_file)
    print(f"  📋 Found {len(init_imports)} files in __init__.py imports")
    
    # 第2步：扫描模块内部导入关系（支持绝对导入和相对导入）
    dependency_graph = scan_module_imports(module_dir, src_dir)
    print(f"  🔍 Found dependencies for {len(dependency_graph)} files")
    
    # 第3步：为每个文件生成完整的 __all__
    py_files = [f for f in module_dir.iterdir() if f.is_file() and f.name.endswith('.py') and f.name != '__init__.py']
    
    success_count = 0
    for py_file in sorted(py_files):
        # 计算完整导出
        complete_exports = compute_complete_exports(py_file, dependency_graph, init_imports)
        
        if complete_exports:
            if add_all_to_file(py_file, complete_exports):
                success_count += 1
        else:
            print(f"  ⏭️  Skipped {py_file.name} (no exports)")
    
    return success_count


# ============================================================
# 主流程
# ============================================================

def main():
    """主函数：批量为所有模块的源文件生成完整的 __all__。"""
    
    # 路径定位
    SCRIPT_DIR = Path(__file__).parent
    PROJECT_ROOT = SCRIPT_DIR.parent
    SRC_DIR = PROJECT_ROOT / "src"
    
    if not SRC_DIR.exists():
        print(f"❌ Error: {SRC_DIR} not found.")
        return
    
    print("=" * 70)
    print("🔧 Enhanced __all__ Generator (Module-Level API Analysis)")
    print("=" * 70)
    
    total_success = 0
    total_modules = 0
    
    for module_name in MODULES_TO_PROCESS:
        module_dir = SRC_DIR / module_name
        
        if not module_dir.exists():
            print(f"\n⚠️  Warning: {module_dir} not found, skipping.")
            continue
        
        success_count = process_module(module_dir, SRC_DIR)
        total_success += success_count
        total_modules += 1
    
    print("\n" + "=" * 70)
    print(f"🎉 Done! Updated {total_success} files across {total_modules} modules.")
    print("=" * 70)


if __name__ == "__main__":
    main()
