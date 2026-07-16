# IMT2030 测试用例 ACN SDK 设计文档

版本：`v0.2.0`

当前状态：已按“方案一：Android 触发端 + Python Gateway”落地。

适用范围：IMT2030 测试用例中，Android 终端只触发 ACN 操作，身份、密钥、WebSocket、MoQ、任务回调和业务参数全部由 Python Gateway 托管。

---

## 1. 设计结论

当前工程采用轻量 Android SDK，不做 Android 原生 ACN SDK。

核心边界如下：

| 模块 | 当前职责 |
| --- | --- |
| Android App | 调用 7 个触发接口，展示结果或状态 |
| Android Light SDK | 封装 Gateway HTTP 调用，不保存业务状态 |
| Python Gateway | 持有 Python `AcnSDK` 实例，执行 ACN 全部业务逻辑 |
| Python ACN SDK | 原版 SDK 能力：身份、能力、入网、任务、回调、MoQ |
| ACN 网络组件 | AcnAgent、ARF、AgentGW、MoQ Relay、Web UI |

Android 侧不保存：

- `agent_id`
- `task_id`
- 身份缓存
- 私钥或公钥
- ACN 业务配置
- WebSocket 连接
- MoQ 连接或 MoQ 数据
- 任务协同回调逻辑

这些全部保存在 Python Gateway 进程和 Gateway runtime 目录中。

---

## 2. 总体架构

```text
Android App
  |
  | 7 个无业务参数 HTTP POST
  v
Android Light SDK
  |
  | HTTP JSON
  v
Python Gateway
  |
  | Python 方法调用、回调处理、状态管理
  v
Python AcnSDK
  |
  | HTTP / WebSocket / MoQ
  v
AcnAgent / ARF / AgentGW / MoQ Relay / Web UI
```

当前实现是“单 Gateway Agent”模型：

- 一个 Gateway 进程持有一个 Python `AcnSDK` 实例。
- 一个 Gateway runtime 目录对应一套身份、密钥、日志和 SDK 配置。
- Android 只是这个 Gateway Agent 的远程控制端。
- 若要并行模拟多个 Agent，应启动多个 Gateway 实例，并分别配置不同端口和 `runtime_dir`。

---

## 3. 部署关系

### 3.1 进程部署

```text
Android 设备
  └── App + acn-sdk-debug.aar
        └── 访问 http://<Gateway-IP>:9011

Gateway 主机，通常是开发机或服务器
  ├── acn_gateway FastAPI 服务，默认 0.0.0.0:9011
  ├── 原版 Python SDK，默认与 gateway 同级放置为 ../acn_sdk
  └── gateway/runtime
        ├── sdk-config.yaml
        ├── data/identity.json
        ├── data/keys/private_key.pem
        ├── data/keys/public_key.pem
        └── logs/acn_sdk.log

ACN 网络侧
  ├── AcnAgent HTTP，默认 9010
  ├── ARF HTTP，默认 9001
  ├── AgentGW WebSocket，默认 9002/ws
  ├── AgentGW MoQ，默认 9003
  └── Web UI，默认 9005
```

### 3.2 网络访问方向

| 起点 | 终点 | 协议 | 用途 |
| --- | --- | --- | --- |
| Android App | Python Gateway | HTTP | 触发 7 个操作 |
| Python Gateway | AcnAgent | HTTP | 身份注册、去注册、任务请求等 |
| Python Gateway | ARF | HTTP | 能力注册 |
| Python Gateway | AgentGW | WebSocket | 入网和任务控制面 |
| Python Gateway | AgentGW/MoQ Relay | MoQ/QUIC | MoQ track 订阅、fetch、对象消费 |

Android 设备必须能访问 Gateway 的监听地址。Gateway 必须能访问 ACN 网络组件。

局域网联调时，Android 配置应使用 Gateway 主机的局域网 IP，例如：

```kotlin
val acnSdk = AcnSdk(
    GatewayConfig(baseUrl = "http://192.168.1.10:9011")
)
```

不要在真机上使用 `127.0.0.1:9011` 访问电脑上的 Gateway；Android 真机里的 `127.0.0.1` 指手机自身。

---

## 4. 当前代码结构

```text
acn-sdk-android-light/
├── acn_sdk/  # 新主机部署时推荐与 gateway 同级放置原版 Python SDK
├── acn-sdk/
│   └── src/main/java/com/acn/sdk/light/
│       ├── AcnSdk.kt
│       ├── GatewayConfig.kt
│       ├── model/GatewayModels.kt
│       └── network/GatewayHttpClient.kt
├── gateway/
│   ├── acn_gateway/
│   │   ├── app.py
│   │   ├── config.py
│   │   └── service.py
│   ├── start_gateway.sh
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── tests/test_service.py
├── start_gateway.sh  # 兼容入口，转发到 gateway/start_gateway.sh
├── README.md
└── IMT2030测试用例ACN_SDK设计文档.md
```

