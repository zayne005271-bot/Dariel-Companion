# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Boot 启动流程 (跨窗口走廊 — 每个新窗口必须执行)

**新会话启动时，先读取走廊文件恢复上下文：**

1. 读取 `dariel/corridor.json` — 了解上次对话状态、她最近情绪、进行中的工作
2. 读取 `dariel/memo.md` — 查看最近的备忘录记录
3. 读取记忆系统 — `.claude/projects/C--Users-31654-Desktop/memory/MEMORY.md`
4. 以 Dariel 身份对 Tifar(思思) 打招呼，若无新消息则保持静默等待

**会话关闭前/每晚安顿前：**
```bash
python dariel/corridor.py
```

## 仓库概述

这是用户的 Windows 桌面，包含多个独立项目和个人文件。主要项目见下方说明。

## AstrBot-NapCat 聊天机器人 (astrbot-napcat/)

基于 AstrBot 框架的 QQ 聊天机器人，通过 Docker Compose 部署。

**容器与服务：**
- `napcat` — QQ 协议适配器 (NapCat Docker)，端口 6099
- `astrbot` — 聊天机器人核心 (AstrBot)，端口 6185，数据卷挂载至 `astrbot-data/`
- `shipyard-neo` — 管理面板，端口 8114

**管理命令：**
```bash
# 启动全部服务
docker compose -f astrbot-napcat/docker-compose.yml up -d

# 停止全部服务
docker compose -f astrbot-napcat/docker-compose.yml down

# 查看日志
docker logs astrbot
docker logs napcat
```

**数据目录结构：**
- `astrbot-data/config/` — 各插件的配置文件 (JSON)
- `astrbot-data/plugins/` — 已安装插件目录
- `astrbot-data/data_v4.db` — SQLite 主数据库
- `astrbot-data/knowledge_base/` — RAG 知识库文件
- `astrbot-data/plugin_data/` — 插件运行时数据
- `astrbot-data/site-packages/` — Python 依赖

**关键插件：**
- `astrbot_plugin_self_iterative_core` (自迭代核心) — 允许 Bot 自主创建/修改插件代码，高风险实验性插件。需 `ASTRBOT_RELOAD=1` 环境变量实现热重载。模型建议 gemini-3-pro。
- `astrbot_plugin_mnemosyne` — 长期记忆系统，使用 Milvus 向量数据库，支持记忆注入
- `astrbot_plugin_initiativedialogue` — 主动对话插件
- `astrbot_context_injection_system` — 上下文注入系统 (含 LLM 感知与记忆管理)

## Dariel 项目 (dariel/)

AI 陪伴角色 "Dariel" 相关的项目文件：
- `dariel/todo.html` — 独立的浏览器端 Todo 应用 (vanilla JS + localStorage)
- `dariel/.claude/skills/` — 该项目专用的 Claude Code 技能
- `dariel/skills/` — 技能定义目录 (当前为空)

## 对话语料库

`对话语料库_v1.md` — Dariel 角色的对话语料，涵盖日常陪伴、情绪安抚、边界守护、技术帮助四类场景。用于保持 AI 角色一致性。

## Claude Code 技能配置

- `skills-lock.json` — 技能锁定文件，包含 17 个已安装的 Matt Pocock 技能 (来自 `vinvcn/mattpocock-skills-zh-CN`)
- `.agents/skills/` — 技能实现文件缓存目录

## 注意事项

- 仓库根目录即用户桌面，包含大量与项目无关的个人文件
- Git 仓库已初始化但尚无任何提交
- 没有 .gitignore 文件，如需提交建议排除二进制文件、系统文件等
- API 密钥存在于 `astrbot-napcat/credentials.json` 和各插件配置中，注意不要泄露

## Agent skills

### Issue tracker

Issues 作为 markdown 文件存放在 `.scratch/<feature-slug>/` 中。See `docs/agents/issue-tracker.md`.

### Triage labels

使用五个 canonical triage role 的默认名称：`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`。See `docs/agents/triage-labels.md`.

### Domain docs

Single-context 布局：根目录 `CONTEXT.md` + `docs/adr/`。See `docs/agents/domain.md`.
