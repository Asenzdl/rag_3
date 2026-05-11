"""CONTEXT_INDEX.md 自动生成脚本 — 基于 AST 分析 + 公共 API 提取。

功能：
    1. 指定模块输出顺序（可跳过某些模块）
    2. 按文件导出公共 API（从每个 .py 文件的 __all__ 提取）
    3. 提取模块职责概要（从文档字符串第一行）
    4. 按 Markdown 标题分组（模块 > 文件）
    5. 局部替换：写入 project_info/CONTEXT_INDEX.md 的特定区域

使用示例：
    python scripts/ast_test.py  # 默认写入 project_info/CONTEXT_INDEX.md
    python scripts/ast_test.py --output /path/to/file.md  # 指定输出路径
"""

import ast
import re
import sys
from pathlib import Path
from typing import List, Optional

# ============================================================
# 配置区：模块输出顺序控制
# ============================================================

# 全局开关：是否显示“职责概要”列
# True  → 表格包含职责概要列（需维护 api_summaries.yaml 或 docstring）
# False → 表格仅显示“文件 | 公共 API”两列（推荐，零维护）
SHOW_SUMMARY_COLUMN = False

# 模块输出顺序（留空则按字母顺序，设为 None 则跳过该模块）
MODULE_ORDER = [
    "src",           # src/ 根目录（app.py / run.py）
    "core",           # 核心基础设施
    # "generation",     # 生成层
    "retriever",      # 检索层
    "utils",          # 工具模块
    "workflow",       # LangGraph 工作流
    # 离线模块（跳过，不输出）
    # "ingestion",    # 取消注释可启用
    # "evaluation",   # 取消注释可启用
]

# 过滤黑名单（绝对禁止扫描）
EXCLUDE_DIRS = {".venv", "venv", "__pycache__", ".git", "build", "dist"}

# 强制索引文件白名单（即使没有 __all__ 也要出现在索引中）
FORCE_INDEX_FILES = {
    "app.py",     # CLI 应用入口
    "run.py",     # 程序启动入口
}

# 标题说明段落配置（按顺序排列,每段一个字符串）
# 这些段落会插入到 "## 📦 核心模块定位表" 和第一个 "###" 之间
HEADER_SECTIONS = [
    "一行定位：文件 → 公共 API：C:类/F:函数/R:Re-export/V:变量常量",
    "- 通常无须关注的模块\n"
    "  - `src/ingestion`：数据预处理管道；离线工具\n"
    "  - `src/evaluation`：检索评估工具；离线工具\n"
    "  - `src/generation/`：RAG Chain 生成层核心 API；phase1为独立阶段"
    # 可在此处添加更多段落，例如：
    # "使用说明：...",
    # "注意事项：...",
]

# 默认职责摘要（当文件无文档字符串时使用，键为文件名）
DEFAULT_SUMMARIES = {
    "run.py": "程序启动入口。",
}

# 模块描述配置（当 __init__.py 无文档字符串时使用，键为模块名）
MODULE_DESCRIPTIONS = {
    "src/": "CLI 应用入口 + 启动脚本",  # src/ 根目录通常无 __init__.py
    # "ingestion": "数据预处理管道",  # 离线模块（当前跳过）
    # "evaluation": "检索评估工具",  # 离线模块（当前跳过）
}

# 文件类型映射（根据文件名推断角色，键为文件名）
FILE_TYPE_MAP = {
    "app.py": "CLI 交互入口：应用入口 + REPL 问答 + 会话状态管理",
    "run.py": "启动脚本：程序启动入口",
}

# ============================================================
# 核心功能：公共 API 提取
# ============================================================

