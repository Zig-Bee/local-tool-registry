#!/usr/bin/env bash
# Local Tool Registry official bootstrap. Forks should update the default repository.
# Local ZIP: bash install.sh. Remote: curl -fsSL <published URL>/install.sh | bash.

ltr_install() (
    set -euo pipefail
    umask 077
    local ltr_repo="${LTR_REPOSITORY:-Zig-Bee/local-tool-registry}"
    local ltr_ref="${LTR_REF:-main}"
    local ltr_source="" ltr_archive="" ltr_python

    case "$(uname -s)" in
        Darwin|Linux) ;;
        *) echo '需要 macOS 或 Linux；Windows 暂不支持。' >&2; exit 1 ;;
    esac
    ltr_python="$(command -v python3 || true)"
    if [[ -z "$ltr_python" ]] || ! "$ltr_python" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
        echo '需要 Python 3.9+，请安装后重新运行。插件本身无需 pip 安装依赖。' >&2
        exit 1
    fi

    # A complete local checkout needs no network access.
    if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
        ltr_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
        if [[ ! -f "$ltr_source/scripts/setup.py" || ! -f "$ltr_source/.agents/plugins/marketplace.json" ]]; then
            ltr_source=""
        fi
    fi
    if [[ -z "$ltr_source" ]]; then
        if [[ ! "$ltr_repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ || ! "$ltr_ref" =~ ^[A-Za-z0-9_.-]+$ ]]; then
            echo '无效的 GitHub owner/repo 或 ref。ref 请用简单分支名、tag 或 commit SHA。' >&2
            exit 1
        fi
        command -v curl >/dev/null || { echo '找不到 curl，请先安装。' >&2; exit 1; }
        ltr_archive="$(mktemp "${TMPDIR:-/tmp}/ltr-download.XXXXXXXX")"
        trap 'rm -f -- "$ltr_archive"' EXIT
        echo '正在下载 Local Tool Registry…'
        curl --fail --silent --show-error --location --retry 2 --connect-timeout 15 --max-time 120 \
            --max-filesize 16777216 --proto '=https' --proto-redir '=https' \
            "https://codeload.github.com/$ltr_repo/tar.gz/$ltr_ref" --output "$ltr_archive"
        ltr_source="$("$ltr_python" - "$ltr_archive" <<'PY'
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile

# Keep source outside Downloads: the local marketplace needs a stable path.
for variable in ("LTR_DATA_DIR", "XDG_DATA_HOME"):
    value = os.environ.get(variable)
    if value and not Path(value).expanduser().is_absolute():
        raise SystemExit(variable + " 必须是绝对路径。")
data = Path(os.environ["LTR_DATA_DIR"]).expanduser() if os.environ.get("LTR_DATA_DIR") else (
    Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))).expanduser() / "local-tool-registry")
sources = data / "sources"
sources.mkdir(parents=True, exist_ok=True, mode=0o700)
target = Path(tempfile.mkdtemp(prefix="source-", dir=str(sources)))
try:
    with tarfile.open(sys.argv[1], "r:gz") as archive:
        members = []
        total = 0
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or not (member.isdir() or member.isfile()):
                raise ValueError("下载包包含不支持的路径或链接。")
            total += member.size
            if len(members) >= 2000 or total > 16 * 1024 * 1024:
                raise ValueError("下载包超过安装大小限制。")
            members.append((member, path))
        if len({path.parts[0] for _, path in members}) != 1:
            raise ValueError("下载包不是单个完整仓库。")
        for member, path in members:
            destination = target.joinpath(*path.parts[1:])
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
    for required in ("scripts/setup.py", ".agents/plugins/marketplace.json", "plugins/local-tool-registry/.codex-plugin/plugin.json"):
        if not (target / required).is_file():
            raise ValueError("下载包缺少文件：" + required)
except BaseException:
    shutil.rmtree(target)
    raise
print(target)
PY
)"
    fi
    echo "安装来源：$ltr_source"
    if ! "$ltr_python" "$ltr_source/scripts/setup.py" "$@"; then
        echo "安装未完成，来源文件已保留在：$ltr_source" >&2
        exit 1
    fi
)

ltr_install "$@"
