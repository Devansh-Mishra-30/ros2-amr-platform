#!/usr/bin/env bash

# Deterministic v0.1.1 bring-up/shutdown verification with durable evidence.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_SETUP="/opt/ros/${ROS_DISTRO}/setup.bash"
WORKSPACE_SETUP="${REPO_ROOT}/ros2_ws/install/setup.bash"
CYCLE_COUNT="${CYCLE_COUNT:-10}"
RELEASE_CYCLE_COUNT=10
CRASH_RECOVERY_TEST="${CRASH_RECOVERY_TEST:-true}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-45}"
SHUTDOWN_TIMEOUT_SECONDS="${SHUTDOWN_TIMEOUT_SECONDS:-15}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8080}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"
RUNTIME_ROOT="${HOME}/.ros/cpp_robotics_sim"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_ROOT="${RUNTIME_ROOT}/evidence/v0.1.1/${TIMESTAMP}"
REGISTRY_PATH="${RUNTIME_ROOT}/process_registry.json"
RECOVERY_HELPER="${REPO_ROOT}/ros2_ws/install/cpp_robotics_sim_ros/lib/cpp_robotics_sim_ros/process_lifecycle.py"
SHUTDOWN_REPORT_DIR="${RUNTIME_ROOT}/shutdown_reports"
RUN_PID=""
CURRENT_CYCLE_DIR=""

mkdir -p "${EVIDENCE_ROOT}"

set +u
# shellcheck disable=SC1090
source "${ROS_SETUP}"
# shellcheck disable=SC1090
source "${WORKSPACE_SETUP}"
set -u
export PYTHONPATH="${REPO_ROOT}/ros2_ws/src/cpp_robotics_sim_ros/scripts:${PYTHONPATH:-}"

group_exists() {
  kill -0 -- "-$1" 2>/dev/null
}

port_is_listening() {
  ss -ltn "sport = :$1" | tail -n +2 | grep -q .
}

wait_until() {
  local timeout="$1"
  shift
  local deadline=$((SECONDS + timeout))
  while ((SECONDS < deadline)); do
    if "$@"; then
      return 0
    fi
    if [[ -n "${RUN_PID}" ]] && ! kill -0 "${RUN_PID}" 2>/dev/null; then
      return 1
    fi
    sleep 0.25
  done
  return 1
}

http_ready() {
  curl --fail --silent --max-time 2 \
    "http://127.0.0.1:${DASHBOARD_PORT}/" | grep -qi '<html'
}

simulation_service_ready() {
  ros2 service list 2>/dev/null | grep -Fxq '/simulation/start'
}

registry_has_simulation() {
  python3 - "${REGISTRY_PATH}" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.exists():
    raise SystemExit(1)
data = json.loads(path.read_text())
raise SystemExit(0 if any(
    item.get('component') == 'simulation_launch' and item.get('state') == 'active'
    for item in data.get('records', [])
) else 1)
PY
}

registry_has_mapping() {
  python3 - "${REGISTRY_PATH}" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.exists(): raise SystemExit(1)
components = {item.get('component') for item in json.loads(path.read_text()).get('records', [])}
raise SystemExit(0 if {'simulation_launch', 'mode_mapping'} <= components else 1)
PY
}

registry_has_only_simulation() {
  python3 - "${REGISTRY_PATH}" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.exists(): raise SystemExit(1)
components = [item.get('component') for item in json.loads(path.read_text()).get('records', [])]
raise SystemExit(0 if components == ['simulation_launch'] else 1)
PY
}

registry_is_clean() {
  python3 - "${REGISTRY_PATH}" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.exists():
    raise SystemExit(1)
raise SystemExit(0 if json.loads(path.read_text()).get('records') == [] else 1)
PY
}

