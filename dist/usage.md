# ACN SDK Wheel 使用说明

本文档说明如何在 Windows 环境下创建测试虚拟环境、安装 `acn_sdk` 的 wheel 包，并运行协作示例脚本进行验证。

## 适用范围

- 适用于通过 wheel 方式分发的 `acn_sdk-0.1.0-py3-none-any.whl`
- 适用于 Windows PowerShell 环境
- 适用于示例脚本：
  - `demo_task_initiator_rt.py`
  - `demo_task_collaborator_rt.py`

## 文件准备

请将以下文件放在同一目录，例如 `E:\temp`：

- `acn_sdk-0.1.0-py3-none-any.whl`
- `demo_task_initiator_rt.py`
- `demo_task_collaborator_rt.py`

## 创建测试虚拟环境

```powershell
# 删除旧环境（如果存在）
Remove-Item -Recurse -Force E:\temp\test_env -ErrorAction SilentlyContinue

# 创建新环境
python -m venv E:\temp\test_env

# 激活虚拟环境
E:\temp\test_env\Scripts\Activate.ps1
```

## 安装 wheel 包

```powershell
# 安装 wheel 包（使用完整路径）
pip install --force-reinstall --no-cache-dir E:\temp\acn_sdk-0.1.0-py3-none-any.whl

# 验证安装结果
python -c "import inspect; from acn_sdk import AcnSDK; print(inspect.signature(AcnSDK.__init__))"
```

预期输出：

```text
(self, agent_name: str, config_path: str | Path | None = None) -> None
```

## 运行示例

`demo_task_collaborator_rt.py` 和 `demo_task_initiator_rt.py` 是一对协作示例脚本，应该分别部署并运行在两个运行节点上。建议由协作端节点先启动，发起端节点随后启动。

### 协作端节点

```powershell
E:\temp\test_env\Scripts\Activate.ps1
python E:\temp\demo_task_collaborator_rt.py
```

### 发起端节点

```powershell
E:\temp\test_env\Scripts\Activate.ps1
python E:\temp\demo_task_initiator_rt.py
```

## 运行说明

- 协作端节点应先启动并保持运行
- 发起端节点在另一端运行节点上启动后，会完成身份注册、任务发起、协同建立和任务信息上报
- 两个脚本均为示例程序，运行期间会持续输出日志信息，属于正常现象

## 清理环境

```powershell
# 退出虚拟环境
deactivate

# 删除虚拟环境（可选）
Remove-Item -Recurse -Force E:\temp\test_env
```

## 注意事项

- 安装时请确认 wheel 文件名与实际产物一致
- 若目录中存在多个 wheel 文件，请优先使用最新生成的 `acn_sdk-0.1.0-py3-none-any.whl`
- 若 PowerShell 提示脚本执行策略限制，可先按现场规范调整执行策略后再激活虚拟环境
