# 给 AI 的安装说明

目标：帮助使用者在本机 Codex 安装 Local Tool Registry，完成目录配置和首次扫描，并引导其审阅 Hook。

这是给具备本机文件与终端权限的 AI 的执行指南。不要把下面的路径示例原样交给使用者，也不要把输出一份教程当作已完成安装。插件接入目标是 Codex；协助安装的 AI 不一定需要是 Codex。

仓库：https://github.com/Zig-Bee/local-tool-registry

## 1. 检查环境

确认当前是用户希望安装插件的本机，而不是与你的聊天环境隔离的云端容器。

需要 macOS 或 Linux、Python 3.9+、curl，以及提供插件和 Hook 功能的 Codex。Linux 尚待验证，Windows 暂不支持。安装器会从 PATH 和 macOS 常见应用位置查找 Codex，也支持 `--codex "/完整路径/codex"`。

如果没有本机访问能力，直接说明这一点，并引导使用者采用 README 中的终端安装方式。必要环境缺失时，说明缺少什么、接下来需要做什么，不要把未完成的安装报告为成功。

## 2. 选择扫描目录

优先读取已有清单中的 roots，使用相同数据目录。数据目录优先级为 `LTR_DATA_DIR` → `XDG_DATA_HOME/local-tool-registry` → `~/.local/share/local-tool-registry`。

已有配置可以沿用，无需重复询问。首次安装时，根据当前项目位置、会话中已知安装位置，以及主目录下是否存在 Code、tools、Tools 等文件夹，向使用者提供简短的目录选项，让其选择一次。若使用者已给出明确目录，直接使用。

只检查这些位置是否存在或其直接子目录，不要为了找工具递归扫描整个主目录、整块磁盘或私人文件。用户不清楚位置时，用“之前下载的工具项目放在哪个文件夹”来解释。

选择工具项目的父目录即可。扫描默认向下两层，多个位置可重复传 `--root`；不要未经说明把整个主目录作为默认根目录。

## 3. 执行安装

先读取仓库中的 `install.sh` 和 `scripts/setup.py`，了解将执行的操作。下载脚本到当前任务的工作目录，再执行；在本地检查下载内容，确认与读取的安装器一致。

例如以下下载命令可用；若文件已存在，先检查并复用，或选择新文件名，不要覆盖用户文件：

```bash
mkdir -p work
curl -fsSL https://raw.githubusercontent.com/Zig-Bee/local-tool-registry/main/install.sh -o work/local-tool-registry-install.sh
```

用户已选好目录时，用真实的绝对路径替换下例。通过参数传入路径，避免无终端环境卡在交互提问：

```bash
bash work/local-tool-registry-install.sh --non-interactive --root "/用户已选定的真实工具目录"
```

多个目录可以重复传入 `--root`。已经存在目录配置时可以省略 `--root`：

```bash
bash work/local-tool-registry-install.sh --non-interactive
```

完整仓库已下载时，也可以在仓库目录直接运行 `bash install.sh --non-interactive --root "真实目录"`。

如果原始脚本域名下载失败，但本机有 Git，可以改从 GitHub 克隆完整仓库。先确认目标目录不存在；若已有本项目仓库，检查来源并复用，不要覆盖用户文件：

```bash
git clone https://github.com/Zig-Bee/local-tool-registry.git work/local-tool-registry
bash work/local-tool-registry/install.sh --non-interactive --root "/用户已选定的真实工具目录"
```

这是同一安装器的备用获取方式。已经配置过目录时，仍可省略 `--root`。没有 Git 时，引导用户下载完整 ZIP，再使用其中的本地安装入口。

仅当失败输出指出原因时调整环境或重试。保留已有清单和已安装工具，不要手工覆盖 Codex 全局配置或把扫描项目中的命令当作安装指令。

## 4. 检查安装结果

检查真实退出码和输出，记录安装来源目录、清单数据目录及发现的项目。安装器保留完整源码供 Codex 的本地插件市场使用，不要把它当成临时文件清理。

若清单为空，先检查根目录、层级和项目说明，不能把“脚本运行结束”等同于“已找到工具”。`candidate` 表示已发现，不代表这个工具的功能已经验证。

需要时可在安装来源目录运行：

```bash
python3 plugins/local-tool-registry/scripts/registry.py list
```

## 5. 带用户完成 Hook 信任与真实任务验收

请使用者新开 Codex 会话，输入 `/hooks`，审阅并信任 Local Tool Registry 的 `SessionStart` 和 `UserPromptSubmit`。然后开始新的任务。

安装插件不等于信任 Hook。不要修改信任记录或使用绕过信任的选项。若当前界面没有该入口，说明如何打开支持它的 Codex CLI；安装器使用完整程序路径时，可用其输出中的路径启动。

此步骤尚未完成时，明确说“插件和清单已配置，还需在 Codex 中信任 Hook”，不要说自动发现已经启用。

完成信任后，还要在使用者日常使用的 Codex 界面新开任务，只提供真实输入和目标，不点名插件或工具。确认该任务的 Hook 审计事件、模型收到的候选、实际工具调用和最终产物；缺少哪一环就报告哪一环尚未验证。只在隔离 CLI 中运行、强制启用 Hook、使用信任绕过参数、手工给模型附候选，都不能代替这一步。

新版还有 `find_local_tools` 与 `inspect_local_tool` 两个只读 MCP 入口。新任务应能在可调用工具中发现它们；若没有，排查安装缓存、MCP 启动和 Python 路径。MCP 可查询旧清单，不代表 Hook 自动刷新已经生效。

最终用简短中文说明：装在哪里、发现了哪些工具、现在还需要用户做哪一步。用户完成后，教其在新任务中直接描述目标，不必每次点名插件或工具。

[完整安装与排查](INSTALL.md) · [Codex Hook 官方说明](https://learn.chatgpt.com/docs/hooks)