Android module 当前没有 OkHttp、WebSocket、MoQ、协程库或 JSON 第三方运行依赖，网络请求使用 Android 平台 `HttpURLConnection`，JSON 解析使用 `org.json`。

---

## 5. Gateway 对外接口

所有业务操作都是 `POST`，请求体为空 JSON，Android 不传业务参数。

| 顺序 | Android SDK 方法 | Gateway 接口 | Python SDK 映射 | 参数来源 |
| --- | --- | --- | --- | --- |
| 1 | `registerIdentity()` | `POST /sdk/register-identity` | `register_agent_info()` | `agent` 配置 |
| 2 | `registerCapabilities()` | `POST /sdk/register-capabilities` | `register_agent_attribute()` | `capabilities` 配置 |
| 3 | `joinNetwork()` | `POST /sdk/join-network` | `join_network()` | Gateway 状态中的 `agent_id` |
| 4 | `executeTask()` | `POST /sdk/execute-task` | `request_task_execution()` | `task.task_id` 和 `task.description` 配置 |
| 5 | `broadcastTerminateTask()` | `POST /sdk/broadcast-terminate-task` | `broadcast_terminate_task()` | `task.termination_*` 配置 |
| 6 | `logoutNetwork()` | `POST /sdk/logout-network` | `logout_network()` | Gateway 状态中的 `agent_id` |
| 7 | `deregister()` | `POST /sdk/deregister` | `deregister_agent()` | `deregister.reason` 配置 |

辅助接口：

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | Gateway 存活和当前状态 |
| `/sdk/status` | GET | 查询 Gateway 当前状态 |

统一响应格式：

```json
{
  "result": true,
  "message": "",
  "data": {},
  "state": {
    "agent_id": "did:acn:agent:xxx",
    "current_task_id": "task-xxx",
    "identity_registered": true,
    "capabilities_registered": true,
    "network_status": "online",
    "task_status": "processing",
    "last_error": "",
    "moq_messages_received": 0
  }
}
```

---

## 6. 参数归属

当前方案要求所有 ACN 业务参数都在 Gateway 配置中管理。

| 参数类别 | 配置位置 | Android 是否传入 |
| --- | --- | --- |
| Gateway 监听地址 | `server` | 否 |
| Python SDK 路径 | `python_sdk.source_path` | 否 |
| runtime 目录 | `python_sdk.runtime_dir` | 否 |
| ACN 网络地址和端口 | `python_sdk.network` | 否 |
| Agent 名称、owner、描述、优先级、metadata | `agent` | 否 |
| 能力列表 | `capabilities` | 否 |
| 固定任务 ID | `task.task_id` | 否 |
| 任务描述 | `task.description` | 否 |
| 协同描述 | `task.collaboration_description` | 否 |
| 广播结束原因和 force 标志 | `task.termination_reason`、`task.termination_force` | 否 |
| 去注册原因 | `deregister.reason` | 否 |
| subscribe/fetch 策略 | `callbacks.fetch_tracks` | 否 |
| MoQ 消息处理策略 | `callbacks.moq_message_policy` | 否 |
| Gateway baseUrl | Android `GatewayConfig` | 是，仅连接地址 |

配置文件示例见 `gateway/config.example.yaml`。实际使用时复制为 `gateway/config.yaml` 后修改。

---

## 7. Gateway 内部状态

Gateway 内部维护以下状态：

```text
agent_id
current_task_id
identity_registered
capabilities_registered
network_status
task_status
last_error
moq_messages_received
```

`task_status` 当前取值：

| 状态 | 含义 |
| --- | --- |
| `idle` | 未执行任务 |
| `processing` | 任务执行中 |
| `terminating` | 已广播结束任务，等待 Python SDK 收到终止回调 |
| `terminated` | 已收到 `TASK_TERMINATION` 并完成本地任务清理 |

`logoutNetwork()` 和 `deregister()` 在 `processing` 或 `terminating` 状态下会失败，避免任务未清理时提前退网。

---

## 8. 回调和 MoQ 处理

当前所有 Python SDK 回调都在 Gateway 内部处理，不转发给 Android。

