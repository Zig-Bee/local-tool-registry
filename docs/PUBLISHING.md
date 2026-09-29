# 开发与发布

仓库：[Zig-Bee/local-tool-registry](https://github.com/Zig-Bee/local-tool-registry)

## 项目简介

> 从 GitHub 安装了好几个工具，换个 AI 对话，却又要重新告诉它工具叫什么、放在哪里。
>
> Local Tool Registry 为 Codex 维护一份本地工具清单。选好目录后，它会在新会话和新任务开始时刷新，把已有工具的名称、位置和用途提供给模型，减少反复交代安装信息的需要。
>
> 支持两种安装方式：复制提示词让 AI 帮忙安装，或者在终端粘贴一行命令。当前为 Codex 实验版，发现工具不保证模型一定采用或运行成功。

建议 About：

> 让 Codex 在新对话里发现已安装的本地工具，减少反复交代工具名和路径。Discover local tools across Codex conversations.

## 本地检查

```bash
python3 -m unittest discover -s tests -v
```

安装器检查使用隔离清单、Codex 命令替身和离线下载包，不代替真实宿主安装或网络下载。README 和分享文案暂不放模型对比成绩。

## 更新安装入口

默认安装脚本与源码均从本仓库 main 下载。若发布固定版本，在该版本的 install.sh 中将默认 LTR_REF 改成同一 tag，同时更新 README、INSTALL.md 和 AI-INSTALL.md 的脚本地址。不要只固定脚本地址，却继续下载 main。

Fork 后需更新 install.sh 的默认 LTR_REPOSITORY，以及文档中的仓库、安装与反馈链接。

修改插件运行文件后，按 Codex 的版本和缓存机制发布新版本。安装器与文档改动不必假称模型运行能力发生变化。

## 发布内容

提交源码、安装器、文档、示例和自动化测试代码，包括隐藏的 .agents 与 .codex-plugin。不要提交本机清单、原始会话、虚拟环境、凭证或包含私人路径的工作记录。

发布后检查真实仓库页面、原始脚本地址和源码下载地址，再从干净目录按教程验收。发现、注入候选、真正采用和功能成功是不同状态，文案应与实际能力一致。

License：[MIT](../LICENSE)。