critical_ros_duplicates_absent() {
  local nodes_path="${CURRENT_CYCLE_DIR}/ros_nodes.txt"
  local result_path="${CURRENT_CYCLE_DIR}/duplicate_result.json"
  ros2 node list --no-daemon --spin-time 2 >"${nodes_path}" 2>&1 || return 1
  python3 - "${nodes_path}" "${result_path}" <<'PY'
import json, pathlib, sys
from process_registry import ProcessRegistry
from runtime_verification import (
    find_duplicate_os_processes, find_duplicate_ros_nodes,
    snapshot_critical_os_processes,
)
nodes = pathlib.Path(sys.argv[1]).read_text().splitlines()
ros_duplicates = find_duplicate_ros_nodes(nodes)
registry_duplicates = {
    component: [record.instance_id for record in records]
    for component, records in ProcessRegistry().duplicate_components().items()
}
os_snapshot = snapshot_critical_os_processes()
os_duplicates = find_duplicate_os_processes(os_snapshot)
pathlib.Path(sys.argv[2]).write_text(json.dumps({
    'success': not ros_duplicates and not os_duplicates and not registry_duplicates,
    'ros_domain_id': __import__('os').environ.get('ROS_DOMAIN_ID', '0'),
    'ros_graph_duplicates': ros_duplicates,
    'os_process_duplicates': os_duplicates,
    'os_ownership_duplicates': registry_duplicates,
    'critical_os_processes': os_snapshot,
}, indent=2, sort_keys=True) + '\n')
raise SystemExit(1 if ros_duplicates or os_duplicates or registry_duplicates else 0)
PY
}

recorded_owned_processes_absent() {
  python3 - \
    "${CURRENT_CYCLE_DIR}/registry_active.json" \
    "${CURRENT_CYCLE_DIR}/registry_mode_active.json" \
    "${CURRENT_CYCLE_DIR}/remaining_process_result.json" <<'PY'
import json, pathlib, sys
from process_registry import (
    owned_process_group_status, ProcessRecord,
)
records = {}
for source in sys.argv[1:3]:
    for item in json.loads(pathlib.Path(source).read_text()).get('records', []):
        record = ProcessRecord.from_mapping(item)
        records[record.instance_id] = record
survivors = {
    record.instance_id: owned_process_group_status(record)
    for record in records.values()
    if owned_process_group_status(record) != 'absent'
}
payload = {
    'success': not survivors,
    'owned_or_ambiguous_survivors': survivors,
}
pathlib.Path(sys.argv[3]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + '\n'
)
raise SystemExit(0 if payload['success'] else 1)
PY
}

snapshot_critical_os_processes() {
  local destination="$1"
  python3 - "${destination}" <<'PY'
import json, pathlib, sys
from runtime_verification import snapshot_critical_os_processes
pathlib.Path(sys.argv[1]).write_text(
    json.dumps(snapshot_critical_os_processes(), indent=2, sort_keys=True) + '\n'
)
PY
}

critical_os_processes_absent() {
  local destination="${CURRENT_CYCLE_DIR}/critical_os_processes_after.json"
  snapshot_critical_os_processes "${destination}"
  python3 - "${destination}" <<'PY'
import json, pathlib, sys
raise SystemExit(0 if json.loads(pathlib.Path(sys.argv[1]).read_text()) == [] else 1)
PY
}

critical_ros_nodes_absent() {
  local nodes_path="${CURRENT_CYCLE_DIR}/ros_nodes_after.txt"
  local result_path="${CURRENT_CYCLE_DIR}/critical_ros_nodes_after.json"
  ros2 node list --no-daemon --spin-time 1 >"${nodes_path}" 2>&1 || return 1
  python3 - "${nodes_path}" "${result_path}" <<'PY'
import json, os, pathlib, sys
from runtime_verification import CRITICAL_ROS_NODES
nodes = pathlib.Path(sys.argv[1]).read_text().splitlines()
remaining = sorted({name.strip() for name in nodes if name.strip()} & CRITICAL_ROS_NODES)
pathlib.Path(sys.argv[2]).write_text(json.dumps({
    'success': not remaining,
    'ros_domain_id': os.environ.get('ROS_DOMAIN_ID', '0'),
    'remaining_critical_ros_nodes': remaining,
}, indent=2, sort_keys=True) + '\n')
raise SystemExit(0 if not remaining else 1)
PY
}

copy_shutdown_reports() {
  local destination="$1"
  local marker="$2"
  mkdir -p "${destination}"
  if [[ -d "${SHUTDOWN_REPORT_DIR}" ]]; then
    find "${SHUTDOWN_REPORT_DIR}" -maxdepth 1 -type f \
      -name '*.json' -newer "${marker}" \
      -exec cp -a -- {} "${destination}/" \;
  fi
}

recover_registered_groups() {
  local report_path="$1"
  "${RECOVERY_HELPER}" --recover --report "${report_path}"
}

ports_released() {
  ! port_is_listening "${DASHBOARD_PORT}" && \
    ! port_is_listening "${ROSBRIDGE_PORT}"
}

