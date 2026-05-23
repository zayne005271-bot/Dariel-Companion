# Dariel Companion

QQ 聊天机器人接入 Claude Code 的完整教程与插件集合。

## 项目结构

```
├── README.md              # 本文件
├── docs/
│   └── qq-claude-bridge.md   # QQ ↔ Claude Code 桥接教程
├── plugins/
│   └── qzone-publisher/      # QQ空间说说发布插件
└── scripts/
    └── auto-share.py         # 自动上网分享内容脚本
```

## 快速开始

详见 `docs/qq-claude-bridge.md`

## 组成部分

- **NapCat** — QQ 协议适配器 (Docker)
- **AstrBot** — 聊天机器人框架
- **Claude Code MCP** — AI 接入层
- **qq_bridge.py** — WebSocket 桥接脚本

## 作者

zayne005271-bot & Dariel
