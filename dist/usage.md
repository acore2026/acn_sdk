# ACN SDK Wheel 使用说明

本文档说明如何在 Windows 环境下创建测试虚拟环境、安装 `acn_sdk` 的 wheel 包，并运行协作示例脚本进行验证。

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

## 清理环境

```powershell
# 退出虚拟环境
deactivate

# 删除虚拟环境（可选）
Remove-Item -Recurse -Force E:\temp\test_env
```