platform_leader_exited() {
  local state
  state="$(ps -o stat= -p "${RUN_PID}" 2>/dev/null | awk '{print $1}')"
  [[ -z "${state}" || "${state}" == Z* ]]
}

platform_group_exited() {
  ! group_exists "$1"
}

snapshot_registry() {
  local destination="$1"
  if [[ -f "${REGISTRY_PATH}" ]]; then
    cp -- "${REGISTRY_PATH}" "${destination}"
  else
    printf '{"missing":true}\n' >"${destination}"
  fi
}

force_cleanup() {
  local cleanup_needed=false
  [[ -n "${RUN_PID}" ]] && cleanup_needed=true
  if [[ -n "${RUN_PID}" ]] && group_exists "${RUN_PID}"; then
    kill -INT -- "-${RUN_PID}" 2>/dev/null || true
    for ((attempt = 0; attempt < SHUTDOWN_TIMEOUT_SECONDS * 4; attempt++)); do
      group_exists "${RUN_PID}" || break
      sleep 0.25
    done
    if group_exists "${RUN_PID}"; then
      kill -TERM -- "-${RUN_PID}" 2>/dev/null || true
      for _ in {1..20}; do
        group_exists "${RUN_PID}" || break
        sleep 0.25
      done
    fi
    if group_exists "${RUN_PID}"; then
      kill -KILL -- "-${RUN_PID}" 2>/dev/null || true
    fi
  fi
  [[ -z "${RUN_PID}" ]] || wait "${RUN_PID}" 2>/dev/null || true
  RUN_PID=""
  if [[ "${cleanup_needed}" == "true" && -x "${RECOVERY_HELPER}" \
    && -n "${CURRENT_CYCLE_DIR}" ]]; then
    recover_registered_groups \
      "${CURRENT_CYCLE_DIR}/failure_recovery_report.json" || true
  fi
}

write_cycle_result() {
  local cycle="$1" result="$2" duration="$3" reason="$4"
  python3 - "${CURRENT_CYCLE_DIR}/result.json" \
    "${cycle}" "${result}" "${duration}" "${reason}" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
cycle_dir = path.parent

def service_succeeded(name):
    candidate = cycle_dir / name
    return candidate.is_file() and 'success=True' in candidate.read_text()

def load_json(name):
    candidate = cycle_dir / name
    if not candidate.is_file():
        return None
    return json.loads(candidate.read_text())

payload = {
    'cycle': int(sys.argv[2]),
    'result': sys.argv[3],
    'shutdown_duration_seconds': float(sys.argv[4]),
    'failure_reason': sys.argv[5],
    'simulation_start_success': service_succeeded('start_result.txt'),
    'mode_start_success': service_succeeded('mapping_start_result.txt'),
    'mode_stop_success': service_succeeded('mapping_stop_result.txt'),
    'simulation_stop_success': service_succeeded('stop_result.txt'),
    'duplicate_check': load_json('duplicate_result.json'),
    'remaining_process_check': load_json('remaining_process_result.json'),
    'cleanup_check': load_json('cleanup_result.json'),
    'critical_ros_nodes_after': load_json('critical_ros_nodes_after.json'),
    'critical_os_processes_after': load_json('critical_os_processes_after.json'),
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
PY
}

run_crash_recovery_test() {
  CURRENT_CYCLE_DIR="${EVIDENCE_ROOT}/crash_recovery"
  mkdir -p "${CURRENT_CYCLE_DIR}"
  local report_marker="${CURRENT_CYCLE_DIR}/shutdown_reports.marker"
  touch "${report_marker}"

  PYTHONPATH="${REPO_ROOT}/ros2_ws/src/cpp_robotics_sim_ros/scripts:${PYTHONPATH:-}" \
    python3 -m pytest -q \
      "${REPO_ROOT}/ros2_ws/src/cpp_robotics_sim_ros/test/test_process_lifecycle.py" \
      -k second_pgid \
      >"${CURRENT_CYCLE_DIR}/different_pgid_same_sid_regression.txt" 2>&1 \
      || return 40

  OPEN_BROWSER=false DASHBOARD_PORT="${DASHBOARD_PORT}" \
    ROSBRIDGE_PORT="${ROSBRIDGE_PORT}" \
    python3 -c '
import os
import signal
import sys
os.setsid()
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])
' "${REPO_ROOT}/scripts/run.sh" \
    >"${CURRENT_CYCLE_DIR}/platform.log" 2>&1 &
  RUN_PID=$!

  wait_until "${STARTUP_TIMEOUT_SECONDS}" http_ready || return 41
  wait_until "${STARTUP_TIMEOUT_SECONDS}" simulation_service_ready || return 42
  ros2 service call /simulation/start std_srvs/srv/Trigger '{}' \
    >"${CURRENT_CYCLE_DIR}/first_start_result.txt" 2>&1 || return 43
  grep -q 'success=True' "${CURRENT_CYCLE_DIR}/first_start_result.txt" || return 44
  wait_until "${STARTUP_TIMEOUT_SECONDS}" registry_has_simulation || return 45
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_before_leader_kill.json"
  snapshot_critical_os_processes \
    "${CURRENT_CYCLE_DIR}/processes_before_leader_kill.json"

  python3 - "${REGISTRY_PATH}" \
    "${CURRENT_CYCLE_DIR}/leader_kill_identity.json" <<'PY'
