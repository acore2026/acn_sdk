# ACN Android SDK

该目录是“方案二：Android 原生 SDK”的初始实现。

目标是让 Android 手机逐步具备与当前 Python `acn_sdk` 对齐的端侧 SDK 能力，使手机最终可以作为独立 ACN Agent 完成身份注册、能力注册、入网、任务协同和数据传输。

当前版本已经完成 Android 原生 SDK 的基础骨架和控制面能力；MoQ/QUIC 数据面只保留接口边界，尚未接入真实 Android native 传输实现。

---

## 1. 当前实现范围

### 1.1 已实现

当前已落地以下能力：

- Android library Gradle 工程骨架
- Android 原生 SDK 入口 `AcnSdk`
- 与 Python SDK 对齐的核心接口命名
- `AcnConfig` 网络配置模型
- Kotlin 数据模型
- OkHttp HTTP 客户端
- OkHttp WebSocket 控制面客户端
- Android Keystore ECDSA 签名
- `EncryptedSharedPreferences` 加密身份缓存
- 能力 VC 占位签发逻辑
- MoQ/QUIC Android native 接口边界

### 1.2 未完成

当前尚未完成：

- Android 原生 MoQ/QUIC 传输栈
- `taskInfoReport()` 的真实 MoQ 数据发送能力
- MoQ subscribe/fetch 后的数据回调
- Android 真机端到端测试
- 与 Python SDK 的完整协议一致性测试

重点说明：`MoqClient` 不是可用的真实 MoQ 实现。当前默认实现是明确占位，调用 publish、subscribe、sendObject 等数据面接口会抛出 `MoqNotImplementedException`。

这样设计是为了避免测试误判。没有真实 QUIC/MoQ 传输时，不能用 HTTP/WebSocket 假装 MoQ 成功。

---

## 2. 工程结构

```text
android/acn-android-sdk/
├── README.md
├── settings.gradle.kts
├── build.gradle.kts
└── acn-sdk/
    ├── build.gradle.kts
    ├── consumer-rules.pro
    └── src/main/
        ├── AndroidManifest.xml
        └── java/com/acn/sdk/
            ├── AcnSdk.kt
            ├── callback/
            │   └── AcnEventListener.kt
            ├── config/
            │   └── AcnConfig.kt
            ├── credential/
            │   └── CredentialIssuer.kt
            ├── crypto/
            │   └── CredentialSigner.kt
            ├── identity/
            │   └── IdentityManager.kt
            ├── model/
            │   └── Models.kt
            ├── network/
            │   ├── AcnHttpClient.kt
            │   ├── AcnWebSocketClient.kt
            │   └── MoqClient.kt
            └── util/
                └── JsonSupport.kt
```

---

## 3. 模块说明

### 3.1 `AcnSdk`

Android 原生 SDK 聚合入口，对上层 App 提供统一接口。

主要职责：

- 初始化身份存储、签名器、HTTP 客户端和 WebSocket 客户端
- 注册 Agent 身份
- 注册 Agent 能力
- 查询本地或远端 Agent 信息
- 入网和退网
- 发送任务请求和任务协同控制面消息
- 为 MoQ 数据面预留统一接口

对应 Python SDK：

```text
acn_sdk.sdk.AcnSDK
```

### 3.2 `AcnConfig`

配置 ACN 网络端点。

默认端口与 Python SDK 配置保持一致：

```text
acn_agent_port     = 9010
arf_port           = 9001
agent_gw_ws_port   = 9002
agent_gw_moq_port  = 9003
web_ui_port        = 9005
ws_path            = /ws
```

### 3.3 `AcnHttpClient`

基于 OkHttp 实现 HTTP 接口。

当前封装的服务端接口包括：

- `POST /idm/v1/identity-applications`
- `POST /arf/v1/agent-cards`
- `POST /acn-agent/v1/agent-deletions`
- `POST /acn-agent/v1/task-executions`
- `POST /acn-agent/v1/task-execution-terminations`
- `POST /arf/v1/agent-discoveries`
- `POST /arf/v1/agent-info`
- `POST /acn-agent/v1/owner-agents`

### 3.4 `AcnWebSocketClient`

基于 OkHttp WebSocket 实现 AgentGW 控制面连接。

当前支持：

