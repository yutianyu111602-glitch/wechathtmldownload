# Skill Control-Plane Update (VSA-23)

时间: 2026-06-03

## 更新口径

1. skill 保持 control plane only。
2. 重脚本执行保留在 Docker worker entrypoint。
3. 任何 runtime/start/write/release 必须由显式 controller gate 放行。

## 禁止回退

- 不把长脚本回填到 skill。
- 不在 skill 中直接执行 DB 写入、upload/release、provider/model 调用。
