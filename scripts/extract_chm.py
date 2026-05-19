#!/usr/bin/env python3
"""CHM 文件内容提取脚本。

将 CHM (Microsoft Compiled HTML Help) 文件中的内容提取为纯文本。
新增 TOC 解析、按章节提取、批量解压到目录等功能。

需要安装 python-chm 库（pip install python-chm）。

用法：
    python extract_chm.py <input.chm> [output.txt]                      # 全部提取（原有行为）
    python extract_chm.py --toc <input.chm>                             # 提取目录结构为 JSON
    python extract_chm.py --section <path> <input.chm>                  # 提取单个章节文本
    python extract_chm.py --extract-dir <输出目录> <input.chm>          # 解压所有章节到目录
"""

import sys
import os
import json
import re
from html.parser import HTMLParser

CHM_AVAILABLE = False
try:
    from chm.chm import CHMFile
    from chm import chmlib
    CHM_AVAILABLE = True
except ImportError:
    try:
        import chm
        CHM_AVAILABLE = True
    except ImportError:
        pass


class TOCParser(HTMLParser):
    """解析 .hhc 目录文件，提取章节标题、路径和层级。"""

    def __init__(self):
        super().__init__()
        self.entries = []
        self.current = None
        self.ul_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'ul':
            self.ul_depth += 1
        elif tag == 'param' and self.current is not None:
            name = attrs_dict.get('name', '')
            value = attrs_dict.get('value', '')
            if name == 'Name':
                self.current['title'] = value
            elif name == 'Local':
                self.current['path'] = value
        elif tag == 'object' and attrs_dict.get('type') == 'text/sitemap':
            self.current = {}

    def handle_endtag(self, tag):
        if tag == 'ul':
            self.ul_depth -= 1
        elif tag == 'object':
            if self.current and 'title' in self.current:
                self.current['level'] = self.ul_depth
                self.entries.append(self.current)
            self.current = None

    def handle_data(self, data):
        pass


def _assign_ids(entries):
    """为目录条目分配顺序 ID、parent_id 和 full_path。"""
    result = []
    parent_stack = []
    counter = 0
    for entry in entries:
        counter += 1
        item = {
            "id": counter,
            "title": entry["title"],
            "path": entry.get("path", ""),
            "level": entry["level"],
        }
        while parent_stack and parent_stack[-1]["level"] >= item["level"]:
            parent_stack.pop()
        item["parent_id"] = parent_stack[-1]["id"] if parent_stack else None
        item["full_path"] = parent_stack[-1]["full_path"] + " > " + entry["title"] if parent_stack else entry["title"]
        parent_stack.append(item)
        result.append(item)
    return result


def _find_hhc(chm_handle):
    """在 CHM 文件中查找 .hhc 目录文件的内部路径。"""
    hhc_paths = []

    def enumerator(ctx, ui, context):
        p = ui.path.decode('utf-8', errors='replace')
        if p.lower().endswith('.hhc'):
            hhc_paths.append(p)
        return chmlib.CHM_ENUMERATOR_CONTINUE

    chmlib.chm_enumerate(chm_handle, chmlib.CHM_ENUMERATE_ALL, enumerator, None)
    return hhc_paths[0] if hhc_paths else None


def extract_toc(chm_path):
    """提取 CHM 文件的目录结构。

    Args:
        chm_path: CHM 文件路径。

    Returns:
        目录条目列表 [{"id": int, "title": str, "path": str, "level": int, "parent_id": int|null}, ...]
        失败返回 None。
    """
    if not os.path.exists(chm_path):
        print(f"错误：文件不存在 - {chm_path}", file=sys.stderr)
        return None

    if not CHM_AVAILABLE:
        print(f"错误：未安装 python-chm 库。请执行: pip install python-chm", file=sys.stderr)
        return None

    try:
        chm_file = CHMFile()
        if not chm_file.LoadCHM(chm_path):
            print(f"错误：无法加载 CHM 文件", file=sys.stderr)
            return None

        data = chm_file.GetTopicsTree()
        hhc_path_fallback = _find_hhc(chm_file.file) if data is None else None

        if data is None and hhc_path_fallback:
            res, ui = chmlib.chm_resolve_object(chm_file.file, hhc_path_fallback.encode('utf-8'))
            if res == chmlib.CHM_RESOLVE_SUCCESS:
                size, raw = chmlib.chm_retrieve_object(chm_file.file, ui, 0, ui.length)
                data = raw[:size] if size > 0 else None

        chm_file.CloseCHM()

        if not data:
            print(f"错误：目录文件为空", file=sys.stderr)
            return None

        text = data.decode('utf-8', errors='replace')
        parser = TOCParser()
        parser.feed(text)
        return _assign_ids(parser.entries)

    except Exception as e:
        print(f"错误：提取目录失败 - {e}", file=sys.stderr)
        return None


