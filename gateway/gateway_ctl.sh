#!/bin/bash
# ============================================================
# ACN_SDK 网关独立控制脚本
# 用法: bash gateway_ctl.sh {start|stop|restart|status|log}
#
# 与 one_click_start_2030.sh 共用 PID/日志文件,两边互认:
#   - 本脚本启动的网关,一键脚本 status/stop 能正确识别
#   - 一键脚本启动的网关,本脚本也能停止
#
# 重要经验(2026-10-19 实测):
#   1. start_gateway.sh 内部是 exec 前台运行,必须后台化;
#   2. 经 wsl.exe / 定时任务启动的进程会随会话被整体回收,
#      必须用 setsid 脱离会话才能常驻;
#   3. setsid 在是进程组长时会 fork,导致 $! 未必是最终 python PID,
#      所以启动后统一用 pgrep 发现真实 PID 再写文件。
# ============================================================
set -u

ACN_SDK_DIR="/home/aicor/compute_network/sandbox-demo/acn_sdk"
GATEWAY_SCRIPT="${ACN_SDK_DIR}/gateway/start_gateway.sh"
GATEWAY_PORT="${GATEWAY_PORT:-9011}"

# 与一键脚本相同的运行目录(PID/日志互通)
RUN_DIR="${HOME}/.run/one_click_2030"
GATEWAY_PID_FILE="${RUN_DIR}/acn_gateway.pid"
GATEWAY_LOG="${RUN_DIR}/acn_gateway.log"
# SDK 自身的业务日志
SDK_LOG="${ACN_SDK_DIR}/gateway/runtime/logs/acn_sdk.log"

log() { echo "[$(date '+%F %T')] $*"; }