- 连接 `ws://<networkIp>:<agentGwWsPort>/ws`
- 发送 `SETUP`
- 等待 `SETUP/OK`
- 发送 `DISCONNECTION`
- 发送任务协同控制面消息
- 接收并分发以下事件：
  - `TASK_REQUEST_COLLABORATION`
  - `DISCOVER_RESULT`
  - `TASK_ASSIGNED`
  - `START_TASK`
  - `TASK_TERMINATION`
  - `SUBSCRIBE_TRACK`

### 3.5 `IdentityManager`

Android 本地身份缓存管理器。

当前使用：

```text
EncryptedSharedPreferences
```

保存内容包括：

- `agentId`
- `vc0`
- `agentName`
- `owner`
- `priority`
- `metadata`
- `capabilityVcs`

### 3.6 `CredentialSigner`

Android 原生签名器。

当前使用：

```text
Android Keystore
EC secp256r1
SHA256withECDSA
Base64 signature
```

用于替代 Python SDK 中基于 PEM 文件的签名方式。

Python SDK 当前使用：

```text
data/keys/private_key.pem
data/keys/public_key.pem
```

Android SDK 改为系统 Keystore 管理私钥，私钥不可直接导出。

### 3.7 `CredentialIssuer`

能力 VC 占位签发器。

当前逻辑与 Python SDK 的模拟签发保持语义一致，但不是正式第三方凭证签发服务。

后续如果需要接入真实发证方，应替换该模块。

### 3.8 `MoqClient`

MoQ/QUIC 数据面接口。

当前只定义接口，不提供真实传输能力：

```kotlin
interface MoqClient {
    suspend fun connect()
    suspend fun publish(namespace: String, track: String)
    suspend fun unpublish(namespace: String, track: String)
    suspend fun sendObject(namespace: String, track: String, payload: ByteArray)
    suspend fun subscribe(namespace: String, track: String, subscriberId: String)
    suspend fun unsubscribe(namespace: String, track: String, subscriberId: String? = null)
    suspend fun disconnect()
}
```

默认占位实现：

```kotlin
NativeMoqClientPlaceholder
```

会抛出：

```kotlin
MoqNotImplementedException
```

---

## 4. 构建环境

建议环境：

- JDK 17
- Android Gradle Plugin 8.7.3
- Kotlin 2.0.21
- Android compileSdk 35
- Android minSdk 26

当前仓库未提交 Gradle Wrapper，因此需要本机有 `gradle` 命令，或后续补充 Wrapper。

### 4.1 使用系统 Gradle 构建

```bash
cd android/acn-android-sdk
gradle :acn-sdk:assembleDebug
```

### 4.2 使用 Gradle Wrapper 构建

如果添加了 Wrapper：

```bash
cd android/acn-android-sdk
./gradlew :acn-sdk:assembleDebug
```

### 4.3 当前环境说明

在当前工作环境中没有检测到系统级 `gradle` 命令，因此本次只完成代码与文档落地，未执行 Android Gradle 构建验证。

---

## 5. 在 Android App 中集成

### 5.1 作为本地 module 引入

在 App 工程的 `settings.gradle.kts` 中加入：

```kotlin
include(":acn-sdk")
project(":acn-sdk").projectDir = file("../android/acn-android-sdk/acn-sdk")
```

在 App 的 `build.gradle.kts` 中加入依赖：

```kotlin
dependencies {
    implementation(project(":acn-sdk"))
}
```

### 5.2 权限

SDK module 已声明：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

如果 App 使用 Android 9 及以上并访问明文 HTTP，需要根据实际测试环境配置 cleartext traffic。例如测试环境使用 `http://<ip>:9010` 时，App 可能需要：

```xml
<application
    android:usesCleartextTraffic="true">
</application>
```

正式环境建议使用 HTTPS/WSS。

---

## 6. 快速使用示例

### 6.1 初始化 SDK