def extract_all_from_file(file_path: Path) -> list[str]:
    """从 Python 文件的 __all__ 中提取公共 API 列表。
    
    Args:
        file_path: .py 文件路径
        
    Returns:
        公共 API 名称列表（如 ["Settings", "create_rag_chain", ...]）
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


def get_file_summary(file_path: Path) -> str:
    """从 Python 文件的文档字符串提取职责概要。
    
    优先级：
        1. 从 api_summaries.yaml 配置文件读取（高质量人工维护）
        2. 从 docstring 第一行提取（自动生成）
        3. 使用 DEFAULT_SUMMARIES 配置的默认值
        4. 返回 "N/A"
    
    Args:
        file_path: .py 文件路径
        
    Returns:
        职责概要字符串
    """
    # 优先级1：从配置文件读取
    PROJECT_ROOT = Path(__file__).parent.parent
    rel_path = file_path.relative_to(PROJECT_ROOT).as_posix()
    config = load_summaries_config()
    
    if rel_path in config:
        return config[rel_path]
    
    # 优先级2：从 docstring 提取
    if file_path.exists():
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            doc = ast.get_docstring(tree)
            if doc:
                # 返回第一行非空内容
                for line in doc.split('\n'):
                    line = line.strip()
                    if line:
                        return line
        except Exception:
            pass
    
    # 优先级3：使用配置的默认摘要
    filename = file_path.name
    if filename in DEFAULT_SUMMARIES:
        return DEFAULT_SUMMARIES[filename]
    
    # 优先级4：返回 N/A
    return "N/A"


def get_module_description(module_name: str, module_dir: Path) -> str:
    """从模块的 __init__.py 提取模块功能描述。
    
    策略（混合）：
        1. 优先从 __init__.py 文档字符串提取第一行
        2. 如果没有，使用 MODULE_DESCRIPTIONS 配置中的默认值
        3. 如果都没有，返回空字符串（不显示描述）
    
    Args:
        module_name: 模块名称（如 "core", "generation"）
        module_dir: 模块目录路径
        
    Returns:
        模块功能描述字符串，或空字符串
    """
    init_file = module_dir / "__init__.py"
    
    # 策略 1：从 __init__.py 文档字符串提取
    if init_file.exists():
        try:
            content = init_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
            doc = ast.get_docstring(tree)
            if doc:
                # 返回第一行非空内容
                for line in doc.split('\n'):
                    line = line.strip()
                    if line:
                        return line
        except Exception:
            pass
    
    # 策略 2：使用配置中的默认值
    if module_name in MODULE_DESCRIPTIONS:
        return MODULE_DESCRIPTIONS[module_name]
    
    # 策略 3：无描述（返回空字符串）
    return ""


def infer_file_type(file_path: Path) -> str:
    """推断文件的角色类型。
    
    Args:
        file_path: .py 文件路径
        
    Returns:
        文件类型字符串（如 "应用入口" / "启动脚本" / "库模块"）
    """
    filename = file_path.name
    
    # 优先使用配置的类型映射
    if filename in FILE_TYPE_MAP:
        return FILE_TYPE_MAP[filename]
    
    # 默认类型：库模块
    return "库模块"


def infer_symbol_type(file_path: Path, symbol_name: str) -> str:
    """推断符号类型（C:类 / F:函数 / R:Re-export / V:变量常量）。
    
    判断优先级：
        1. 本文件定义的类 → C
        2. 本文件定义的函数 → F
        3. 本文件定义的变量/常量 → V
        4. 从其他模块导入后 re-export → R
        5. 回退：根据命名约定推断
    
    Args:
        file_path: .py 文件路径
        symbol_name: 符号名称
        
    Returns:
        "C"（类）、"F"（函数）、"R"（重新导出）或 "V"（变量/常量）
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        
        # 收集所有导入的符号名（含别名）
        imported_symbols = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    # import X as Y → 记录 Y（别名）或 X（原始名）
                    imported_symbols.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_symbols.add(alias.asname or alias.name)
        
        # 优先级1-3：检查本文件定义
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == symbol_name:
                return "C"
            elif isinstance(node, ast.FunctionDef) and node.name == symbol_name:
                return "F"
            elif isinstance(node, ast.Assign):
                # 检查变量/常量赋值（如 RETRIEVE = "retrieve"）
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == symbol_name:
                        return "V"
        
        # 优先级4：检查是否是 Re-export
        if symbol_name in imported_symbols:
            return "R"
    
    except Exception:
        pass
    
    # 优先级5：回退策略：根据命名约定推断
    if symbol_name[0].isupper() and '_' not in symbol_name:
        return "C"
    else:
        return "F"


def format_api_symbols(file_path: Path, api_names: list[str]) -> str:
    """格式化公共 API 符号（带类型前缀）。
    
    Args:
        file_path: .py 文件路径（用于类型推断）
        api_names: 公共 API 名称列表
        
    Returns:
        格式化字符串，如 "`C:Settings` `F:create_rag_chain` `R:RetryableError`"
    """
    if not api_names:
        return ""
    
    symbols_with_type = []
    for api_name in api_names:
        symbol_type = infer_symbol_type(file_path, api_name)
        symbols_with_type.append(f"`{symbol_type}:{api_name}`")
    
    return " ".join(symbols_with_type)