# ---------- 状态检测 ----------
gateway_running() {
  [[ -f "${GATEWAY_PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${GATEWAY_PID_FILE}" 2>/dev/null)" || return 1
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

# PID 文件丢失/失效时,按进程名查找真实网关进程
gateway_discover_pid() {
  pgrep -f 'python -m acn_gateway' 2>/dev/null | head -n 1
}

# 0=健康接口正常 1=不通 2=本机无 curl
gateway_healthy() {
  command -v curl >/dev/null 2>&1 || return 2
  curl -s -m 3 "http://127.0.0.1:${GATEWAY_PORT}/health" >/dev/null 2>&1
}

# ---------- 动作 ----------
do_start() {
  if [[ ! -f "${GATEWAY_SCRIPT}" ]]; then
    log "❌ 找不到启动脚本: ${GATEWAY_SCRIPT}"
    return 1
  fi
  mkdir -p "${RUN_DIR}"

  # 1) 已在运行则跳过(PID 文件优先,失效则按进程名兜底)
  if gateway_running; then
    log "↩️  网关已在运行 (PID $(cat "${GATEWAY_PID_FILE}")),跳过"
    return 0
  fi
  local discovered
  discovered="$(gateway_discover_pid)"
  if [[ -n "${discovered}" ]]; then
    log "↩️  检测到网关进程已在运行 (PID ${discovered},PID 文件失效),已重建 PID 文件"
    echo "${discovered}" > "${GATEWAY_PID_FILE}"
    return 0
  fi
  rm -f "${GATEWAY_PID_FILE}"

  # 2) 启动(setsid 脱离会话 + nohup 后台化,cd 到 acn_sdk 目录)
  (
    cd "${ACN_SDK_DIR}" || exit 1
    setsid nohup bash "${GATEWAY_SCRIPT}" >>"${GATEWAY_LOG}" 2>&1 < /dev/null &
  )

  # 3) 用 pgrep 拿真实 python PID 写文件(规避 setsid fork 导致 $! 失真)
  local pid=""
  local i
  for i in 1 2 3 4 5; do
    pid="$(gateway_discover_pid)"
    [[ -n "${pid}" ]] && break
    sleep 1
  done
  if [[ -z "${pid}" ]]; then
    log "❌ 网关启动失败,最近日志如下:"
    tail -n 20 "${GATEWAY_LOG}" 2>/dev/null
    return 1
  fi
  echo "${pid}" > "${GATEWAY_PID_FILE}"

  # 4) 等健康接口就绪(最多 15s)
  local waited=0 rc
  while :; do
    gateway_healthy; rc=$?
    [[ ${rc} -ne 1 ]] && break
    gateway_discover_pid >/dev/null || break
    (( waited >= 15 )) && break
    sleep 1
    waited=$((waited + 1))
  done
  gateway_healthy; rc=$?
  if [[ ${rc} -eq 0 ]]; then
    log "✅ 网关已启动 (PID ${pid}),健康接口 ${GATEWAY_PORT} 正常"
  else
    log "⚠️  进程在运行 (PID ${pid}),但健康接口 ${GATEWAY_PORT} 暂未就绪"
  fi
  log "   日志: ${GATEWAY_LOG} (SDK 业务日志: ${SDK_LOG})"
}

do_stop() {
  local pid=""
  if gateway_running; then
    pid="$(cat "${GATEWAY_PID_FILE}")"
  else
    pid="$(gateway_discover_pid)"
    [[ -n "${pid}" ]] && log "PID 文件失效,按进程名找到网关 (PID ${pid})"
  fi

  if [[ -z "${pid}" ]]; then
    log "网关未在运行"
    rm -f "${GATEWAY_PID_FILE}"
    return 0
  fi

  # 先 SIGTERM(uvicorn lifespan 会执行 SDK disconnect_all 清理 WS/MoQ)
  if kill "${pid}" 2>/dev/null; then
    local i
    for i in 1 2 3 4 5; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      log "5 秒未退出,SIGKILL 强制结束 (PID ${pid})"
      kill -9 "${pid}" 2>/dev/null
      sleep 1
    fi
    if kill -0 "${pid}" 2>/dev/null; then
      log "⚠️  无法停止网关 (PID ${pid},权限不足?)"
      return 1
    fi
    log "✅ 已停止网关 (PID ${pid})"
  else
    log "⚠️  停止网关 (PID ${pid}) 失败(权限不足?)"
    return 1
  fi
  rm -f "${GATEWAY_PID_FILE}"
}

do_status() {
  echo "==== ACN_SDK 网关状态 ===="
  # 进程
  local pid=""
  if gateway_running; then
    pid="$(cat "${GATEWAY_PID_FILE}")"
    echo "进程:   ✅ 运行中 (PID ${pid})"
    ps -o etime= -p "${pid}" 2>/dev/null | awk '{print "运行时长: "$1}'
  else
    pid="$(gateway_discover_pid)"
    if [[ -n "${pid}" ]]; then
      echo "进程:   ✅ 运行中 (PID ${pid},PID 文件失效)"
    else
      echo "进程:   ❌ 未运行"
    fi
  fi
  # 健康接口
  gateway_healthy; local rc=$?
  if [[ ${rc} -eq 0 ]]; then
    echo "健康:   ✅ http://127.0.0.1:${GATEWAY_PORT}/health 正常"
  elif [[ ${rc} -eq 2 ]]; then
    echo "健康:   ? 本机无 curl,无法检测 (${GATEWAY_PORT})"
  else
    echo "健康:   ❌ ${GATEWAY_PORT} 未就绪"
  fi
  # SDK 状态摘要
  if [[ ${rc} -eq 0 ]]; then
    echo -n "SDK:    "
    curl -s -m 3 "http://127.0.0.1:${GATEWAY_PORT}/sdk/status" | python3 -c "
import json, sys
try:
    s = json.load(sys.stdin).get('state', {})
    aid = s.get('agent_id') or '-'
    if len(aid) > 40:
        aid = aid[:24] + '...' + aid[-12:]
    ident = 'registered' if s.get('identity_registered') else 'none'
    caps = 'registered' if s.get('capabilities_registered') else 'none'
    print('agent_id=%s identity=%s caps=%s net=%s task=%s' % (
        aid, ident, caps, s.get('network_status'), s.get('task_status')))
except Exception as exc:
    print('parse-error: %s' % exc)
" 2>/dev/null || echo "查询失败"
  fi
  echo "日志:   ${GATEWAY_LOG}"
  echo "SDK日志: ${SDK_LOG}"
}

do_log() {
  [[ -f "${GATEWAY_LOG}" ]] || { echo "(日志文件不存在: ${GATEWAY_LOG})"; return 0; }
  echo "==== ${GATEWAY_LOG} (最后 ${LOG_LINES:-40} 行,Ctrl+C 退出) ===="
  tail -n "${LOG_LINES:-40}" -f "${GATEWAY_LOG}"
}

usage() {
  sed -n '2,8p' "$0"
  exit 1
}

# ---------- 入口 ----------
case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; do_start ;;
  status)  do_status ;;
  log)     do_log ;;
  *)       usage ;;
esac