```kotlin
val sdk = AcnSdk(
    context = applicationContext,
    agentName = "AndroidAgent",
    config = AcnConfig(
        networkIp = "101.245.78.174",
        acnAgentPort = 9010,
        arfPort = 9001,
        agentGwWsPort = 9002,
        agentGwMoqPort = 9003,
    ),
    eventListener = object : AcnEventListener {
        override fun onTaskCollaborationRequest(payload: JsonObject) {
            // 处理任务协同请求
        }

        override fun onDiscoverResult(payload: JsonObject) {
            // 处理发现结果
        }

        override fun onStartTask(payload: JsonObject) {
            // 处理启动任务
        }

        override fun onTaskTermination(payload: JsonObject) {
            // 处理任务终止
        }

        override fun onError(error: Throwable) {
            // 处理 WebSocket 或事件解析异常
        }
    },
)
```

### 6.2 注册身份

```kotlin
val agentId = sdk.registerAgentInfo(
    AgentInfo(
        name = "AndroidAgent",
        owner = "+8613800138000",
        description = "Android ACN test agent",
        priority = 1,
    ),
)
```

### 6.3 注册能力

```kotlin
sdk.registerAgentAttribute(
    agentId = agentId,
    capabilities = listOf("目标跟踪", "可疑人员识别"),
)
```

### 6.4 入网

```kotlin
sdk.joinNetwork(
    agentId = agentId,
    connectMoq = false,
)
```

说明：

- `connectMoq = false` 时，只连接 WebSocket 控制面。
- `connectMoq = true` 时，需要注入真实 `MoqClient` 实现，否则会抛出 `MoqNotImplementedException`。

### 6.5 请求任务执行

```kotlin
val taskId = sdk.requestTaskExecution(
    agentId = agentId,
    taskInfo = "Android test task",
)
```

### 6.6 请求任务协同

```kotlin
sdk.requestTaskCollaboration(
    agentId = agentId,
    taskId = taskId,
    requiredCapabilities = listOf("目标跟踪"),
)
```

### 6.7 发送任务数据

当前该接口依赖真实 MoQ 实现。未接入 native MoQ 前，调用会失败。

```kotlin
sdk.taskInfoReport(
    agentId = agentId,
    taskId = taskId,
    topic = "Location",
    payload = "hello".toByteArray(),
)
```

当前预期异常：

```text
MoqNotImplementedException
```

### 6.8 退网

```kotlin
sdk.logoutNetwork(agentId)
```

### 6.9 清理

```kotlin
sdk.disconnectAll()
sdk.clearAll()
```

---

## 7. 与 Python SDK 的接口映射

| Python SDK | Android SDK | 当前状态 |
| --- | --- | --- |
| `register_agent_info()` | `registerAgentInfo()` | 已实现 |
| `register_agent_attribute()` | `registerAgentAttribute()` | 已实现，能力 VC 为占位签发 |
| `query_agent_id()` | `queryAgentId()` | 已实现，本地查询 |
| `query_agent_info()` | `queryAgentInfo()` | 已实现 |
| `query_agent_list()` | `queryAgentList()` | 已实现 |
| `join_network()` | `joinNetwork()` | 已实现 WebSocket 控制面；MoQ 需真实实现 |
| `logout_network()` | `logoutNetwork()` | 已实现 |
| `query_network_status()` | `queryNetworkStatus()` | 已实现 |
| `request_task_execution()` | `requestTaskExecution()` | 已实现 |
| `request_task_collaboration()` | `requestTaskCollaboration()` | 已实现 |
| `accept_task_collaboration()` | `acceptTaskCollaboration()` | 已实现 |
| `start_task_collaboration()` | `startTaskCollaboration()` | 已实现 |
| `task_info_report()` | `taskInfoReport()` | 接口已实现，真实发送依赖 MoQ |
| `request_terminate_task()` | `requestTerminateTask()` | 已实现 |
| `disconnect_all()` | `disconnectAll()` | 已实现 |
| `clear_all()` | `clearAll()` | 已实现 |

---

## 8. MoQ/QUIC 为什么没有直接实现

当前 Python SDK 的 MoQ 数据面依赖：

```text
MoQClient
  ↓
moq.pub.MOQPublisher / moq.sub.MOQSubscriber
  ↓
aioquic
  ↓
QUIC / MoQ Relay
```

这套实现绑定 Python 运行时，不能直接被 Android/Kotlin 使用。

Android 原生实现需要单独选型：

