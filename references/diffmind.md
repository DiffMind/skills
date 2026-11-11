# DiffMind接入说明

## 接入前提

Skill 只提供连接流程，不包含后端服务。

- 默认 MCP 地址：`https://mcp.diffmind.ai/mcp/open`；默认连接名称：`diffmind-open`。
- 对应 OAuth issuer：`https://mcp.diffmind.ai/mcp/oauth`。服务发现与 OAuth 由服务端启用，所有公开端点使用 HTTPS。
- 官网登录与授权确认页由服务端的 OAuth 流程引导打开，本 Skill 不猜测或写死官网授权页域名。
- 用户须有目标服务可用的 DiffMind 账号；不同服务的账号、配置和授权不可假定互通。
- 服务不可达时报告实际连接错误，不在用户电脑启动后端，也不自动切换其他服务。

## 身份和凭据

按 [connection.md](connection.md) 的固定客户端分流：WorkBuddy、豆包使用配对码；Codex、Cursor、Claude 使用各自原生 OAuth。

OAuth 路径由当前客户端登记、生成回调、换取凭据、保存和刷新；用户在浏览器确认。不手工复制其他客户端凭据，不自行拼接授权 URL。配对路径仅用于 WorkBuddy、豆包，并在安全通路完整时，按 [pairing.md](pairing.md) 兑换一次性码并由智能体保护返回的凭据。

两种方式都不索取密码、Cookie 或长期访问令牌，不展示或记录 Token 值。必要的连接配置和审批如实告知，不强制静默写入，不承诺其他客户端已经登录等于当前客户端可用。费用确认与身份授权分开。
## 开放工具

| 工具 | OAuth scope | 参数与限制 |
| --- | --- | --- |
| diffmind_web_search | web:search | query 必填；maxResults 可选，具体范围看实际 schema |
| diffmind_paper_search | web:search | request.query、request.clientRequestId；标准文献检索，返回searchNo |
| diffmind_paper_ai_search | web:search | 自然语言文献检索，服务端规划概念/同义词/作者/年份；按原规则计附加费，使用原searchNo查询 |
| diffmind_paper_search_result | web:search | 原searchNo；快照分页与筛选，不重复检索；filteredCount为全部条件匹配数，snapshotFacets.languages为完整快照语种分布 |
| diffmind_paper_detail | web:search | 原searchNo、paperKey；仅完整摘要 |
| diffmind_paper_filter_options | web:search | 只读筛选选项 |
| diffmind_paper_download_estimate | web:search | 只传希望下载的篇数；下载前必须先调用。大于10篇且不超过20篇须用户确认预估点数。大于20篇拒绝，禁止确认下载或改成20篇 |
| diffmind_paper_download | web:search | 原searchNo、paperKey；预估通过后逐篇申请一次性下载链接 |
| diffmind_compare_tasks | model:chat | 只读返回当前限制、账号占用数及本 OAuth 应用的运行批次 |
| diffmind_models_resolve | model:chat | 名称解析为有权使用的别名；同名需明确选择，不返回模型 ID |
| diffmind_models_list | model:chat | 有权使用的模型别名、展示名 |
| diffmind_compare_chat | model:chat | 本次任务的 messages、明确模型及 clientRequestId，按服务端 limits 校验 |
| diffmind_compare_result | model:chat | 原 taskId 和真正展示后的累计 displayedModelAliases |
| diffmind_compare_cancel | model:chat | 原 taskId；可指定本批次 modelAliases，省略为整批取消 |

实际下载按账号每秒仅放行一次，与聊天提交分别计数；HTTP429表示本次未启动下载，原票据在有效期内可稍后重试。不要立即循环重试或并发打开多个下载链接；用户确认批量下载时，依次执行并遵循服务端限流提示。

联网检索只使用上表里的搜索工具，并且只调用当前连接实际列出的工具。权限只决定这次调用是否允许，不用来切换地址或认证方式。当前没有列出全部知识库文档的工具。工具执行可能扣除用户点数，不用实际搜索充当连接探活。

## 排障

| 现象 | 检查与处理 |
| --- | --- |
| https://mcp.diffmind.ai 不可达 | 检查目标服务、域名解析和网络连接；不自动切换其他服务 |
| metadata 返回 503 或 OAuth 未启用 | 请服务维护者检查登录是否已开启；Skill 不绕过鉴权 |
| metadata 返回 HTML/404 | 地址或网关路由错误，不能把网页响应当 OAuth JSON |
| 注册/兑换 token 返回存储错误 | 这是服务端故障，请联系维护者；不要向用户索取密码、Token 或日志 |
| “不支持身份验证” | 先检查实际服务 URL、401 discovery 和元数据；不能仅凭 UI 文案判断端口错误 |
| “未经身份验证” | 按 connection.md 的固定客户端分流进入原生 OAuth 或安全配对。导入技能或新增配置本身不等于已经可用 |
| 授权页面 JS/CSS 404，一直加载 | 授权页资源加载失败，请维护者处理；不持续重试授权码 |
| invalid_grant / 旧 client_id 无效 | 可能是凭据到期、重放撤销或服务升级；重新登录。已确认旧登记失效时可新增未占用的服务器名称触发 DCR，不删除无关配置 |
| 登录成功但当前会话无工具 | 先发现工具并使用智能体可用的刷新能力；仅 Codex 可使用专用后备脚本，其他智能体按各自接入说明处理，不借用 Codex 授权 |
| 工具未直接显示 | 先搜索智能体延迟工具目录；存在可发现工具时不要让用户重复授权或重启 |
| 浏览器点开服务地址后显示需要登录 | 浏览器没有当前客户端的登录状态，不能据此判断授权失败；不补填任何密钥或认证头，用客户端的工具列表验证 |
| 工具调用权限不足 | 只补申请本次搜索或模型聊天所需的那一项权限，不伪造调用来源 |

