# Tests 功能总结与测试报告

## 测试范围

本报告覆盖仓库顶层 `tests/` 目录。项目在 `pyproject.toml` 中配置了：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

因此默认执行 `pytest` 或 `pytest -q` 时，运行的是顶层 `tests/` 测试集，不包含 `moq/tests/` 子目录。

## 执行结果

执行命令：

```bash
pytest -q
```

执行结果：

```text
51 passed in 72.62s (0:01:12)
```

## 测试文件功能

### `tests/conftest.py`

提供统一测试夹具和 mock 环境，主要用于隔离外部依赖：

- 创建临时 SDK 配置文件。
- 创建临时 identity、密钥和日志目录。
- mock `HttpClient` 底层 HTTP session。
- mock ACN Agent、ARF 等接口响应。
- mock `PipelineLogReporter`，用于验证流水日志记录。

这些夹具使测试不依赖真实 ACN、ARF、WebSocket 或 MoQ Relay 服务。

### `tests/test_identity_flow.py`

主业务流测试文件，共 39 个用例，覆盖 SDK 的身份、网络、任务协作和配置相关能力：

- Agent 注册、能力注册、查询和注销完整生命周期。
- 本地 Agent 信息查询、远端 Agent 信息查询、Owner Agent 列表查询。
- 请求签名、签名编码顺序、timestamp-only 签名校验。
- 入网、退网、网络状态查询，以及新配置端口生效。
- 任务创建、任务状态查询、任务列表查询、任务终止和广播终止。
- WebSocket 消息处理，包括协作请求、发现结果、开始任务、任务终止、任务分配和清理指令。
- MoQ 轨道发布、对象发送、订阅、fetch 策略、重复订阅跳过、非法订阅模式拒绝。
- 回调注册和分发，包括 WebSocket 业务消息回调和 MoQ 对象回调。
- `CLEAR` 和 `clear_all` 强制清理 identity、网络状态、任务注册表、发布轨道和订阅轨道。
- SDK 配置重载。
- SDK 初始化时清理陈旧 identity 缓存。
- HTTP 客户端禁用环境代理继承。
- EC 密钥创建、保留，以及旧 RSA 密钥替换。
- 旧版 identity 文件兼容，包括单 capability VC 和已有 capability VC 名称解析。
- capability 输入去重。
- 能力 VC 根据不同 issuer 使用对应证书和私钥签发。

### `tests/test_logging_format.py`

日志格式测试文件，共 4 个用例，覆盖 SDK 和网络客户端日志可读性：

- HTTP 请求和响应按 pretty JSON 输出。
- SDK 高层日志只保留描述性信息，不重复回显底层 HTTP response。
- WebSocket 发送和接收 payload 按 pretty JSON 输出。
- SDK 处理网络消息时输出结构化 payload。

### `tests/test_moq_client.py`

MoQ 客户端测试文件，共 8 个用例，覆盖发布端、订阅端和异步资源清理：

- Publisher 使用真实 `FullTrackName` 编码 namespace 和 track。
- Subscriber 收到对象后转发给上层回调。
- 断开连接时清理已发布轨道和已订阅轨道。
- 跨线程访问事件循环时串行化，避免并发竞态。
- transport 关闭兼容同步 `close()`。
- 异步 `aclose()` 超时时取消任务并回退到同步关闭。
- Subscriber 断开时取消对象接收任务。
- `get_next_object()` 支持跨 owner event loop 桥接对象队列和回调。

## 覆盖能力概览

当前顶层测试覆盖了以下核心能力：

| 模块 | 覆盖内容 |
| --- | --- |
| 身份生命周期 | 注册、能力注册、查询、注销、陈旧缓存清理、旧数据兼容 |
| 网络生命周期 | 入网、退网、网络状态、配置端口、WebSocket 连接与清理 |
| 任务协作 | 任务创建、状态查询、协作请求、协作接受、任务开始、任务终止、广播终止 |
| MoQ 传输 | 发布、发送对象、订阅、fetch、重复订阅保护、断开清理 |
| 回调机制 | WebSocket 消息回调、MoQ 对象回调、订阅策略回调 |
| 安全与凭证 | EC 密钥、RSA 迁移、请求签名、issuer-specific VC 签发 |
| 日志 | HTTP、WebSocket、SDK 网络消息的 pretty JSON 日志 |
| 配置与 HTTP | 配置重载、ARF/ACN Agent endpoint 选择、禁用环境代理 |

## 结论

顶层 `tests/` 测试集当前全部通过，能够作为 SDK 单元测试和轻量集成回归的主要依据。测试通过 mock 外部网络服务验证 SDK 内部行为、请求构造、状态流转和资源清理逻辑。

需要注意的是，当前默认测试不覆盖真实 ACN、ARF、WebSocket、MoQ Relay 服务的端到端联调，也不包含 `moq/tests/` 子目录测试。