import json, os, pathlib, signal, sys
from process_registry import ProcessRegistry, verify_process_identity
records = [
    record for record in ProcessRegistry().list_records()
    if record.component == 'simulation_launch'
]
if len(records) != 1 or not verify_process_identity(records[0]):
    raise SystemExit(1)
record = records[0]
pathlib.Path(sys.argv[2]).write_text(
    json.dumps(record.to_mapping(), indent=2, sort_keys=True) + '\n'
)
os.kill(record.pid, signal.SIGKILL)
PY

  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" registry_is_clean || return 46
  copy_shutdown_reports \
    "${CURRENT_CYCLE_DIR}/leader_death_reports" "${report_marker}"
  python3 - "${CURRENT_CYCLE_DIR}/leader_death_reports/simulation_launch.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.is_file(): raise SystemExit(1)
report = json.loads(path.read_text())
raise SystemExit(0 if (
    report.get('success') is True
    and any(
        attempt.get('signal') == 'SIGINT'
        and attempt.get('result') == 'sent'
        for attempt in report.get('signals_attempted', [])
    )
) else 1)
PY
  touch "${report_marker}"

  ros2 service call /simulation/start std_srvs/srv/Trigger '{}' \
    >"${CURRENT_CYCLE_DIR}/second_start_result.txt" 2>&1 || return 47
  grep -q 'success=True' "${CURRENT_CYCLE_DIR}/second_start_result.txt" || return 48
  wait_until "${STARTUP_TIMEOUT_SECONDS}" registry_has_simulation || return 49
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_before_manager_kill.json"

  python3 - "${CURRENT_CYCLE_DIR}/manager_kill_identity.json" <<'PY'
import json, os, pathlib, signal, sys
from process_registry import ProcessRegistry, capture_process_identity
records = [
    record for record in ProcessRegistry().list_records()
    if record.component == 'simulation_launch'
]
if len(records) != 1: raise SystemExit(1)
parent = capture_process_identity(records[0].parent_pid)
arguments = json.loads(parent.cmdline_fingerprint)
if not any(pathlib.Path(value).name == 'simulation_manager_node.py'
           for value in arguments[:3]):
    raise SystemExit(1)
pathlib.Path(sys.argv[1]).write_text(json.dumps({
    'pid': parent.pid,
    'ppid': parent.parent_pid,
    'pgid': parent.pgid,
    'sid': parent.session_id,
    'exe': parent.exe,
    'cmdline_fingerprint': parent.cmdline_fingerprint,
}, indent=2, sort_keys=True) + '\n')
os.kill(parent.pid, signal.SIGKILL)
PY

  python3 - "${CURRENT_CYCLE_DIR}/platform_kill_identity.json" <<'PY'
import json, os, pathlib, signal, sys
from process_registry import capture_process_identity
from runtime_verification import snapshot_critical_os_processes
matches = [
    item for item in snapshot_critical_os_processes()
    if item['component'] == 'platform_launch'
]
if len(matches) != 1: raise SystemExit(1)
identity = capture_process_identity(matches[0]['pid'])
if identity.pid != identity.pgid or identity.pid != identity.session_id:
    raise SystemExit(1)
