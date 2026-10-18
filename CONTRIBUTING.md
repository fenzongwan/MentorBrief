# 参与开发

感谢参与 Mentor Brief。项目当前使用 Python 标准库，不依赖第三方 Python 包。

## 本地运行

```powershell
git clone <repository-url>
cd MentorBrief
python .\start-demo.bat
```

也可以直接启动服务：

```powershell
python .\server.py
```

然后访问 <http://127.0.0.1:8765>。

## 开发约定

1. 从 `main` 创建功能分支，例如 `feature/moments-filter`。
2. 修改后至少运行 `python -m py_compile *.py`，并手动检查受影响页面。
3. 提交前确认没有把真实数据库、日志、聊天导出或 API Key 加入 Git。
4. 提交说明使用简短的祈使句，例如 `Add moments author filter`。
5. 通过 Pull Request 合并，不直接向 `main` 强推。

## 数据安全

- 只提交 `sample/` 或已明确脱敏的演示数据。
- 不要提交 `data/weflow-assistant.db`、`*.log`、`.env` 或个人 API Key。
- 不要在 Issue、PR 或截图中粘贴真实聊天内容和个人信息。
- 新增外部模型接口时，应保留发送前脱敏和审计记录。

## 添加共同作者

仓库创建后，由仓库所有者在 GitHub 的 `Settings -> Collaborators` 中邀请对方。若使用 GitHub CLI：

```powershell
gh api --method PUT repos/OWNER/REPOSITORY/collaborators/USERNAME -f permission=push
```

对方接受邀请后即可推送分支和提交 Pull Request。