| 路线 | 说明 | 优点 | 风险 |
| --- | --- | --- | --- |
| Rust + NDK | 用 Rust 实现或封装 MoQ/QUIC，通过 JNI 暴露给 Kotlin | 性能好，可跨平台复用 | 构建和 JNI 封装复杂 |
| C/C++ + NDK | 使用 C/C++ QUIC/MoQ 库，通过 JNI 接入 | native 生态成熟 | 调试成本高，内存安全要求高 |
| Kotlin/Java 实现 | 纯 Android 实现 MoQ/QUIC | 集成简单 | 协议复杂，开发周期长 |
| Gateway 过渡 | Android 走 HTTP/WebSocket，服务端 Python 负责 MoQ | 快速可用 | 不是真正 Android 原生数据面 |

当前代码选择“接口已预留、实现不伪造”的方式：

- 上层 API 先稳定。
- HTTP/WebSocket/身份/签名先原生化。
- MoQ 后续以 `MoqClient` 实现类接入。

---

## 9. 后续接入真实 MoQ 的方式

后续需要新增一个真实实现：

```kotlin
class NativeMoqClient(
    private val host: String,
    private val port: Int,
    private val role: String,
) : MoqClient {
    override suspend fun connect() {
        // 调用 Rust/NDK 或 Android native MoQ 实现
    }

    override suspend fun publish(namespace: String, track: String) {
        // MoQ PUBLISH
    }

    override suspend fun sendObject(namespace: String, track: String, payload: ByteArray) {
        // MoQ object send
    }

    override suspend fun subscribe(namespace: String, track: String, subscriberId: String) {
        // MoQ SUBSCRIBE
    }
}
```

然后在初始化 SDK 时注入：

```kotlin
val sdk = AcnSdk(
    context = applicationContext,
    agentName = "AndroidAgent",
    config = config,
    eventListener = listener,
    moqPublisher = NativeMoqClient(
        host = config.agentGwMoqHost,
        port = config.agentGwMoqPort,
        role = "publisher",
    ),
    moqSubscriber = NativeMoqClient(
        host = config.agentGwMoqHost,
        port = config.agentGwMoqPort,
        role = "subscriber",
    ),
)
```

之后入网时启用 MoQ：

```kotlin
sdk.joinNetwork(agentId, connectMoq = true)
```

---

## 10. 当前测试建议

在 MoQ 未接入前，建议先测试控制面链路：

1. Android SDK 初始化
2. `registerAgentInfo()`
3. `registerAgentAttribute()`
4. `joinNetwork(connectMoq = false)`
5. WebSocket `SETUP/OK`
6. `requestTaskExecution()`
7. `requestTaskCollaboration()`
8. WebSocket 事件回调
9. `logoutNetwork()`

暂不测试：

- `taskInfoReport()` 的真实 MoQ 发送
- MoQ subscribe/fetch
- MoQ object receive

这些需要 native MoQ 接入后再验证。

---

## 11. 与现有 Python 工程的关系

该 Android SDK 是新增工程，不替换当前 Python SDK。

当前关系：

```text
Python SDK:
  acn_sdk/
  mock/
  examples/
  tests/

Android SDK:
  android/acn-android-sdk/
```

建议后续保持以下一致性：

- HTTP path 一致
- JSON 字段名一致
- WebSocket message type 一致
- timestamp 格式一致
- signature 编码方式一致
- 任务状态语义一致
- MoQ namespace/track 规则一致

---

## 12. 已知限制

- 当前未提交 Gradle Wrapper。
- 当前未执行 Android Gradle 构建验证。
- 当前 `CredentialIssuer` 是占位模拟签发，不是正式发证服务。
- 当前没有实现 PipelineLogReporter Android 版本。
- 当前没有实现任务本地 registry，任务状态查询仍需后续补齐。
- 当前没有实现 Android 后台保活、断线重连、网络切换恢复。
- 当前没有实现 MoQ native transport。

---

## 13. 推荐下一步

优先级建议：

1. 在具备 Android Gradle 环境的机器上执行构建。
2. 修正编译期问题。
3. 使用 mock 服务验证 HTTP 注册链路。
4. 使用 AgentGW 验证 WebSocket 入网链路。
5. 补充 Android instrumented test。
6. 选择 MoQ/QUIC Android native 技术路线。
7. 实现真实 `NativeMoqClient`。
8. 补齐任务 registry、重连和日志上报能力。
