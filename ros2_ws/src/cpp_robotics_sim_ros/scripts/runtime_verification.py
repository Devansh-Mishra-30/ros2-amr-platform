#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Small deterministic checks used by v0.1.1 runtime verification."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence


CRITICAL_ROS_NODES = frozenset(
    {
        '/simulation_manager', '/mode_manager', '/mapping_manager',
        '/localization_manager', '/navigation_goal_manager',
        '/rosbridge_websocket', '/controller_manager', '/slam_toolbox',
        '/amcl', '/controller_server', '/planner_server',
        '/behavior_server', '/bt_navigator', '/waypoint_follower',
        '/velocity_smoother',
        '/scan_frame_bridge', '/command_mux', '/clock_bridge',
        '/scan_bridge', '/imu_bridge', '/robot_state_publisher',
        '/joint_state_publisher', '/joint_state_broadcaster',
        '/diff_drive_controller', '/gz_ros_control',
        '/lifecycle_manager_slam', '/lifecycle_manager_localization',
        '/lifecycle_manager_navigation',
    }
)

_MANAGER_EXECUTABLES = {
    'simulation_manager_node.py': 'simulation_manager',
    'mode_manager_node.py': 'mode_manager',
    'mapping_manager_node.py': 'mapping_manager',
    'localization_manager_node.py': 'localization_manager',
    'navigation_goal_manager_node.py': 'navigation_goal_manager',
}

_LAUNCH_COMPONENTS = {
    'web_interface.launch.py': 'platform_launch',
    'interactive_control.launch.py': 'simulation_launch',
    'slam_mapping.launch.py': 'mode_mapping',
    'amcl_localization.launch.py': 'mode_localization',
    'nav2_navigation.launch.py': 'mode_navigation',
}


def find_duplicate_ros_nodes(
    node_names: Iterable[str],
    critical_nodes: frozenset[str] = CRITICAL_ROS_NODES,
) -> dict[str, int]:
    """Count exact-name duplicates in one ROS domain's graph snapshot."""
    counts = Counter(name.strip() for name in node_names if name.strip())
    return {
        name: count
        for name, count in sorted(counts.items())
        if name in critical_nodes and count > 1
    }


def classify_critical_os_process(arguments: Sequence[str]) -> str | None:
    """Classify only exact AMR entry points; this function never signals."""
    for argument in arguments[:3]:
        component = _MANAGER_EXECUTABLES.get(Path(argument).name)
        if component is not None:
            return component

    for index in range(max(0, len(arguments) - 3)):
        if (
            Path(arguments[index]).name == 'ros2'
            and arguments[index + 1:index + 3]
            == ['launch', 'cpp_robotics_sim_ros']
        ):
            return _LAUNCH_COMPONENTS.get(arguments[index + 3])

    if len(arguments) >= 3 and arguments[1:3] == ['-m', 'http.server']:
        return 'dashboard_http_server'

    for argument in arguments[:3]:
        if Path(argument).name == 'rosbridge_websocket':
            return 'rosbridge_websocket'

    return None


def find_duplicate_os_processes(
    processes: Iterable[Mapping[str, object]],
) -> dict[str, list[int]]:
    """Return exact-entry-point OS duplicates separately from ROS nodes."""
    grouped: dict[str, list[int]] = {}
    for process in processes:
        arguments = process.get('arguments')
        pid = process.get('pid')
        if not isinstance(arguments, list) or not isinstance(pid, int):
            continue
        if not all(isinstance(argument, str) for argument in arguments):
            continue
        component = classify_critical_os_process(arguments)
        if component is not None:
            grouped.setdefault(component, []).append(pid)
    return {
        component: sorted(pids)
        for component, pids in sorted(grouped.items())
        if len(pids) > 1
    }


def snapshot_critical_os_processes(
    proc_root: Path = Path('/proc'),
) -> list[dict[str, object]]:
    """Snapshot current-user critical AMR processes without name-based action."""
    snapshot = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.geteuid():
                continue
            raw_arguments = (entry / 'cmdline').read_bytes()
            arguments = [
                value.decode('utf-8', errors='surrogateescape')
                for value in raw_arguments.split(b'\0')
                if value
            ]
            component = classify_critical_os_process(arguments)
            if component is None:
                continue
            stat_text = (entry / 'stat').read_text(encoding='utf-8')
            closing = stat_text.rfind(')')
            fields = stat_text[closing + 1:].strip().split()
            snapshot.append(
                {
                    'component': component,
                    'pid': int(entry.name),
                    'parent_pid': int(fields[1]),
                    'pgid': int(fields[2]),
                    'session_id': int(fields[3]),
                    'arguments': arguments,
                }
            )
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            continue
    return sorted(snapshot, key=lambda item: int(item['pid']))