def extract_section(chm_path, section_path):
    """从 CHM 文件中提取单个章节的纯文本。

    Args:
        chm_path: CHM 文件路径。
        section_path: 章节在 CHM 中的内部路径（如 "/chapter1/sec1.htm"）。

    Returns:
        纯文本内容，提取失败返回 None。
    """
    if not os.path.exists(chm_path):
        print(f"错误：文件不存在 - {chm_path}", file=sys.stderr)
        return None

    if not CHM_AVAILABLE:
        print(f"错误：未安装 python-chm 库。请执行: pip install python-chm", file=sys.stderr)
        return None

    try:
        chm_file = CHMFile()
        if not chm_file.LoadCHM(chm_path):
            print(f"错误：无法加载 CHM 文件", file=sys.stderr)
            return None

        if not section_path.startswith('/'):
            section_path = '/' + section_path
        res, ui = chmlib.chm_resolve_object(chm_file.file, section_path.encode('utf-8'))
        if res != chmlib.CHM_RESOLVE_SUCCESS:
            chm_file.CloseCHM()
            print(f"警告：章节未找到 - {section_path}", file=sys.stderr)
            return ""

        size, data = chmlib.chm_retrieve_object(chm_file.file, ui, 0, ui.length)
        chm_file.CloseCHM()

        if not data or size == 0:
            print(f"警告：章节为空 - {section_path}", file=sys.stderr)
            return ""

        text = data.decode('utf-8', errors='replace')
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    except Exception as e:
        print(f"错误：提取章节失败 {section_path} - {e}", file=sys.stderr)
        return None


def _sanitize_title(title, max_len=60):
    """将章节标题转为安全的文件名片段。"""
    safe = re.sub(r'[\\/*?:"<>|]', '', title)
    safe = safe.replace(' ', '_')
    safe = safe.strip('._')
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe if safe else "untitled"


def extract_to_dir(chm_path, output_dir):
    """将 CHM 所有章节按 TOC 结构解压到指定目录。

    目录结构：
        output_dir/
            _toc.json                    # TOC 结构
            ch001_章节标题.txt            # 各章节纯文本
            ch002_章节标题.txt
            ...

    Args:
        chm_path: CHM 文件路径。
        output_dir: 输出目录（自动创建）。

    Returns:
        成功返回 True，失败返回 False。
    """
    toc = extract_toc(chm_path)
    if not toc:
        return False

    os.makedirs(output_dir, exist_ok=True)

    # 写 _toc.json
    toc_path = os.path.join(output_dir, '_toc.json')
    with open(toc_path, 'w', encoding='utf-8') as f:
        json.dump(toc, f, ensure_ascii=False, indent=2)

    if not CHM_AVAILABLE:
        print(f"错误：未安装 python-chm 库", file=sys.stderr)
        return False

    try:
        chm_file = CHMFile()
        if not chm_file.LoadCHM(chm_path):
            print(f"错误：无法加载 CHM 文件", file=sys.stderr)
            return False

        extracted = 0
        total = sum(1 for e in toc if e.get('path'))

        for entry in toc:
            section_path = entry.get('path', '')
            if not section_path:
                continue
            if not section_path.startswith('/'):
                section_path = '/' + section_path

            section_path_bytes = section_path.encode('utf-8')
            res, ui = chmlib.chm_resolve_object(chm_file.file, section_path_bytes)
            if res != chmlib.CHM_RESOLVE_SUCCESS:
                continue

            size, data = chmlib.chm_retrieve_object(chm_file.file, ui, 0, ui.length)
            if not data or size == 0:
                continue

            text = data.decode('utf-8', errors='replace')
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if not text:
                continue

            seq = str(entry['id']).zfill(3)
            safe = _sanitize_title(entry['title'])
            filename = f"ch{seq}_{safe}.txt"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# {entry['title']}\n# 章节路径: {entry.get('full_path', '')}\n# 源文件: {section_path}\n\n{text}\n")

            extracted += 1

        chm_file.CloseCHM()
        print(f"成功：已解压 {extracted}/{total} 个章节到 {output_dir}")
        return True

    except Exception as e:
        print(f"错误：解压失败 - {e}", file=sys.stderr)
        return False