# ============================================================
# 主流程：索引生成
# ============================================================

def generate_index_content() -> str:
    """生成索引的 Markdown 内容。
    
    Returns:
        Markdown 格式的索引字符串
    """
    
    # 路径精确定位
    SCRIPT_DIR = Path(__file__).parent
    PROJECT_ROOT = SCRIPT_DIR.parent
    SRC_DIR = PROJECT_ROOT / "src"
    
    if not SRC_DIR.exists():
        print(f"❌ Error: {SRC_DIR} not found.")
        return ""
    
    # 确定模块顺序
    if MODULE_ORDER:
        module_names = [m for m in MODULE_ORDER if m]
    else:
        module_names = sorted([d.name for d in SRC_DIR.iterdir() if d.is_dir()])
    
    # 生成 Markdown 内容
    lines = []
    modules_processed = 0
    files_processed = 0
    
    for module_name in module_names:
        # 特殊处理：src 根目录下的 .py 文件
        if module_name == "src":
            # 查找 src/ 根目录下的所有 .py 文件（排除 __init__.py）
            src_files = sorted([
                f for f in SRC_DIR.iterdir()
                if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
            ])
            
            if src_files:
                lines.append(f"### `{SRC_DIR.relative_to(PROJECT_ROOT).as_posix()}/`")
                lines.append("")  # 标题后空行
                
                # src/ 根目录通常无 __init__.py，尝试使用配置描述
                if "src/" in MODULE_DESCRIPTIONS:
                    lines.append(f"> {MODULE_DESCRIPTIONS['src/']}")
                    lines.append("")  # 描述后空行
                
                # 根据开关动态决定表头
                if SHOW_SUMMARY_COLUMN:
                    lines.append("| 文件 | 公共 API | 职责概要 |")
                    lines.append("| :--- | :--- | :--- |")
                else:
                    lines.append("| 文件 | 公共 API |")
                    lines.append("| :--- | :--- |")
                                
                for src_file in src_files:
                    public_apis = extract_all_from_file(src_file)
                                    
                    # 检查是否在强制索引白名单中
                    is_force_index = src_file.name in FORCE_INDEX_FILES
                                    
                    # 如果没有 __all__ 且不在白名单中，跳过
                    if not public_apis and not is_force_index:
                        continue
                                    
                    # 生成 API 字符串（白名单文件可能没有 __all__）
                    if public_apis:
                        api_str = format_api_symbols(src_file, public_apis)
                    else:
                        api_str = "—"  # 表示"不适用"
                                    
                    rel_path = src_file.relative_to(PROJECT_ROOT).as_posix()
                                    
                    # 根据开关动态生成行
                    if SHOW_SUMMARY_COLUMN:
                        summary = get_file_summary(src_file)
                        lines.append(f"| `{rel_path}` | {api_str} | {summary} |")
                    else:
                        lines.append(f"| `{rel_path}` | {api_str} |")
                    print(f"✅ {rel_path}: {len(public_apis)} 个公共 API")
                    files_processed += 1
                
                lines.append("")  # 空行分隔
                modules_processed += 1
            continue
        
        # 正常模块处理
        module_dir = SRC_DIR / module_name
        
        if not module_dir.exists():
            print(f"⚠️  Warning: {module_dir} not found, skipping.")
            continue
        
        # 跳过黑名单目录
        if module_name in EXCLUDE_DIRS:
            continue
        
        # 查找所有 .py 文件（排除 __init__.py）
        py_files = sorted([
            f for f in module_dir.rglob("*.py")
            if f.name != "__init__.py" and not f.name.startswith('_')
        ])
        
        if not py_files:
            continue
        
        # 添加模块标题（三级标题，带路径）
        lines.append(f"### `{module_dir.relative_to(PROJECT_ROOT).as_posix()}/`")
        lines.append("")  # 标题后空行
        
        # 添加模块功能描述（从 __init__.py 提取）
        module_desc = get_module_description(module_name, module_dir)
        if module_desc:
            lines.append(f"> {module_desc}")
            lines.append("")  # 描述后空行
        
        # 根据开关动态决定表头
        if SHOW_SUMMARY_COLUMN:
            lines.append("| 文件 | 公共 API | 职责概要 |")
            lines.append("| :--- | :--- | :--- |")
        else:
            lines.append("| 文件 | 公共 API |")
            lines.append("| :--- | :--- |")
        
        module_has_files = False
        for py_file in py_files:
            # 提取公共 API
            public_apis = extract_all_from_file(py_file)
            if not public_apis:
                continue  # 跳过没有 __all__ 的文件
            
            # 格式化符号
            api_str = format_api_symbols(py_file, public_apis)
            
            # 生成相对路径
            rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
            
            # 根据开关动态生成行
            if SHOW_SUMMARY_COLUMN:
                summary = get_file_summary(py_file)
                lines.append(f"| `{rel_path}` | {api_str} | {summary} |")
            else:
                lines.append(f"| `{rel_path}` | {api_str} |")
            module_has_files = True
            files_processed += 1
        
        if module_has_files:
            lines.append("")  # 空行分隔
            modules_processed += 1
            print(f"✅ {module_name}: {sum(1 for f in py_files if extract_all_from_file(f))} 个文件")
    
    print(f"\n📊 Generated index: {modules_processed} modules, {files_processed} files.")
    return "\n".join(lines)