pathlib.Path(sys.argv[1]).write_text(json.dumps({
    'pid': identity.pid,
    'ppid': identity.parent_pid,
    'pgid': identity.pgid,
    'sid': identity.session_id,
    'exe': identity.exe,
    'cmdline_fingerprint': identity.cmdline_fingerprint,
}, indent=2, sort_keys=True) + '\n')
os.kill(identity.pid, signal.SIGKILL)
PY

  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" platform_leader_exited || return 50
  wait "${RUN_PID}" 2>/dev/null || true
  RUN_PID=""
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" ports_released || return 51
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" registry_is_clean || return 52
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" critical_os_processes_absent || return 53
  copy_shutdown_reports \
    "${CURRENT_CYCLE_DIR}/final_shutdown_reports" "${report_marker}"
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_final.json"
  python3 - "${CURRENT_CYCLE_DIR}/result.json" <<'PY'
import json, pathlib, sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({
    'success': True,
    'simulation_launch_leader_death_recovered': True,
    'simulation_manager_death_recovered': True,
    'platform_launch_death_recovered': True,
    'registry_clean': True,
    'ports_released': True,
    'critical_os_processes_absent': True,
}, indent=2, sort_keys=True) + '\n')
PY
}

run_cycle() {
  local cycle="$1"
  local cycle_label
  printf -v cycle_label '%02d' "${cycle}"
  CURRENT_CYCLE_DIR="${EVIDENCE_ROOT}/cycle_${cycle_label}"
  mkdir -p "${CURRENT_CYCLE_DIR}"
  local report_marker="${CURRENT_CYCLE_DIR}/shutdown_reports.marker"
  touch "${report_marker}"

  OPEN_BROWSER=false DASHBOARD_PORT="${DASHBOARD_PORT}" \
    ROSBRIDGE_PORT="${ROSBRIDGE_PORT}" \
    python3 -c '
import os
import signal
import sys
os.setsid()
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])
' "${REPO_ROOT}/scripts/run.sh" \
    >"${CURRENT_CYCLE_DIR}/platform.log" 2>&1 &
  RUN_PID=$!

  wait_until "${STARTUP_TIMEOUT_SECONDS}" http_ready || return 11
  wait_until "${STARTUP_TIMEOUT_SECONDS}" \
    port_is_listening "${ROSBRIDGE_PORT}" || return 12
  wait_until "${STARTUP_TIMEOUT_SECONDS}" simulation_service_ready || return 13

  ros2 service call /simulation/start std_srvs/srv/Trigger '{}' \
    >"${CURRENT_CYCLE_DIR}/start_result.txt" 2>&1 || return 14
  grep -q 'success=True' "${CURRENT_CYCLE_DIR}/start_result.txt" || return 15
  wait_until "${STARTUP_TIMEOUT_SECONDS}" registry_has_simulation || return 16
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_active.json"
  snapshot_critical_os_processes \
    "${CURRENT_CYCLE_DIR}/critical_os_processes_simulation.json"

  ros2 service call /mode/mapping std_srvs/srv/Trigger '{}' \
    >"${CURRENT_CYCLE_DIR}/mapping_start_result.txt" 2>&1 || return 17
  grep -q 'success=True' \
    "${CURRENT_CYCLE_DIR}/mapping_start_result.txt" || return 18
  wait_until "${STARTUP_TIMEOUT_SECONDS}" registry_has_mapping || return 19
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_mode_active.json"
  snapshot_critical_os_processes \
    "${CURRENT_CYCLE_DIR}/critical_os_processes_mode.json"

  # A freshly stopped DDS participant can remain visible until discovery
  # converges. Poll the live graph rather than accepting or rejecting one
  # transient snapshot; a persistent critical duplicate still fails the cycle.
  wait_until "${STARTUP_TIMEOUT_SECONDS}" \
    critical_ros_duplicates_absent || return 20

  ros2 service call /mode/stop std_srvs/srv/Trigger '{}' \
    >"${CURRENT_CYCLE_DIR}/mapping_stop_result.txt" 2>&1 || return 21
  grep -q 'success=True' \
    "${CURRENT_CYCLE_DIR}/mapping_stop_result.txt" || return 22
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" \
    registry_has_only_simulation || return 23

  local shutdown_start shutdown_end duration
  shutdown_start="$(date +%s%N)"
  ros2 service call /simulation/stop std_srvs/srv/Trigger '{}' \
    >"${CURRENT_CYCLE_DIR}/stop_result.txt" 2>&1 || return 24
  grep -q 'success=True' "${CURRENT_CYCLE_DIR}/stop_result.txt" || return 25
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" registry_is_clean || return 26
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_after_stop.json"
  copy_shutdown_reports \
    "${CURRENT_CYCLE_DIR}/shutdown_reports" "${report_marker}"
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" \
    recorded_owned_processes_absent || return 31

  local platform_pgid="${RUN_PID}"
  kill -INT -- "-${RUN_PID}" || return 27
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" \
    platform_leader_exited || return 28
  wait "${RUN_PID}" 2>/dev/null || true
  RUN_PID=""
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" \
    platform_group_exited "${platform_pgid}" || return 28
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" ports_released || return 29
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" \
    critical_os_processes_absent || return 32
  wait_until "${SHUTDOWN_TIMEOUT_SECONDS}" \
    critical_ros_nodes_absent || return 33
  snapshot_registry "${CURRENT_CYCLE_DIR}/registry_final.json"
  shutdown_end="$(date +%s%N)"
  duration="$(awk -v start="${shutdown_start}" -v end="${shutdown_end}" \
    'BEGIN {printf "%.6f", (end-start)/1000000000}')"
  awk -v duration="${duration}" \
    'BEGIN {exit !(duration <= 15.0)}' || return 30
  python3 - "${CURRENT_CYCLE_DIR}/cleanup_result.json" <<'PY'