def extract_chm(chm_path, output_path=None):
    """将 CHM 文件全部内容提取为纯文本（原有行为，保持向后兼容）。"""
    if not os.path.exists(chm_path):
        print(f"错误：文件不存在 - {chm_path}", file=sys.stderr)
        return False

    if not output_path:
        output_path = os.path.splitext(chm_path)[0] + '.txt'

    if not CHM_AVAILABLE:
        print(f"错误：未安装 python-chm 库。请执行: pip install python-chm", file=sys.stderr)
        print(f"提示：如果无法安装，可以使用 `extract_chmLib` 命令行工具替代。", file=sys.stderr)
        return False

    try:
        chm_file = CHMFile()
        if not chm_file.LoadCHM(chm_path):
            print(f"错误：无法加载 CHM 文件", file=sys.stderr)
            return False

        all_text = []
        file_list = []

        def enumerator(ctx, ui, context):
            p = ui.path.decode('utf-8', errors='replace')
            if p.lower().endswith(('.htm', '.html', '.txt')):
                file_list.append(p)
            return chmlib.CHM_ENUMERATOR_CONTINUE

        chmlib.chm_enumerate(chm_file.file, chmlib.CHM_ENUMERATE_FILES, enumerator, None)

        for entry_path in file_list:
            try:
                entry_path_bytes = entry_path.encode('utf-8')
                res, ui = chmlib.chm_resolve_object(chm_file.file, entry_path_bytes)
                if res != chmlib.CHM_RESOLVE_SUCCESS:
                    continue
                size, data = chmlib.chm_retrieve_object(chm_file.file, ui, 0, ui.length)
                if data and size > 0:
                    text = data.decode('utf-8', errors='replace')
                    text = re.sub(r'<[^>]+>', '', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    if text:
                        all_text.append(f"--- {entry_path} ---\n{text}\n")
            except Exception as e:
                print(f"警告：读取 {entry_path} 失败: {e}", file=sys.stderr)

        chm_file.CloseCHM()

        if not all_text:
            print(f"警告：未从 CHM 文件中提取到任何文本内容", file=sys.stderr)
            return False

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(all_text))

        print(f"成功：已提取 {len(all_text)} 个文件到 {output_path}")
        return True

    except Exception as e:
        print(f"错误：提取 CHM 文件失败 - {e}", file=sys.stderr)
        return False


def _print_usage():
    print("用法：", file=sys.stderr)
    print("  python extract_chm.py <input.chm> [output.txt]                        # 全部提取", file=sys.stderr)
    print("  python extract_chm.py --toc <input.chm>                               # 提取目录", file=sys.stderr)
    print("  python extract_chm.py --section <path> <input.chm>                    # 提取单个章节", file=sys.stderr)
    print("  python extract_chm.py --extract-dir <输出目录> <input.chm>            # 解压到目录", file=sys.stderr)


def main():
    args = sys.argv[1:]

    if not args:
        _print_usage()
        sys.exit(1)

    if args[0] == '--toc':
        if len(args) < 2:
            print("错误：--toc 需要指定 CHM 文件路径", file=sys.stderr)
            sys.exit(1)
        toc = extract_toc(args[1])
        if toc is None:
            sys.exit(1)
        print(json.dumps(toc, ensure_ascii=False, indent=2))
        return

    if args[0] == '--section':
        if len(args) < 3:
            print("错误：--section 需要指定 <内部路径> <CHM 文件>", file=sys.stderr)
            sys.exit(1)
        text = extract_section(args[2], args[1])
        if text is None:
            sys.exit(1)
        print(text)
        return

    if args[0] == '--extract-dir':
        if len(args) < 3:
            print("错误：--extract-dir 需要指定 <输出目录> <CHM 文件>", file=sys.stderr)
            sys.exit(1)
        if not extract_to_dir(args[2], args[1]):
            sys.exit(1)
        return

    # 向后兼容：python extract_chm.py <input.chm> [output.txt]
    chm_path = args[0]
    output_path = args[1] if len(args) > 1 else None
    if chm_path.startswith('--'):
        print(f"错误：未知选项 {chm_path}", file=sys.stderr)
        _print_usage()
        sys.exit(1)
    if not extract_chm(chm_path, output_path):
        sys.exit(1)


if __name__ == '__main__':
    main()