def replace_in_target_file(content: str, output_path: Optional[Path] = None) -> bool:
    """将索引内容替换到目标文件的特定区域。
    
    Args:
        content: 要插入的索引内容
        output_path: 输出文件路径（默认 project_info/CONTEXT_INDEX.md）
        
    Returns:
        True 如果成功替换
    """
    
    # 路径精确定位
    SCRIPT_DIR = Path(__file__).parent
    PROJECT_ROOT = SCRIPT_DIR.parent
    
    if output_path is None:
        output_path = PROJECT_ROOT / "project_info" / "CONTEXT_INDEX.md"
    
    if not output_path.exists():
        print(f"❌ Error: {output_path} not found.")
        return False
    
    try:
        file_content = output_path.read_text(encoding="utf-8")
        lines = file_content.split('\n')
        
        # 查找替换区域：从 "## 📦 核心模块定位表" 后一行开始，到下一个 "##" 标题前（替换整个模块定位表区域）
        start_marker = "## 📦 核心模块定位表"
        start_idx = None
        end_idx = None
        
        for i, line in enumerate(lines):
            if start_marker in line:
                start_idx = i + 1  # 标题后下一行开始
                break
        
        if start_idx is None:
            print(f"❌ Error: Start marker '{start_marker}' not found.")
            return False
        
        # 从 start_idx 开始查找下一个 ## 标题（替换整个区域）
        for j in range(start_idx, len(lines)):
            if lines[j].startswith('## ') and not lines[j].startswith('### '):
                end_idx = j
                break
        
        # 如果没找到下一个 ## 标题，说明是文件末尾，替换到文件末尾
        if end_idx is None:
            end_idx = len(lines)
        
        # 构建新内容：配置段落 + 空行 + 生成的索引 + 空行
        header_content = '\n'.join(HEADER_SECTIONS)
        new_lines = lines[:start_idx] + [''] + header_content.split('\n') + [''] + content.split('\n') + [''] + lines[end_idx:]
        new_content = '\n'.join(new_lines)
        
        # 写回文件
        output_path.write_text(new_content, encoding="utf-8")
        
        print(f"✅ Successfully replaced index in {output_path.relative_to(PROJECT_ROOT)}")
        print(f"   Lines {start_idx+1} to {end_idx} replaced")
        return True
        
    except Exception as e:
        print(f"❌ Failed to update {output_path}: {e}")
        return False


def refresh_index(output_path: Optional[Path] = None):
    """刷新索引文件。
    
    Args:
        output_path: 输出文件路径（默认 project_info/CONTEXT_INDEX.md）
    """
    
    print("=" * 60)
    print("🔧 Generating API Index")
    print("=" * 60)
    
    # 生成索引内容
    index_content = generate_index_content()
    
    if not index_content:
        print("❌ Failed to generate index content.")
        return
    
    # 替换到目标文件
    success = replace_in_target_file(index_content, output_path)
    
    if success:
        print("\n" + "=" * 60)
        print("🎉 Index update complete!")
        print("=" * 60)


if __name__ == "__main__":
    # 解析命令行参数
    output_path = None
    if len(sys.argv) > 1 and sys.argv[1] == "--output":
        if len(sys.argv) > 2:
            output_path = Path(sys.argv[2])
        else:
            print("❌ Error: --output requires a file path")
            sys.exit(1)
    
    refresh_index(output_path)
