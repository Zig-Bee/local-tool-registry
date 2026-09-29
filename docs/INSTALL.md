# 安装与使用

不想操作终端？在 [README](../README.md#方式一复制给-ai跟着提示安装) 复制提示词，让能访问本机的 AI 按 [AI 安装说明](AI-INSTALL.md) 完成配置。以下是自行使用终端的方式。

## 推荐：一条命令启动

前提：电脑已有 Python 3.9+、curl，以及支持插件和 Hook 的 Codex。当前以 macOS 为主，Linux 待验证，Windows 暂不支持。


```bash
curl -fsSL https://raw.githubusercontent.com/Zig-Bee/local-tool-registry/main/install.sh | bash
```

脚本会下载完整仓库、查找 Codex、保存目录、安装插件并首次扫描，不需要 Git、pip 或 sudo。若找不到 Python 或 Codex，会显示原因并退出；它不会替你安装这些宿主软件。

远程下载的源码保存在清单数据目录下的 `sources/source-…`，安装结束会显示实际位置，请保留该位置。完整 ZIP 则直接使用解压目录作为安装来源，也需要保留。

## 选择工具目录

界面示意如下，编号取决于你的电脑上有哪些文件夹：

```text
工具放在哪个文件夹？
  1. /Users/你/Code
输入编号或粘贴/拖入目录：1
  已选择：/Users/你/Code
输入编号或粘贴/拖入目录；回车完成：
```

输入编号或目录后，可以继续添加第二个目录；选完直接回车。目录必须存在，中文、空格、终端拖入的路径均可使用。

例如下载器放在“我的工具/下载器”，请选择“我的工具”。默认向下扫描两层，不建议选择整个个人主目录或磁盘。安装器只列出常见目录供选择，不会自行扫描它们。

如果已经配置过，会先显示原目录：回车沿用，输入 `a` 追加。已有清单和手动登记的调用入口会保留。

## 在 Codex 中信任 Hook

新开 Codex 会话，输入 `/hooks`。找到 Local Tool Registry，审阅并信任它的 `SessionStart` 和 `UserPromptSubmit`，然后开始新任务。

这是 Codex 要求的信任步骤，安装插件不会自动完成它。若当前界面没有这个入口，使用支持该功能的 Codex CLI；安装器通过应用位置找到 Codex 时，会显示可直接运行的完整命令。[官方 Hook 说明](https://learn.chatgpt.com/docs/hooks)

自动触发仍要求 Codex 进程能找到 `python3`。终端能运行 Python，不代表所有桌面启动环境都拥有相同 PATH。

## 已经下载了 ZIP

完整解压到准备长期保留的目录。打开终端，输入 `bash `（后面有空格），把文件夹里的 `install.sh` 拖进去，再按回车。

也可以在仓库目录运行：

```bash
bash install.sh
```

脚本使用本地文件，不再下载仓库。不要只下载 Skill 文件；隐藏目录 `.agents` 和 `.codex-plugin` 也属于插件。

## 安装完成后

安装器会列出发现的项目。清单为空时，请检查选择的目录中是否有项目 README 或受支持配置。

开始新的 Codex 任务，直接描述结果，例如：

> 请把这个 CSV 转成 Markdown 表格，保留全部数据行和列顺序，保存为 report.md。

清单中的 `candidate` 表示发现了项目；`configured` 表示登记了入口且基础检查通过；`unavailable` 表示路径或环境等基础检查失败。这些状态都不等于功能已经运行成功。

## 以后添加目录

在安装来源目录再次运行 `bash install.sh`，输入 `a` 添加目录。也可以只更新清单：

```bash
bash install.sh --configure-only
```

新工具放入已配置范围且含可识别说明时，下次成功扫描会刷新候选，无需重新安装插件。

## 高级用法

以下命令在完整仓库目录运行。

直接给定目录，跳过提问：

```bash
bash install.sh --root "/绝对路径/我的工具"
```

多个目录可重复使用 `--root`。无人值守运行用 `--non-interactive`，首次仍需 `--root`；已有配置时会沿用。

只预览，不修改配置：

```bash
bash install.sh --root "/绝对路径/我的工具" --dry-run
```

这里预览的是本地安装步骤；远程入口仍需先下载脚本和源码。显示完整命令与输出可加 `--verbose`。手动指定 Codex 可执行文件可加 `--codex "/完整路径/codex"`。

查看工具清单和查询能力：

```bash
python3 plugins/local-tool-registry/scripts/registry.py list
python3 plugins/local-tool-registry/scripts/registry.py find "CSV Markdown"
```

登记明确的调用入口时，填写 [能力卡模板](../examples/tool-card.json)，然后执行：

```bash
python3 plugins/local-tool-registry/scripts/registry.py register --file "/绝对路径/card.json"
```

目录配置默认追加。若要替换整个扫描范围，使用注册器的 `configure --replace-roots --root ...` 并列出完整的新目录。

默认数据目录为 `~/.local/share/local-tool-registry`。高级优先级：注册器参数 `--data-dir` → `LTR_DATA_DIR` → `XDG_DATA_HOME/local-tool-registry` → 默认目录。自定义路径应为绝对路径，Codex 与安装器要使用相同环境变量；桌面应用不一定继承终端环境。

## 常见问题

| 现象 | 处理方式 |
|---|---|
| 下载失败 | 改用 AI 安装方式，让 AI 尝试 Git 克隆；也可以下载完整 ZIP |
| 找不到 Python | 安装 Python 3.9+，确保 python3 命令可用，再重试 |
| 找不到 Codex | 安装 Codex CLI，或用 --codex 指定已有程序 |
| Codex 不识别 plugin | 更新到提供插件与 Hook 功能的版本 |
| 当前没有交互终端 | 用 --root 指定目录，已有配置可用 --non-interactive |
| 新任务没有候选 | 检查插件启用、Hook 信任、Python PATH 和数据目录是否一致 |
| 候选出现但没有调用 | 检查描述、入口与任务是否匹配；采用工具由模型判断 |
| 工具提示包不存在 | 检查工具自己的虚拟环境；系统 Python 不一定装有该包 |

安装失败会保留先前成功的步骤、已有清单和已下载的来源文件。修复原因后重试。若启用了自定义数据目录，请在终端和 Codex 中保持一致。

## 更新与卸载

发布新版本后按该版本的安装说明重新运行安装器，沿用已有目录配置。Hook 有变化时，需在 `/hooks` 中重新审阅。安装器保留旧下载来源，便于排查；不要清理 Codex 当前引用的来源目录。

卸载：

```bash
codex plugin remove local-tool-registry@local-tool-registry
codex plugin marketplace remove local-tool-registry
```

若 codex 不在 PATH，使用安装时显示的完整程序路径代替。卸载插件不会删除原工具，也不会删除共享清单；需要清理数据时，先备份所需记录，再删除实际数据目录。
