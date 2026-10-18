# Mentor Radar / 导师雷达：完整方案

> 目标：在**不把个人微信/QQ 登录进第三方 Web 应用**的前提下，把 WeFlow 已经导出的数据变成导师信号、群聊日报、朋友圈提醒和日程待办，并接入 DSH。
>
> 一句话：**WeFlow 负责采集，队友的 Assistant 负责分析，DSH 负责提醒和对话入口。**

---

## 1. 三层架构

```text
┌──────────────────────────────────────────────────────────────┐
│ 采集层：WeFlow                                                │
│  - 登录/解密由 WeFlow 自己完成                                 │
│  - 输出 %APPDATA%\weflow\cache\contacts.json                  │
│  - 输出 %APPDATA%\weflow\cache\session-messages.json          │
│  - 本方案不读取 WeFlow-config.json 里的 decryptKey             │
└──────────────────────────────┬───────────────────────────────┘
                               │ 本地文件
┌──────────────────────────────▼───────────────────────────────┐
│ 分析层：WeFlow Assistant                                      │
│  - weflow_cache.py：缓存 → 标准消息模型                       │
│  - weflow_sync.py：增量导入 + 新消息提醒 + 自动清理            │
│  - server.py：SQLite、群聊总结、朋友圈关注、审计               │
│  - dsh_bridge.py：日报、状态、关注名单、群聊总结               │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP / CLI
┌──────────────────────────────▼───────────────────────────────┐
│ 入口层：DSH                                                   │
│  - 对话式查询：今天导师说了什么？                              │
│  - 定时提醒：08:00 早报、21:00 晚报、03:00 清理                │
│  - 后续可以包成 client plugin / 侧边栏                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 封号风险：必须说清楚

### 2.1 风险的真正位置

本方案分成两段：

| 环节 | 是否接触微信/QQ | 风险 |
|---|---|---|
| WeFlow 登录、解密本地数据库 | 是 | **高**。它是第三方工具，不是微信官方授权 |
| 本方案读取 WeFlow 缓存 | 否 | 不增加新的平台交互风险 |
| 本方案 Web/API/DSH | 否 | 不登录、不注入、不自动发送 |

所以：

- **不能说“整个方案绝对不会被封”**。风险主要在 WeFlow 的采集方式。
- 可以说：“我们的应用零注入、零登录、零自动发送，只消费 WeFlow 的本地缓存；采集端的风险被隔离在 WeFlow。”
- 如果比赛要求“完全无风险”，只能走企业微信会话存档、QQ 官方机器人、用户手动导出；个人微信朋友圈没有官方 API。

### 2.2 本方案刻意不做

- 不读取 `WeFlow-config.json` 的 `decryptKey`、`imageXorKey`、`imageAesKey`
- 不直接解密微信数据库
- 不模拟点击、不自动滚动朋友圈
- 不自动发送消息、不自动加好友
- 不把原始聊天记录上传云端
- 不实现任何“防封/绕过检测”逻辑

### 2.3 朋友圈的边界

当前 WeFlow 缓存里能确认的是**联系人和聊天消息**，没有发现 Moments/SNS 缓存文件。因此：

- 聊天消息：可以自动增量同步。
- 朋友圈：仍走「导入朋友圈 JSON/CSV」，格式与队友 demo 一致。
- 如果后续 WeFlow 提供朋友圈导出/API，再增加 `weflow_moments.py` adapter；不建议为朋友圈去做 UI 自动浏览。

---

## 3. WeFlow 缓存格式

本机 WeFlow 的缓存目录：

```text
%APPDATA%\weflow\cache\
├── contacts.json
├── session-messages.json
├── session-stats.json
└── group-my-message-counts.json
```

### 3.1 contacts.json

结构：

```json
{
  "wxid_or_chatroom_id": {
    "displayName": "显示名",
    "avatarUrl": "...",
    "updatedAt": 1234567890
  }
}
```

用途：

- 把 `chatroom_id` 映射成群名
- 把 `senderUsername` 映射成发送者显示名
- 不包含备注名/手机号等额外字段

### 3.2 session-messages.json

结构：

```json
{
  "session_id": {
    "updatedAt": 1234567890,
    "messages": [
      {
        "messageKey": "...",
        "localId": 1,
        "serverId": 2,
        "localType": 1,
        "createTime": 1234567890,
        "isSend": 0,
        "senderUsername": "wxid_xxx",
        "parsedContent": "文本内容",
        "linkTitle": "",
        "linkUrl": "",
        "appMsgDesc": "",
        "xmlType": ""
      }
    ]
  }
}
```

关键字段：

- `messageKey`：稳定消息 ID，用于去重
- `createTime`：Unix 秒
- `isSend`：1 表示自己发送
- `senderUsername`：发送者 wxid
- `parsedContent`：已解析的文本
- `linkTitle` / `linkUrl`：链接消息
- `appMsgDesc`：应用消息描述
- `localType`：微信消息类型，高 32 位可能带 flag，取 `localType & 0xFFFFFFFF`

### 3.3 类型映射

| base type | 含义 | 本项目类型 |
|---|---|---|
| 1 | 文本 | text |
| 3 | 图片 | image |
| 34 | 语音 | voice |
| 43 | 视频 | video |
| 47 | 表情 | emoji |
| 49 | 应用/链接/文件 | link 或 file |
| 50 | 通话 | call |
| 10000 | 系统 | system |

---

## 4. 新增模块

### 4.1 `weflow_cache.py`

职责：只读缓存，转换成 Assistant 的导入格式。

```powershell
python .\weflow_cache.py --stats
python .\weflow_cache.py --out data\weflow-chats.json
python .\weflow_cache.py --out data\weflow-groups.json --groups-only
```

输出格式：

```json
[
  {
    "chatId": "xxx@chatroom",
    "chatName": "群名",
    "chatType": "group",
    "messages": [
      {
        "msgId": "...",
        "senderName": "显示名",
        "wxid": "wxid_xxx",
        "time": "2026-09-13T21:42:13+08:00",
        "type": "text",
        "content": "..."
      }
    ]
  }
]
```

设计点：

- 默认排除公众号和 openim，避免把服务号消息混进群聊总结。
- `--groups-only` / `--direct-only` 可控制范围。
- `--since` 支持 epoch 秒或 ISO 时间。
- 不输出 `rawContent`，避免 XML 和无关内容进入数据库。
- 不读取 `WeFlow-config.json`。

### 4.2 `weflow_sync.py`

职责：增量同步 + 新消息提醒 + 可选清理。

```powershell
# 首次导入（bootstrap，不把历史消息当新提醒）
python .\weflow_sync.py --once