import json, pathlib, sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({
    'platform_process_group_exited': True,
    'ports_released': True,
    'registry_clean': True,
    'critical_os_processes_absent': True,
    'critical_ros_nodes_absent': True,
}, indent=2, sort_keys=True) + '\n')
PY
  write_cycle_result "${cycle}" PASS "${duration}" ''
}

main() {
  local passed=0 cycle status reason crash_status=0
  trap force_cleanup EXIT INT TERM

  if [[ "${CRASH_RECOVERY_TEST}" == "true" ]]; then
    printf 'v0.1.1 crash/orphan recovery preflight\n'
    set +e
    run_crash_recovery_test
    crash_status=$?
    set -e
    if ((crash_status != 0)); then
      printf '{"success":false,"failure_reason":"gate code %d"}\n' \
        "${crash_status}" >"${CURRENT_CYCLE_DIR}/result.json"
      force_cleanup
    fi
  else
    crash_status=1
  fi

  if ((crash_status == 0)); then
  for ((cycle = 1; cycle <= CYCLE_COUNT; cycle++)); do
    printf 'v0.1.1 cycle %d/%d\n' "${cycle}" "${CYCLE_COUNT}"
    set +e
    run_cycle "${cycle}"
    status=$?
    set -e
    if ((status != 0)); then
      reason="cycle failed at gate code ${status}"
      snapshot_registry "${CURRENT_CYCLE_DIR}/registry_at_failure.json"
      write_cycle_result "${cycle}" FAIL 0 "${reason}"
      force_cleanup
      break
    fi
    passed=$((passed + 1))
  done
  fi

  python3 - "${EVIDENCE_ROOT}" "${CYCLE_COUNT}" "${passed}" \
    "${crash_status}" "${RELEASE_CYCLE_COUNT}" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
requested, passed = int(sys.argv[2]), int(sys.argv[3])
crash_success = int(sys.argv[4]) == 0
release_cycle_count = int(sys.argv[5])
results = [json.loads(path.read_text()) for path in sorted(root.glob('cycle_*/result.json'))]
cycle_run_success = passed == requested and len(results) == requested
release_verified = (
    cycle_run_success and crash_success and requested == release_cycle_count
)
summary = {
    'requested_cycles': requested,
    'passed_cycles': passed,
    'required_release_cycles': release_cycle_count,
    'cycle_run_success': cycle_run_success,
    'crash_recovery_success': crash_success,
    'release_verified': release_verified,
    'success': release_verified,
    'cycles': results,
    'maximum_shutdown_duration_seconds': max(
        (item['shutdown_duration_seconds'] for item in results), default=0.0
    ),
}
(root / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
if release_verified:
    decision = 'PASS: v0.1.1 runtime acceptance verified\n'
elif cycle_run_success and crash_success:
    decision = (
        'INCOMPLETE: smoke run passed; exactly 10 cycles are required for '
        'v0.1.1 release acceptance\n'
    )
else:
    decision = 'FAIL: v0.1.1 runtime acceptance not verified\n'
(root / 'release_decision.txt').write_text(decision)
raise SystemExit(0 if cycle_run_success and crash_success else 1)
PY
  printf 'Evidence: %s\n' "${EVIDENCE_ROOT}"
}

main "$@"
