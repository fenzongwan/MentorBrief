# Mentor Brief · 导师简报

本地优先的微信聊天总结与朋友圈关注提醒工具。支持导入 WeFlow 聊天/朋友圈数据、生成结构化摘要、追踪指定联系人动态，并在发送给外部模型前做名称与联系方式脱敏。

> 当前为 v1.2 测试版。程序目录不可写时会自动把数据库放到 `%LOCALAPPDATA%\MentorBrief\data`，避免 `readonly database` 问题。

## 功能

- 聊天 JSON/CSV 导入、会话搜索和时间范围选择
- 要点、待办、约定和链接的一键总结
- 发送前人名、手机号、邮箱和 `wxid` 脱敏
- 总结结果与原始消息对照
- 朋友圈关注名单、新增动态识别和时间线
- 本地审计日志，不记录消息原文
- OpenAI 兼容接口，也支持无需 API Key 的本地规则总结
- WeFlow 本地缓存统计与周期同步脚本

## 快速启动

需要 Windows 10/11 和 Python 3.10+。

```powershell
git clone <repository-url>
cd MentorBrief
python .\start-demo.bat
```

浏览器打开 <http://127.0.0.1:8765>。

首次启动会初始化脱敏演示数据，之后启动会保留数据库、API 配置、导入数据和关注名单。

### 演示顺序

1. 双击 `start-demo.bat`。
2. 浏览器打开 <http://127.0.0.1:8765>。
3. 默认进入「沟通简报」，看预置简报，点「生成提纲」。
4. 点「消息总结」选择「导师 · 周老师」。
5. 点「行动清单」勾选/新增跟进事项。
6. 点「关注动态」看关注对象动态。

详细操作见 [使用说明.md](使用说明.md)，项目背景见 [介绍.md](介绍.md)，技术方案见 [ARCHITECTURE.md](ARCHITECTURE.md)，原理讲解见 [技术详解.md](技术详解.md)，答辩准备见 [点评与答辩.md](点评与答辩.md)，路演材料见 `导师简报-项目介绍.pptx`。

## 开发模式

双击 `start-demo.bat`，或在项目目录执行：

```powershell
python .\server.py
```

数据库默认保存在项目的 `data\weflow-assistant.db`。如果项目目录不可写（例如解压到 `Program Files`、只读共享盘或权限受限目录），程序会自动把数据库迁移到 `%LOCALAPPDATA%\MentorBrief\data\weflow-assistant.db`。无需手动修改目录权限。

访问 <http://127.0.0.1:8765>。

项目只使用 Python 标准库。提交前可执行：

```powershell
python -m py_compile *.py
```

参与方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)。

## 使用流程

1. 先在“关注动态”页添加关注对象，填写 `wxid` 或导出数据中的稳定 ID。
2. 在“消息总结”页导入聊天记录 JSON/CSV。导入后选择群聊、时间范围，点击“一键总结”。
3. 在“关注动态”页导入朋友圈 JSON/CSV，只保留关注名单中的作者，新增动态会高亮并显示角标。
4. 审计日志记录每次导入和模型请求的范围、条数、脱敏状态，不记录消息原文。

可先用 `sample/sample-chats.json` 和 `sample/sample-moments.json` 试跑。试跑朋友圈前，先把关注 ID 填为 `wxid_teacher`。
演示建议：先导入聊天记录，选中“项目协作群”，时间范围切到“全部”，点击“一键总结”，再点任意“查看原文”；随后导入朋友圈并展示新增角标。

## 真实 WeFlow 缓存同步

除了文件导入，现在可以直接读取 WeFlow 的本地缓存：

```powershell
# 先看统计，不打印消息内容
python .\weflow_cache.py --stats

# 首次同步
python .\weflow_sync.py --once

# 持续监听缓存变化
python .\weflow_sync.py --loop --interval 30
```

缓存位置默认是 `%APPDATA%\weflow\cache`。同步逻辑只读 `contacts.json` 和 `session-messages.json`，不读取 `WeFlow-config.json` 里的解密密钥。

更多命令见 [DSH.md](DSH.md) 和 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 数据格式

导入器会递归识别聊天消息和朋友圈记录。朋友圈导出优先读取 WeFlow 的顶层 `posts` 数组，支持 `contentDesc` 正文和 `media[].localPath/url/thumb` 图片。常见字段别名包括：

- 聊天：`chatName/groupName`、`senderName/nickname`、`wxid`、`time/createTime`、`content/text`、`type/msgType`
- 朋友圈：`authorId/wxid`、`authorName/nickname`、`createdAt/createTime`、`content/text/description`、`images/mediaPaths`

如果真实 WeFlow 导出字段不同，只需要调整 `server.py` 中 `normalize_message` / `normalize_moment` 的字段别名。

## 模型接口

默认使用本地规则总结，无需 API key。也可以切换到任何 OpenAI 兼容接口，例如：

```text
https://api.openai.com/v1
```

配置后填写 API key 和模型名即可。请求由本地服务代理，页面不会直接暴露 key。

## 隐私边界

- API key 保存在本机 SQLite。
- 默认把成员名替换为“成员 A / 成员 B”，并脱敏手机号、邮箱、wxid。
- 审计日志只记录范围和数量，不记录原文。
- 原文对照默认沿用脱敏设置；显示原名时页面会先弹确认。

## 数据流向

```text
WeFlow 导出文件
  -> 本地导入器字段识别与标准化
  -> SQLite（消息 / 朋友圈 / 关注名单 / 审计）
  -> 页面展示或总结服务
  -> OpenAI 兼容接口（仅发送脱敏后的消息文本）
```

## 已知限制

- 不直连 WeFlow HTTP API；采集依赖 WeFlow 导出文件或本地缓存。
- 图片只展示路径占位，不加载本地解密文件。
- 朋友圈新增提醒是应用内提醒，不做 Windows 原生弹窗。
- 朋友圈不是实时监控；WeFlow 无法自动导出时，需要手动导入后再识别新增动态。
- 真实 WeFlow 导出字段可能与示例不同；如无法识别，可在设置页查看导入失败提示，然后按 README 的字段别名调整解析器。
- WeFlow 解密后的图片文件目前只显示路径占位，不加载原图。

## 数据与隐私

数据库和 API Key 默认只保存在本机。请只处理你有权访问的数据，不要提交真实聊天记录、数据库、日志或 API Key。详见 [SECURITY.md](SECURITY.md)。
