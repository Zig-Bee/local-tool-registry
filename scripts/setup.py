#!/usr/bin/env python3
"""Install Local Tool Registry with a small interactive directory chooser."""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "plugins/local-tool-registry/scripts/registry.py"


def load_registry():
    spec = importlib.util.spec_from_file_location("ltr_registry", REGISTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report_activation(codex):
    spec = importlib.util.spec_from_file_location("ltr_activation", REPO / "scripts/check_activation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.check_activation(codex, str(REPO))
    messages = {
        "ready": "Hook 配置可运行；普通新会话是否触发、是否采用工具仍待验收。",
        "needs_trust": "自动注入未启用：Hook 已加载，但尚未获信任。请在 /hooks 审阅。",
        "disabled": "自动注入未启用：发现已禁用的 Hook，请在 /hooks 检查。",
        "not_loaded": "自动注入未就绪：宿主没有加载完整的插件 Hook，请检查安装来源与版本。",
        "unknown": "无法确认 Hook 状态；自动注入保持待验收，请在 /hooks 检查。",
    }
    print(messages.get(result.get("status"), messages["unknown"]))
    return result


def find_codex(explicit=None):
    if explicit:
        path = shutil.which(str(Path(explicit).expanduser()))
        if not path:
            raise ValueError("指定的 Codex 程序不可执行：" + explicit)
        return path
    path = shutil.which("codex")
    if path:
        return path
    if sys.platform == "darwin":
        for base in (Path("/Applications"), Path.home() / "Applications"):
            for name in ("Codex.app", "ChatGPT.app"):
                path = base / name / "Contents/Resources/codex"
                if path.is_file() and os.access(path, os.X_OK):
                    return str(path)
    raise ValueError("没有找到 Codex CLI。请先安装 Codex CLI，或用 --codex /完整路径/codex 指定已有程序。")


@contextlib.contextmanager
def terminal_input():
    # curl | bash occupies stdin; interactive answers must come from the terminal.
    if sys.stdin.isatty():
        yield sys.stdin
    else:
        try:
            stream = open("/dev/tty", encoding="utf-8")
        except OSError:
            raise ValueError("当前没有交互终端。请加 --root '/工具目录'；已有配置可加 --non-interactive。")
        with stream:
            yield stream


def read_answer(stream, prompt):
    print(prompt, end="", flush=True)
    line = stream.readline()
    if not line:
        raise ValueError("输入已结束，尚未开始安装。可使用 --root 指定工具目录。")
    return line.strip()


def parse_directory(value):
    # Accept pasted paths, quoted paths and macOS terminal drag-and-drop escaping.
    direct = Path(value).expanduser()
    if value and direct.is_dir():
        return direct.resolve()
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = []
    if len(parts) == 1 and Path(parts[0]).expanduser().is_dir():
        return Path(parts[0]).expanduser().resolve()
    raise ValueError("找不到这个目录，请粘贴或拖入一个已经存在的文件夹。")


def choose_roots(existing, non_interactive=False):
    if non_interactive:
        if not existing:
            raise ValueError("首次安装需要 --root '/工具目录'，或在终端运行以选择目录。")
        return []
    with terminal_input() as stream:
        if existing:
            print("\n已有工具目录：")
            for root in existing:
                print("  " + root)
            answer = read_answer(stream, "回车沿用；输入 a 追加目录：")
            while answer not in ("", "a", "A"):
                answer = read_answer(stream, "请输入 a，或直接回车沿用：")
            if not answer:
                return []
        suggestions = [Path.home() / name for name in ("Code", "tools", "Tools")]
        suggestions = list(dict.fromkeys(p.resolve() for p in suggestions if p.is_dir()))
        print("\n工具放在哪个文件夹？选择项目的父目录即可，不会自动扫描整个电脑。")
        for number, path in enumerate(suggestions, 1):
            print("  {}. {}".format(number, path))
        roots = []
        while True:
            answer = read_answer(stream, "输入编号或粘贴/拖入目录{}：".format("；回车完成" if roots else ""))
            if not answer and roots:
                return roots
            if answer.isdigit() and 1 <= int(answer) <= len(suggestions):
                path = suggestions[int(answer) - 1]
            else:
                try:
                    path = parse_directory(answer)
                except ValueError as exc:
                    print(str(exc))
                    continue
            if path not in roots:
                roots.append(path)
            print("  已选择：" + str(path))


def run_step(command, label, dry_run=False, verbose=False):
    print(label, flush=True)
    if dry_run or verbose:
        print("+ " + shlex.join(command), flush=True)
    if dry_run:
        return
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError((result.stdout or "命令退出码：" + str(result.returncode)).strip())
    if verbose and result.stdout:
        print(result.stdout.rstrip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", help="工具项目所在的目录，可重复传入。省略时交互选择。")
    parser.add_argument("--codex", help="手动指定 Codex 可执行文件。默认自动查找。")
    parser.add_argument("--configure-only", action="store_true", help="只追加目录并扫描，不安装插件。")
    parser.add_argument("--non-interactive", action="store_true", help="不提问；需要已有目录配置或 --root。")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不安装也不写入清单。")
    parser.add_argument("--verbose", action="store_true", help="显示完整命令与输出。")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 9) or sys.platform not in ("darwin", "linux"):
            raise ValueError("需要 macOS 或 Linux 和 Python 3.9+。Windows 暂不支持。")
        for variable in ("LTR_DATA_DIR", "XDG_DATA_HOME"):
            value = os.environ.get(variable)
            if value and not Path(value).expanduser().is_absolute():
                raise ValueError(variable + " 必须是绝对路径，确保新会话使用同一份清单。")
        market = json.loads((REPO / ".agents/plugins/marketplace.json").read_text())["name"]
        module = load_registry()
        catalog = module.Registry(module.default_data_dir())
        try:
            existing = catalog._load_snapshot()["roots"]
        except module.RegistryError as exc:
            raise ValueError(str(exc))
        codex = None if args.configure_only else find_codex(args.codex)
        print("Local Tool Registry · 本地工具清单")
        roots = [parse_directory(p) for p in args.root] if args.root else choose_roots(existing, args.non_interactive)
        commands = []
        if codex:
            commands.append(([codex, "plugin", "--help"], "检查 Codex 插件功能…"))
            commands.extend([
                ([codex, "plugin", "marketplace", "add", str(REPO)], "注册插件来源…"),
                ([codex, "plugin", "add", "local-tool-registry@" + market], "安装插件…"),
            ])
        if roots:
            configure = [sys.executable, str(REGISTRY), "configure"]
            for path in roots:
                configure.extend(["--root", str(path)])
            commands.append((configure, "保存工具目录…"))
        commands.append(([sys.executable, str(REGISTRY), "scan"], "扫描已有工具…"))
        for command, label in commands:
            run_step(command, label, args.dry_run, args.verbose)
        if args.dry_run:
            print("预览完成，没有执行命令或修改清单。")
            return 0
        listing = catalog.list(8)
        print("\n插件文件与清单已配置，清单中共有 {} 个项目：".format(listing["total"]))
        for tool in listing["tools"]:
            print("  {} · {}".format(tool["name"], tool["status"]))
        if not listing["total"]:
            print("还没有发现工具。请检查目录中是否有项目 README 或受支持配置。")
        if codex:
            print("\n检查宿主实际 Hook 状态（只读，不更改信任）…", flush=True)
            report_activation(codex)
        print("\n下一步：新开 Codex 会话，输入 /hooks，审阅并信任 Local Tool Registry 的 Hook。")
        print("自动注入尚待验收：请在日常使用的 Codex 界面新开任务，只给输入和目标，不点名工具。")
        print("确认该会话收到候选并实际使用工具；手动运行 Hook 或绕过信任的测试不算安装验收。")
        print("新任务也应能发现 find_local_tools / inspect_local_tool 两个只读 MCP 入口。")
        print("清单目录：" + str(catalog.data_dir))
        print("安装来源：" + str(REPO) + "（请保留）")
        if codex and not shutil.which("codex"):
            print("需要使用 CLI 时运行：" + shlex.quote(codex))
        if os.environ.get("LTR_DATA_DIR") or os.environ.get("XDG_DATA_HOME"):
            print("使用了自定义数据路径；Codex 也需要相同的环境变量。")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("\n安装未完成：" + str(exc), file=sys.stderr)
        print("已完成的步骤和已有清单会保留。修复问题后可重新运行安装命令。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