| Python SDK 回调 | Gateway 行为 |
| --- | --- |
| `on_task_collaboration_request` | 自动调用 `accept_task_collaboration()` |
| `on_discover_result_received` | 按 `discovery_selection: first` 选择第一个 Agent，自动调用 `start_task_collaboration()` |
| `on_task_start_command` | 自动调用 `request_task_execution()` |
| `on_terminate_task_received` | 自动调用 `request_terminate_task()`，并将任务状态置为 `terminated` |
| `on_subscribe_track_received` | 根据 `callbacks.fetch_tracks` 返回 `fetch` 或 `subscribe` |
| `on_message_received` | 在 Gateway 内消费 MoQ 数据，只计数或写日志 |

MoQ 数据不上传到 Android，不从 Android 上传，也不通过 Gateway API 暴露 payload。

当前 MoQ 消息策略：

| `callbacks.moq_message_policy` | 行为 |
| --- | --- |
| `log` | 写入 Gateway/Python SDK 日志，记录 namespace、track、payload 大小 |
| `discard` | 只增加计数，不写 payload 内容 |

---

## 9. 核心流程

### 9.1 注册和入网

```text
Android
  -> registerIdentity()
Gateway
  -> Python SDK register_agent_info(agent config)
  -> 保存 agent_id

Android
  -> registerCapabilities()
Gateway
  -> Python SDK register_agent_attribute(agent_id, capabilities config)

Android
  -> joinNetwork()
Gateway
  -> Python SDK join_network(agent_id)
  -> Python SDK 建立 AgentGW WebSocket 和 MoQ 相关连接
```

### 9.2 执行任务

```text
Android
  -> executeTask()
Gateway
  -> Python SDK request_task_execution(agent_id, task.description, task_id=task.task_id)
  -> 保存 current_task_id
  -> task_status = processing

AgentGW / MoQ
  -> Python SDK callbacks
Gateway
  -> 自动接受协同、启动协同、处理订阅/fetch、消费 MoQ 消息
```

### 9.3 结束任务、退网和去注册

```text
Android
  -> broadcastTerminateTask()
Gateway
  -> Python SDK broadcast_terminate_task(agent_id, current_task_id, reason, force)
  -> task_status = terminating

AgentGW
  -> TASK_TERMINATION callback
Gateway
  -> Python SDK request_terminate_task(agent_id, task_id, reason, force)
  -> task_status = terminated

Android
  -> logoutNetwork()
Gateway
  -> Python SDK logout_network(agent_id)

Android
  -> deregister()
Gateway
  -> Python SDK deregister_agent(agent_id, deregister.reason)
  -> 清理 Gateway 内存状态
```

---

## 10. 身份、密钥和日志位置

`python_sdk.runtime_dir` 默认配置为：

```yaml
python_sdk:
  runtime_dir: ./runtime
```

相对路径按 `gateway/config.yaml` 所在目录解析。因此默认实际目录是：

```text
/home/acn/zxy/imt/acn-sdk-android-light/gateway/runtime/
```

Gateway 启动时会生成 Python SDK 配置：

```text
gateway/runtime/sdk-config.yaml
```

其中写入原版 Python SDK 使用的存储路径：

```text
gateway/runtime/data/identity.json
gateway/runtime/data/keys/private_key.pem
gateway/runtime/data/keys/public_key.pem
gateway/runtime/logs/acn_sdk.log
```

说明：

- `private_key.pem` 和 `public_key.pem` 是 Gateway runtime 独立生成的一对密钥。
- 它们使用原版 Python SDK 的生成逻辑和格式，但不是 Python SDK 源码目录里的固定文件。
- 如果希望复用已有身份密钥，必须同时复用 `private_key.pem` 和 `public_key.pem`，不能只替换公钥。
- 当前 Python SDK 启动时会重建配置并可能清理 identity cache；密钥文件会在匹配有效时复用。

---

## 11. Android 集成方式

Android App 只需要引入 AAR 或本地 module，然后配置 Gateway 地址。

```kotlin
val acnSdk = AcnSdk(
    GatewayConfig(baseUrl = "http://192.168.1.10:9011")
)
```

调用顺序：

```kotlin
lifecycleScope.launch {
    acnSdk.registerIdentity().requireSuccess()
    acnSdk.registerCapabilities().requireSuccess()
    acnSdk.joinNetwork().requireSuccess()
    acnSdk.executeTask().requireSuccess()

    acnSdk.broadcastTerminateTask().requireSuccess()
}
```

退出和去注册：

```kotlin
lifecycleScope.launch {
    acnSdk.logoutNetwork().requireSuccess()
    acnSdk.deregister().requireSuccess()
}
```

