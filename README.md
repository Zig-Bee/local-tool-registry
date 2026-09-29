# Local Tool Registry · 本地工具清单

**工具已经装好了，换个 AI 对话，却又要从头介绍一遍？**

假设你从 GitHub 安装了几个项目：一个视频下载器、一个音频转写工具，还有一个表格转换器。

后来，你在新的 Codex 对话里发来一段音频，说“帮我整理成文字”。它未必知道电脑里已经有转写工具，可能重新找方案、建议安装，或者自己写一段代码。你又得补充：“之前装过那个项目，在这个目录，用它就行。”

**Local Tool Registry 想减少的，就是这次重复交代。**

选好工具所在的目录后，插件会维护一份本地工具清单，在新会话和新任务开始时刷新，并把相关工具的名称、位置和用途提供给 Codex。你描述要做的事，模型再判断是否采用已有工具。

> 当前是实验版，提供 Codex 接入。它帮助模型发现工具，不保证每次都选对、调用或运行成功，也不恢复其他对话的聊天记录。

## 两种安装方式

需要支持插件与 Hook 的 Codex、Python 3.9+。当前主要面向 macOS；Linux 待验证，Windows 暂不支持。

### 方式一：复制给 AI，跟着提示安装

把下面这段完整发给 **能访问本机文件和终端的 AI**，例如本机 Codex：

```text
请帮我在本机 Codex 安装 Local Tool Registry：
https://github.com/Zig-Bee/local-tool-registry

先阅读并按仓库 docs/AI-INSTALL.md 完成实际安装，不要只给我教程。
优先沿用已有工具目录配置；首次安装时，帮我找出常见工具目录，让我选一次即可。
完成后列出发现的工具，并带我完成 /hooks 的审阅与信任。
需要我操作时，只告诉我当前要做的下一步。
```

不需要自己改路径或填写命令。AI 会检查环境、协助选目录、执行安装，再告诉你需要亲自完成的操作。只有网页聊天、无法操作本机的 AI，不能直接替你安装。

### 方式二：在终端粘贴一行命令

```bash
curl -fsSL https://raw.githubusercontent.com/Zig-Bee/local-tool-registry/main/install.sh | bash
```

按提示输入目录编号，或粘贴、拖入已有工具所在的文件夹，选完回车继续。下载、解压、安装、保存目录和首次扫描由脚本完成，无需手动编辑配置，也不需要 Git。

两种方式最后都需要：**新开 Codex 会话，输入 `/hooks`，审阅并信任 Local Tool Registry 的 Hook，再开始新任务。** 这是 [Codex 的要求](https://learn.chatgpt.com/docs/hooks)，安装器不会跳过。

下载完整 ZIP 的用户，也可以在解压目录运行 `bash install.sh`。

[详细教程与排查](docs/INSTALL.md) · [给 AI 的安装说明](docs/AI-INSTALL.md)

## 装好后怎么用

假设你的工具集中放在这里：

```text
我的工具/
├── 视频下载器/
├── 音频转写工具/
└── 表格转换器/
```

首次选择“我的工具”这个目录。以后在新的 Codex 任务里，直接发文件或链接，描述目标：

> 请把这段音频整理成文字，再列出主要观点。

> 请把这个 CSV 转成 Markdown 表格，保存为 report.md。

是否调用已有项目，取决于工具是否适用、环境是否可用以及模型的判断。想确认有没有真正用到，看实际执行的命令和最终文件。

新项目放入已配置目录，并带有可识别的 README 或项目配置时，下次成功扫描会更新候选。装在别处的工具，需要追加目录或单独登记。

## 工作原理

选定目录 → 读取项目说明 → 更新共享清单 → 向当前任务提供候选 → 模型判断并执行。

扫描只读取支持的项目元数据，不会自动执行这些项目，也不会安装它们的依赖。Hook 负责触发刷新，Skill 负责指导模型查询详情、检查入口和验证结果。

默认清单保存在 `~/.local/share/local-tool-registry`，供本机不同 Codex 会话共享，不会自动同步到其他设备。

## 当前限制

- 首次需要选择工具目录，不会扫描整台电脑；默认向下扫描两层。
- 每次任务会重扫配置范围，尚未实现增量索引。
- 描述不完整、匹配不准或候选过多时，可能漏选。
- 下载器、转写工具等仍需要自己的依赖、登录状态和可用入口。
- 插件本身不提供完整的视频下载、转写或理解流程。
- Claude Code、WorkBuddy、DeepSeek 接入及 Windows 支持尚未完成。

[使用示例](examples/SCENARIOS.md) · [登记调用入口](examples/tool-card.json) · [工作原理详解](docs/ARCHITECTURE.md)

遇到问题可在 [Issues](https://github.com/Zig-Bee/local-tool-registry/issues) 反馈系统、Codex 版本、任务和实际表现，分享日志前去掉私人路径及凭证。

[开发与发布](docs/PUBLISHING.md) · [更新记录](CHANGELOG.md) · [MIT License](LICENSE)