# 持续监听
python .\weflow_sync.py --loop --interval 30

# 只同步群聊，并打印关注对象的新消息
python .\weflow_sync.py --once --groups-only --print-alerts

# 新消息写入 JSONL
python .\weflow_sync.py --loop --interval 30 --alerts-out data\alerts.jsonl

# 同步后清理 30 天前的原始消息
python .\weflow_sync.py --loop --interval 30 --cleanup-days 30
```

状态文件：

```text
data/weflow_sync_state.json
```

保存每个会话已经见过的 `messageKey`。第一次运行没有状态文件，视为 bootstrap；只导入，不把历史消息当成“新提醒”。

### 4.3 `maintenance.py`

```powershell
python .\maintenance.py cleanup --days 30 --dry-run
python .\maintenance.py cleanup --days 30
```

### 4.4 `dsh_bridge.py`

```powershell
python .\dsh_bridge.py status
python .\dsh_bridge.py watch --id wxid_teacher --name 陈老师
python .\dsh_bridge.py daily
python .\dsh_bridge.py daily --date today --out reports\morning.md
python .\dsh_bridge.py summarize --conversation "项目协作群" --range all
```

日报结构：

1. 导师消息
2. 导师简报
3. 下次回复提纲
4. 导师动态
5. 群聊摘要
6. 行动清单
7. 数据说明

`daily` 会同时读取 `/api/reports/mentor`、`/api/reply-outline`、`/api/todos?status=open`；没有这些数据时自动降级，不会报错。

---

## 5. 数据库与自动清理

### 5.1 现有表

- `conversations`
- `messages`
- `moments`
- `watchlist`
- `summaries`
- `mentor_reports`
- `todos`
- `reply_outlines`
- `audit_log`
- `app_settings`

### 5.2 行动清单与回复提纲 API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/todos?status=open` | 读取待办 |
| POST | `/api/todos` | 新增跟进事项 |
| PATCH | `/api/todos/{id}` | 标记完成/恢复待办 |
| GET | `/api/reply-outline?conversationId=...` | 读取最近一份回复提纲 |
| POST | `/api/reply-outline` | 基于导师简报生成/返回回复提纲 |

