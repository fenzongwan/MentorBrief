# 接入 DSH（DeepSeek Harness）

`dsh_bridge.py` 是 WeFlow Assistant 和 DSH 之间的薄桥接层，只使用 Python 标准库：

- 不登录微信/QQ
- 不注入客户端
- 不自动发送消息
- 只调用本机 `http://127.0.0.1:8765` 的 HTTP API

## 1. 先启动服务

```powershell
python .\server.py
```

## 2. 从 WeFlow 本地缓存同步真实数据

WeFlow 会把已解密的会话写入：

```text
%APPDATA%\weflow\cache\contacts.json
%APPDATA%\weflow\cache\session-messages.json
```

先看统计（不会打印消息内容）：

```powershell
python .\weflow_cache.py --stats
```

输出里会包含 `cacheUpdatedAt` 和 `cacheAgeSeconds`，用来判断 WeFlow 缓存是否新鲜。如果 `cacheAgeSeconds` 很大，说明 WeFlow 没在跑或没刷新。

首次同步：

```powershell
python .\weflow_sync.py --once
```

持续监听缓存变化（30 秒一次）：

```powershell
python .\weflow_sync.py --loop --interval 30
```

只同步群聊，并在有新消息时输出提醒：

```powershell
python .\weflow_sync.py --once --groups-only --print-alerts
```

把提醒写入 JSONL，供 DSH 或其他程序读取：

```powershell
python .\weflow_sync.py --loop --interval 30 --alerts-out data\alerts.jsonl
```

> 第一次同步是 bootstrap，会把历史消息导入，但不会把历史消息当成“新提醒”。之后新增的消息才会触发 alerts。

## 3. 常用命令

```powershell
# 查看服务状态
python .\dsh_bridge.py status

# 生成日报（Markdown 输出到终端）
python .\dsh_bridge.py daily

# 生成日报并写入文件
python .\dsh_bridge.py daily --out reports\daily.md

# 只生成某一天
python .\dsh_bridge.py daily --date 2026-10-18
python .\dsh_bridge.py daily --date today

# 添加关注对象
python .\dsh_bridge.py watch --id wxid_teacher --name 陈老师

# 导入 WeFlow 导出文件
python .\dsh_bridge.py import-chats --file sample\sample-chats.json
python .\dsh_bridge.py import-moments --file sample\sample-moments.json

# 总结群聊
python .\dsh_bridge.py summarize --conversation "项目协作群" --range all
```

如果服务不在默认端口：

```powershell
python .\dsh_bridge.py --base-url http://127.0.0.1:8766 daily
```

## 4. 消息存档自动清理

```powershell
# 预览将删除多少条
python .\maintenance.py cleanup --days 30 --dry-run

# 真正删除 30 天前的原始消息
python .\maintenance.py cleanup --days 30
```

同步时顺带清理：

```powershell
python .\weflow_sync.py --loop --interval 30 --cleanup-days 30
```

## 5. 在 DSH 里怎么用

直接让 DSH 运行命令，例如：

> 运行 `python weflow_sync.py --once`，然后运行 `python dsh_bridge.py daily`，把输出整理成今天的每日沟通摘要。

或者用 DSH 的定时提醒：

- 每 5 分钟：`python weflow_sync.py --once`
- 每天 08:00：`python dsh_bridge.py daily --date today --out reports\morning.md`
- 每天 21:00：`python dsh_bridge.py daily --date today --out reports\evening.md`
- 每天 03:00：`python maintenance.py cleanup --days 30`

DSH 负责“什么时候提醒、怎么呈现”，脚本负责“从本地服务取数据并生成 Markdown”。

## 6. 当前日报包含

- 导师消息
- 导师简报（关键信号 / 行动项）
- 下次回复提纲（目标 / 必须回应 / 结构 / 草稿）
- 导师动态
- 群聊摘要（要点/待办/约定）
- 行动清单（未完成待办）
- 数据统计和隐私说明

## 7. UI 对应页面

- 沟通简报：导师简报 + 指标 + 回复提纲
- 消息总结：会话、消息、群聊总结、原文对照
- 行动清单：待办勾选、新增、筛选
- 关注动态：关注名单、朋友圈动态
- 设置：模型、脱敏、审计

## 8. 边界

- 这些脚本不采集微信/QQ 数据，只消费 WeFlow 已经写入本地缓存的数据。
- WeFlow 的登录、数据库解密、Hook/协议风险不在这些脚本里，也不能由它们承诺“免封”。
- 如果要更实时，建议用 `weflow_sync.py --loop` 监听 WeFlow 缓存；不要做个人微信扫码登录到第三方 Web 应用。