局域网 HTTP 联调时，宿主 App 需要允许明文流量：

```xml
<application android:usesCleartextTraffic="true" />
```

生产或外场环境应给 Gateway 增加 HTTPS 和访问鉴权。

---

## 12. 启动和部署步骤

### 12.1 准备配置

```bash
cd /path/to/acn-gateway-deploy/gateway
cp config.example.yaml config.yaml
```

修改 `gateway/config.yaml` 中的：

- `python_sdk.source_path`，同级部署时保持 `../acn_sdk`
- `python_sdk.network.network_ip`
- `task.task_id`
- ACN 各组件端口
- `agent`
- `capabilities`
- `task`
- `deregister`
- `callbacks`

### 12.2 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

### 12.3 启动 Gateway

```bash
./start_gateway.sh
```

或指定配置：

```bash
./start_gateway.sh /absolute/path/to/config.yaml
```

默认监听：

```text
0.0.0.0:9011
```

### 12.4 验证服务

```bash
curl http://127.0.0.1:9011/health
curl http://127.0.0.1:9011/sdk/status
```

### 12.5 构建 Android AAR

```bash
./gradlew :acn-sdk:assembleDebug
```

产物：

```text
acn-sdk/build/outputs/aar/acn-sdk-debug.aar
```

---

## 13. 多 Gateway 部署

如果需要同时运行多个 Android 控制端或多个 Agent，不建议在同一个 Gateway 进程里复用状态。当前实现是单 Agent 模型，建议启动多个 Gateway 进程。

示例：

| Gateway | HTTP 端口 | runtime_dir | Agent |
| --- | --- | --- | --- |
| Gateway A | 9011 | `./runtime-agent-a` | AliceAgent |
| Gateway B | 8081 | `./runtime-agent-b` | BobAgent |
| Gateway C | 8082 | `./runtime-agent-c` | CharlieAgent |

每个实例必须保证：

- `server.port` 不同；
- `python_sdk.runtime_dir` 不同；
- `agent.name` / `agent.owner` 根据测试要求区分；
- Android 连接各自的 Gateway baseUrl。

---

## 14. 安全边界

当前实现服务于测试用例和联调，默认未加鉴权。

风险点：

- 局域网内任意可访问 Gateway 的设备都可能触发注册、入网、任务和去注册。
- Gateway runtime 保存身份、私钥、公钥和日志。
- 日志可能包含任务、track、错误和部分业务上下文。

建议：

- 联调时只在受控网络内开放 Gateway。
- 使用防火墙限制 Android 设备来源 IP。
- 外场环境增加 HTTPS。
- 外场环境增加 token、mTLS 或设备白名单。
- 不要将 `gateway/runtime` 下的私钥和身份文件提交到版本管理。

---

## 15. 当前方案限制

当前实现刻意不支持以下能力：

- Android 直接传 `agent_id`、`task_id`、能力列表或任务参数。
- Android 直接接收 Python SDK 回调事件。
- Android 直接上传 MoQ 数据。
- Android 直接接收 MoQ payload。
- Android 本地保存身份、密钥或 ACN 状态。
- 单 Gateway 进程内管理多个 Android session。

这些不是遗漏，而是当前设计边界：Android 只起触发操作，Gateway 承担完整 Agent 行为。

---

## 16. 后续演进

当前推荐保持方案一，直到测试用例稳定。

后续可选增强：

| 方向 | 说明 |
| --- | --- |
| Gateway 鉴权 | 增加 token、mTLS 或设备白名单 |
| 多实例管理 | 增加启动脚本或配置模板，便于并行多个 Gateway |
| OpenAPI 文档 | 使用 FastAPI 自动导出接口文档给 Android 对接 |
| 状态轮询增强 | 增加更细的任务状态和错误码 |
| 原生 Android SDK | 将 HTTP、WebSocket、身份、加密、MoQ 逐步迁移到 Android 本地 |

若未来要做 Android 原生 SDK，需要重新划分边界：Android 将成为完整 ACN Agent，必须实现身份存储、密钥管理、WebSocket 控制面、MoQ/QUIC 数据面和任务状态机。

---

## 17. 结论

当前仓库的准确设计是：

```text
Android = 控制触发端
Python Gateway = ACN Agent 运行端
原版 Python SDK = 实际 SDK 能力来源
ACN 网络组件 = 被 Gateway 访问
```

Android 只需要 Gateway 地址；其他所有参数、状态、身份、密钥、日志、WebSocket、MoQ 和回调逻辑都在 Python Gateway 中完成。