`reply_outlines` 存的是结构化 JSON：

- `goal`
- `mustAnswer`
- `structure`（开场/回应/推进/追问）
- `keyPoints`
- `avoid`
- `draft`

回复提纲只生成草稿，不自动发送。

### 5.3 清理策略

默认 `retentionDays = 30`。

`POST /api/maintenance/cleanup`：

```json
{
  "retentionDays": 30,
  "dryRun": true
}
```

行为：

- 删除 `sent_at < cutoff` 的原始消息
- 保留 `summaries`（日报/群摘要）
- 写入 `audit_log`，只记录条数和时间范围，不记录原文
- `PRAGMA secure_delete = ON`，删除后尽量覆盖页内容

推荐定时：

```text
每天 03:00  python maintenance.py cleanup --days 30
```

### 5.4 后续增强

- 对话级 `retention_days`
- 置顶/法务保留
- 删除前加密归档
- 附件单独 TTL
- 定期 `VACUUM`

---

## 6. DSH 集成

### 6.1 最小可用

DSH 直接运行 CLI：

```text
python weflow_sync.py --once
python dsh_bridge.py daily --date today
```

### 6.2 定时任务

| 时间 | 命令 | 产出 |
|---|---|---|
| 每 5 分钟 | `python weflow_sync.py --once` | 增量入库 |
| 08:00 | `python dsh_bridge.py daily --date today` | 早报 |
| 21:00 | `python dsh_bridge.py daily --date today` | 晚报 |
| 03:00 | `python maintenance.py cleanup --days 30` | 清理 |

### 6.3 对话式查询

用户在 DSH 里说：

> 今天导师和群里有什么需要我处理的？

DSH 可以：

1. 运行 `python dsh_bridge.py daily --json`
2. 或者分别调用 `status`、`daily`、`summarize`
3. 把结果整理成自然语言

### 6.4 后续插件化

- DSH client plugin：侧边栏嵌入 `http://127.0.0.1:8765`
- 或把 `dsh_bridge.py` 包成 DSH tool/MCP server
- 当前先保持 CLI，稳定后再做插件，避免被 DSH 版本/协议绑定

---

## 7. 日报与提醒的产品逻辑

### 7.1 早报（08:00）

- 昨天 18:00 之后到现在的导师消息
- 新增朋友圈
- 昨天群聊摘要/待办
- 今天截止的任务
- 建议回复（只生成草稿，不自动发送）

### 7.2 晚报（21:00）

- 今天各群摘要
- 未完成待办
- 明天需要准备的事项
- 导师未回复的问题

### 7.3 即时提醒

触发条件：

- 导师私聊
- 群里 @我
- 导师消息包含“截止/提交/明天/今天/报名/会议”
- 朋友圈新增（可选）

去重与降噪：

- 同一导师 10 分钟内只提醒一次
- 免打扰时段
- 普通消息进日报，不即时弹窗

---

## 8. 文件地图