排障只报告脱敏摘要，避免输出请求头、完整认证配置、浏览器授权链接、callback URL 查询参数或 token。

## 多模型对比交付

模型聊天需要 `model:chat`。单次可以选择任意个不同模型，至少 1 个；不要按 `limits.allowedModelCounts` 限制个数。同一次请求不要重复同一个模型，其他会话和后续轮次可以再用。比较结果协议包含 `newResults`（新原文）、`pendingModels`（未完成模型）、`models`（全部状态）和 `nextAction`。按 SKILL.md 中的进度交付规则逐个完整展示，传累计 `displayedModelAliases` 查询原任务；批次 completed 后仍有 newResults 时继续展示，不自动总结。服务端不持久化展示确认，不因读取而确认已展示。

## 启用和费用确认

仅在用户明确指定 DiffMind 时使用本 Skill。每次新的搜索或模型批次前提示可能扣除账号点数，等待真实确认；已有 OAuth 不代替本次付费确认。后备脚本 `--check` 只检查工具，`--query` 发起真实搜索并可能扣点。查询已有模型任务结果不重新发起生成，也不重复弹出付费确认；已有任务继续生成的用量仍按原规则结算。

## 等待与失败提示

查询已有任务不设总等待上限。网络中断后先等待约 1 秒重试原查询，此后约 15 秒，直到终态、不可恢复的错误或用户停止。正常间隔以 `retryAfterSeconds` 为准，不用一段固定时长当成总超时。

`models` 包含每个模型的错误状态，即使 `newResults` 为空也必须检查。`insufficient_points` 表示账号点数不足，按实际失败阶段说明受影响模型；不把它列入仍在生成的名单，不自动重发付费请求。

## Codex 专用后备脚本的行为与日志

仅 Codex 智能体使用此脚本；Cursor、豆包和 WorkBuddy 不执行，也不需要安装 Codex。`codex_mcp.py` 读取并核对指定 MCP 配置，启动本机 Codex App Server，通过临时线程发现工具并复用 Codex 管理的 OAuth。`--check` 只检查，`--query` 调用一次 `diffmind_web_search`；不支持模型对比或其结果轮询，不启动智能体模型对话，不自行读写 Token 或持久 MCP 配置。

脚本没有日志文件写入功能。stdout 输出 JSON：检查状态、搜索工具原始结果或脱敏失败原因；命令参数错误由 argparse 输出到 stderr。子进程 stderr 被丢弃，原始 RPC 错误不直接打印。搜索词位于进程命令参数中，命令与 stdout 可能被智能体的运行记录、终端记录或运维采集保留；搜索结果可能包含敏感内容。临时线程不代表整个 Codex 运行条件完全无日志，Codex 自身运行日志由智能体管理。实际搜索还会走服务端正常用量记录和日志链路，具体内容以服务端配置为准。

配置读取超时 15 秒，普通 RPC 默认单次 45 秒，工具就绪循环目标约 30 秒（在途 RPC 可能让实际耗时超过该值），搜索调用单次 120 秒。这些是脚本局部等待限制，不是多模型生成或轮询总时长上限。`ready=true` 只说明调用链路可用，还必须检查工具结果本身的错误字段。

## 后台限制与任务恢复

新批次先读取 `diffmind_compare_tasks`。后台按账号限制同时生成中的会话，一次提问不论几个模型只计一个名额，全部模型结束才释放；上限读取服务端limits，缺省为2个。已有上限个会话仍在生成时，新的会话立即拒绝、不等待、不排队。相同模型可以出现在不同会话和后续轮次。通过服务端 `limits.maxConcurrentChats` 和 `activeChatCount` 读取限制及占用，不按模型数量计算。这个上限只统计本连接上正在生成的会话。

新对话提交按账号每秒放行1次，成功后至少间隔1秒，超限立即拒绝、不等待；通过 `limits.startsPerSecond` 获取此限制，不再读取原分钟配置。已有任务的幂等重试、结果查询不消耗新的提交额度。其他协议限制、建议轮询间隔、保留期和计费策略通过 `limits` 返回，客户端不能以 Skill 里的数字覆盖后端。`CONCURRENCY_LIMIT` 返回本批次未启动及现有可管理任务；停止需要用户选择，复用原取消工具并查询实际终态。

查询以服务端返回的状态和正文为准。先看是否已有终态和正文，再说明属主失联或任务不在运行。查询失败不能说成任务已失败。不自动重发模型，以免重复扣点。

消息内容的相关性由调用方按 SKILL.md 的上下文范围组织；服务器能强制检查身份、scope、模型权益、消息数量/大小和计费，却不能可靠地从任意自然语言中判断哪句话属于无关智能体聊天。不能宣传服务端已自动过滤全部隐私内容。扣点前点选确认及完整展示是智能体交互规则，不能代替服务端鉴权和计费校验。
