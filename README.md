# 知研 · 科研文献简报

知研帮助你追踪智能体长期记忆、长期记忆治理、用户建模与个性化、自动科研智能体和生产力增强等研究。它通过 OpenAlex、Crossref、arXiv 检索开放学术元数据；配置 Semantic Scholar API key 后也会检索 Semantic Scholar。

检索覆盖受各索引收录、主题词和分页范围限制，不承诺包含世界上所有论文。每条结果尽量提供题名、作者、摘要、来源、日期、标识符/DOI、类型、评审状态线索、相关性说明和来源链接。系统展示元数据与获准的开放获取链接，不下载或再发布受版权保护的论文全文。

## 本地运行完整应用

需要 Python 3.9 或更新版本；不需要安装第三方 Python 包。

```sh
python3 server.py
```

在浏览器打开 <http://127.0.0.1:8787>。首次启动会检查当天简报并在需要时开始检索。服务保持运行时会每天更新一次，也可以点“立即更新”。关闭服务或电脑休眠期间不会检索、推送或更新；重新启动后调度器会按当天状态补做检索。结果、API 响应缓存和“有关/无关”反馈保存在 `work/digest.sqlite3`，阅读标记保存在当前浏览器。

## 配置可选 API 凭据

API 凭据只从环境变量读取。不要将密钥写进源代码、Netlify 前端或 GitHub 仓库。

macOS / Linux（zsh）：

```sh
export OPENALEX_API_KEY='你的 OpenAlex key'
export CROSSREF_MAILTO='你的联系邮箱'
export SEMANTIC_SCHOLAR_API_KEY='你的 Semantic Scholar key'
python3 server.py
```

Windows PowerShell：

```powershell
$env:OPENALEX_API_KEY='你的 OpenAlex key'
$env:CROSSREF_MAILTO='你的联系邮箱'
$env:SEMANTIC_SCHOLAR_API_KEY='你的 Semantic Scholar key'
python server.py
```

OpenAlex、Crossref 和 arXiv 不要求配置个人密钥；Semantic Scholar 在未设置密钥时会跳过。OpenAlex 和 Semantic Scholar 密钥通过请求头发送；Crossref 的 `CROSSREF_MAILTO` 是联系邮箱，不是密钥。SQLite 缓存键会对请求地址做哈希，并剔除密钥/邮箱字段。

## 用 GitHub + Netlify 部署在线版

将本 `research-digest` 文件夹里的内容作为 GitHub 仓库根目录，然后在 Netlify 选择 **Add new project → Import an existing project** 并连接仓库。`netlify.toml` 已把发布目录设为 `site`，构建命令留空即可。网页从 `site/digest.json` 加载简报，搜索、筛选、排序和标记都在浏览器内完成。

每日检索由仓库中的 GitHub Actions 工作流运行：它调用 OpenAlex、Crossref、arXiv，以及配置后可选的 Semantic Scholar，生成新的 `site/digest.json` 并提交回仓库；Netlify 看到这个提交后自动发布新简报。页面打开与否不会影响定时任务。工作流计划在北京时间约 01:17 启动；GitHub 可能延迟计划任务，不保证精确到分钟。代码推送也会触发一次更新，便于首次生成和修改主题后刷新。

在 GitHub 仓库设置中，确认 Actions 获准写入仓库内容（**Settings → Actions → General → Workflow permissions → Read and write permissions**）。可选凭据添加到 **Settings → Secrets and variables → Actions**：`OPENALEX_API_KEY`、`CROSSREF_MAILTO`、`SEMANTIC_SCHOLAR_API_KEY`。OpenAlex、Crossref、arXiv 无需密钥；不配置 Semantic Scholar 密钥时会跳过该来源。密钥只作为 Actions 运行环境变量，不提交进代码。初次部署先发布空白等待状态；也可在 GitHub 的 **Actions → Daily research digest → Run workflow** 手动启动首次检索。工作流成功后提交的数据会触发 Netlify 发布。

本地运行仍使用 `python3 server.py`，不依赖 GitHub Actions。在线版反馈和阅读标记保存在各自浏览器的本地存储，不会同步给其他访问者；本地版的相关性反馈保存在本机 SQLite 数据库。

## 检索和排序

- 每个主题向各来源查询并分页；首版主要保留 2024 年以来的记录，方向和检索词在 `server.py` 的 `TOPICS` 中维护。
- 程序使用 SQLite 缓存 API 响应，识别 429/5xx 后退避重试。Crossref 请求按有无 `mailto` 控制频率；arXiv 连续请求之间等待至少 3 秒。
- 相关性根据标题、摘要和主题词排序；“有关/无关”反馈会在本机数据库中调整后续排序，不代表论文质量判断。
- 预印本和已发表记录分开标注。各来源不一定提供同行评审证据，无法核实时会显示“未知”或“未核实”。
- Crossref 直达全文链接仅在元数据明确列出 Creative Commons 许可时显示；其他条目保留 DOI 或来源记录链接。OpenAlex、Semantic Scholar 和 arXiv 提供开放获取链接时会展示其链接。

## 官方 API 文档

- [OpenAlex 认证、速率限制与 API 使用建议](https://help.openalex.org/api/authentication/)
- [Crossref API 认证、速率限制与请求建议](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/) · [REST API 使用建议](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)
- [arXiv API 用户手册与分页/请求间隔说明](https://info.arxiv.org/help/api/user-manual.html)
- [Semantic Scholar API 参考](https://api.semanticscholar.org/api-docs/)
- [Netlify 从 Git 仓库导入和自动部署](https://docs.netlify.com/manage/projects/add-new-project/)
- [GitHub Actions 定时工作流](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Netlify Scheduled Functions 与函数执行时限](https://docs.netlify.com/build/functions/configuration/?fn-language=js)