```text
weflow-assistant-demo-v0.1/
├── server.py              # 原 demo + retention + mentor report + todos + reply outline
├── wechat_text.py         # 微信文本导出 → 标准 JSON（支持脱敏）
├── weflow_cache.py        # WeFlow 缓存 → 标准 JSON
├── weflow_sync.py         # 增量同步 + 提醒 + 清理
├── dsh_bridge.py          # DSH CLI：status/daily/watch/summarize/import
├── maintenance.py         # 清理 CLI
├── seed_demo.py           # 预置脱敏导师聊天、群聊、朋友圈、简报、待办、回复提纲
├── DSH.md                 # DSH 使用说明
├── ARCHITECTURE.md        # 本文件
├── 介绍.md                 # 项目介绍
├── 技术详解.md             # 给非科班队友的技术讲解
├── 点评与答辩.md           # 自评、风险、Q&A
├── 导师简报-项目介绍.pptx    # 路演 PPT
├── start-demo.bat         # 一键启动（ASCII + CRLF）
├── sample/
│   ├── sample-chats.json
│   └── sample-moments.json
├── static/                # UI：沟通简报 / 消息总结 / 行动清单 / 关注动态 / 设置
└── data/
    ├── mentor-chat.json
    ├── mentor-brief.json
    ├── reply-outline.json
    ├── demo-moments.json
    ├── weflow-assistant.db
    └── weflow_sync_state.json
```

---

## 9. QQ 怎么办

QQ 不能直接复用微信缓存。建议：

1. **QQ 群**：QQ 开放平台官方机器人；只能拿机器人可见的消息，需要群主添加/审核。
2. **QQ 私聊/QQ 空间**：没有官方 API；UI 自动化/Hook 风险高，不建议放进主流程。
3. **比赛 demo**：微信为主，QQ 留 `QQAdapter` 接口和一张架构图；不要为了“全支持”引入高风险模块。

---

## 10. 比赛演示脚本

### 10.1 3 分钟版本

1. 打开 `http://127.0.0.1:8765`。
2. 默认「沟通简报」：展示关键信号、待办、下次回复提纲。
3. 点「生成提纲」，说明“只生成草稿，不自动发送”。
4. 点「行动清单」，勾选一条待办，再新增一条跟进。
5. 打开「消息总结」，选一个群，点“一键总结”，点“查看原文”。
6. 运行 `python dsh_bridge.py daily`，展示导师消息、简报、回复提纲、群摘要、行动清单。
7. 展示自动清理：`python maintenance.py cleanup --days 30 --dry-run`。
8. 展示 DSH 提醒配置：08:00 早报 / 21:00 晚报。

### 10.2 答辩要点

- 采集层可插拔：WeFlow / 导出文件 / 官方接口。
- 应用层零注入、零登录、零自动发送。
- 日报带原文引用，防幻觉。
- 存档有 TTL 和审计，隐私可控。
- WeFlow 的风险不被包装成“官方授权”。

---

## 11. 已知限制

1. WeFlow 缓存只覆盖聊天，不覆盖朋友圈；朋友圈仍要导入 JSON/CSV。
2. WeFlow 缓存是否实时更新取决于 WeFlow 自身；`weflow_sync.py` 只是轮询文件变化。
3. 群聊总结默认使用本地规则；接大模型需要在设置页配置 OpenAI 兼容接口。
4. 当前 demo 的“关注名单”同时服务导师消息和朋友圈；产品化时应拆成两个名单。
5. 日报读取最近一次群摘要；要全自动，需要在日报任务前对选定群调用 `summarize`。
6. 导师简报和回复提纲在 demo 中是人工校对/规则生成；真实使用可接模型，但要保留引用和人工确认。
7. 待办清单目前是本地状态，不发提醒；后续可接 DSH 或 Windows Toast。
8. QQ 仅保留 adapter 设计，未实现。

---

## 12. 推荐下一步

1. 用真实 WeFlow 缓存跑一次 `weflow_sync.py --once`，确认会话/消息数量。
2. 在“关注动态”添加导师，导入一份朋友圈 JSON。
3. 对目标群执行一次 `summarize`，再生成 `daily`。
4. 用 DSH 建 08:00/21:00 两个提醒。
5. 如果 WeFlow 能导出朋友圈，补 `weflow_moments.py`；否则保持手动导入。
