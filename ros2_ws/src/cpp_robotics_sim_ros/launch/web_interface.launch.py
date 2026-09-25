# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

import atexit
import fcntl
import os
from pathlib import Path
import shutil
import sys

from ament_index_python.packages import (
    get_package_prefix,
    get_package_share_directory,
)
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    LogInfo,
    TimerAction,
)
from launch.conditions import IfCondition
from launch.substitutions import (
    LaunchConfiguration,
    PythonExpression,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


_LOCK_FILE_HANDLE = None

PROJECT_PACKAGE = 'cpp_robotics_sim_ros'


def get_single_instance_lock_path() -> Path:
    """Return the per-user lock path for the dashboard runtime."""
    return (
        Path.home()
        / '.ros'
        / 'cpp_robotics_sim'
        / 'web_interface.lock'
    )


def acquire_single_instance_lock() -> None:
    """
    Prevent multiple web-interface launch instances.

    The open lock-file handle must remain alive for the entire launch.
    """
    global _LOCK_FILE_HANDLE

    lock_path = get_single_instance_lock_path()

    lock_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    lock_file = lock_path.open('a+', encoding='utf-8')
    ownership_acquired = False
    ownership_transferred = False

    try:
        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as error:
            raise RuntimeError(
                'Another robotics dashboard instance is already '
                'running. Stop it before launching another copy.'
            ) from error

        ownership_acquired = True
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()

        _LOCK_FILE_HANDLE = lock_file
        ownership_transferred = True
    finally:
        if ownership_transferred:
            return

        if ownership_acquired:
            try:
                fcntl.flock(
                    lock_file.fileno(),
                    fcntl.LOCK_UN,
                )
            except OSError:
                pass

        lock_file.close()


def release_single_instance_lock() -> None:
    global _LOCK_FILE_HANDLE

    if _LOCK_FILE_HANDLE is None:
        return

    try:
        fcntl.flock(
            _LOCK_FILE_HANDLE.fileno(),
            fcntl.LOCK_UN,
        )
    finally:
        _LOCK_FILE_HANDLE.close()
        _LOCK_FILE_HANDLE = None


def cleanup_runtime_admission() -> None:
    """Recover registered groups before releasing single-instance ownership."""
    try:
        recover_verified_owned_processes()
    except Exception as error:
        print(
            '[web_interface] verified process recovery failed during exit: '
            + str(error),
            file=sys.stderr,
            flush=True,
        )
    finally:
        release_single_instance_lock()


def prepare_runtime_admission() -> None:
    """Acquire runtime ownership before recovering stale processes."""
    acquire_single_instance_lock()

    try:
        recover_verified_owned_processes()
    except Exception:
        release_single_instance_lock()
        raise


def recover_verified_owned_processes() -> None:
    """Stop only process groups whose persisted identity is still proven."""
    source_directory = Path(__file__).resolve().parents[1] / 'scripts'
    if (source_directory / 'process_registry.py').is_file():
        module_directory = source_directory
    else:
        module_directory = (
            Path(get_package_prefix(PROJECT_PACKAGE))
            / 'lib'
            / PROJECT_PACKAGE
        )
    if str(module_directory) not in sys.path:
        sys.path.insert(0, str(module_directory))

    from process_lifecycle import (
        persist_shutdown_result,
        recover_owned_processes,
    )
    from process_registry import ProcessRegistry

    registry = ProcessRegistry()
    reports = recover_owned_processes(registry)
    failures = []
    for report in reports:
        persist_shutdown_result(report)
        if not report.success:
            failures.append(report.to_mapping())

    if failures:
        raise RuntimeError(
            'Unable to safely recover verified owned processes: '
            + repr(failures)
        )


def validate_workspace(
    package_share: Path,
) -> None:
    """
    Reject the obsolete project-root install tree.

    This package must resolve through ros2_ws/install.
    """
    resolved_share = package_share.resolve()
    resolved_text = str(resolved_share)

    expected_fragment = (
        '/ros2_ws/install/'
        f'{PROJECT_PACKAGE}/share/{PROJECT_PACKAGE}'
    )

    if expected_fragment not in resolved_text:
        raise RuntimeError(
            'Incorrect ROS overlay selected.\n'
            'Expected the package under:\n'
            '  .../ros2_ws/install/'
            f'{PROJECT_PACKAGE}\n'
            'Resolved package share:\n'
            f'  {resolved_share}\n'
            'Source only ros2_ws/install/setup.bash.'
        )


def create_browser_action(
    dashboard_port,
    open_browser,
):
    dashboard_url = PythonExpression(
        [
            "'http://localhost:' + str(",
            dashboard_port,
            ')',
        ]
    )

    if shutil.which('powershell.exe'):
        command = [
            'powershell.exe',
            '-NoProfile',
            '-Command',
            'Start-Process',
            dashboard_url,
        ]
    elif shutil.which('cmd.exe'):
        command = [
            'cmd.exe',
            '/C',
            'start',
            '',
            dashboard_url,
        ]
    elif shutil.which('xdg-open'):
        command = [
            'xdg-open',
            dashboard_url,
        ]
    else:
        return LogInfo(
            msg=(
                'Automatic browser opening is unavailable. '
                'Open http://localhost:8080 manually.'
            )
        )

    return TimerAction(
        period=2.0,
        actions=[
            ExecuteProcess(
                cmd=command,
                output='screen',
                condition=IfCondition(open_browser),
            )
        ],
    )


def _build_launch_description():
    websocket_port = LaunchConfiguration(
        'websocket_port'
    )
    dashboard_port = LaunchConfiguration(
        'dashboard_port'
    )
    open_browser = LaunchConfiguration(
        'open_browser'
    )
    mode_startup_grace_period = LaunchConfiguration(
        'mode_startup_grace_period'
    )

    package_share = Path(
        get_package_share_directory(
            PROJECT_PACKAGE
        )
    )

    validate_workspace(package_share)

    dashboard_directory = (
        package_share
        / 'web'
        / 'dashboard'
    )

    simulation_manager_config = (
        package_share
        / 'config'
        / 'simulation_manager.yaml'
    )

    environment_registry_config = (
        package_share
        / 'config'
        / 'environment_registry.yaml'
    )

    mode_manager_config = (
        package_share
        / 'config'
        / 'mode_manager.yaml'
    )

    mapping_manager_config = (
        package_share
        / 'config'
        / 'mapping_manager.yaml'
    )

    localization_manager_config = (
        package_share
        / 'config'
        / 'localization_manager.yaml'
    )

    required_paths = (
        dashboard_directory,
        simulation_manager_config,
        environment_registry_config,
        mode_manager_config,
        mapping_manager_config,
        localization_manager_config,
    )

    missing_paths = [
        str(path)
        for path in required_paths
        if not path.exists()
    ]

    if missing_paths:
        raise RuntimeError(
            'Required installed dashboard files are missing:\n'
            + '\n'.join(
                f'  {path}'
                for path in missing_paths
            )
            + '\nRebuild cpp_robotics_sim_ros.'
        )

    simulation_manager = Node(
        package=PROJECT_PACKAGE,
        executable='simulation_manager_node.py',
        name='simulation_manager',
        output='screen',
        parameters=[
            str(simulation_manager_config),
            str(environment_registry_config),
            {
                'use_sim_time': False,
            },
        ],
    )

    mode_manager = Node(
        package=PROJECT_PACKAGE,
        executable='mode_manager_node.py',
        name='mode_manager',
        output='screen',
        parameters=[
            str(mode_manager_config),
            {
                'use_sim_time': False,
                'startup_grace_period': ParameterValue(
                    mode_startup_grace_period, value_type=float,
                ),
            },
        ],
    )

    mapping_manager = Node(
        package=PROJECT_PACKAGE,
        executable='mapping_manager_node.py',
        name='mapping_manager',
        output='screen',
        parameters=[
            str(mapping_manager_config),
            {
                'use_sim_time': False,
            },
        ],
    )

    localization_manager = Node(
        package=PROJECT_PACKAGE,
        executable='localization_manager_node.py',
        name='localization_manager',
        output='screen',
        parameters=[
            str(localization_manager_config),
            {
                'use_sim_time': False,
            },
        ],
    )

    navigation_goal_manager = Node(
        package=PROJECT_PACKAGE,
        executable='navigation_goal_manager_node.py',
        name='navigation_goal_manager',
        output='screen',
        parameters=[
            {
                'use_sim_time': True,
                'action_name': '/navigate_to_pose',
                'goal_frame': 'map',
                'server_wait_timeout': 2.0,
            },
        ],
    )

    platform_lifecycle_orchestrator = Node(
        package=PROJECT_PACKAGE,
        executable='platform_lifecycle_orchestrator_node.py',
        name='platform_lifecycle_orchestrator',
        output='screen',
        parameters=[{'use_sim_time': False}],
    )

    rosbridge_websocket = Node(
        package='rosbridge_server',
        executable='rosbridge_websocket',
        name='rosbridge_websocket',
        output='screen',
        parameters=[
            {
                'port': websocket_port,
                'address': '0.0.0.0',
                'retry_startup_delay': 5.0,
                'fragment_timeout': 600,
                'delay_between_messages': 0.0,
                'max_message_size': 10_000_000,
                'unregister_timeout': 10.0,
                'use_compression': False,
            },
        ],
    )

    dashboard_server = ExecuteProcess(
        cmd=[
            'python3',
            '-m',
            'http.server',
            dashboard_port,
            '--bind',
            '0.0.0.0',
            '--directory',
            str(dashboard_directory),
        ],
        output='screen',
    )

    browser_action = create_browser_action(
        dashboard_port,
        open_browser,
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'websocket_port',
                default_value='9090',
                description=(
                    'Rosbridge WebSocket port'
                ),
            ),
            DeclareLaunchArgument(
                'dashboard_port',
                default_value='8080',
                description=(
                    'Dashboard HTTP port'
                ),
            ),
            DeclareLaunchArgument(
                'open_browser',
                default_value='true',
                description=(
                    'Automatically open the dashboard '
                    'in the default browser'
                ),
            ),
            DeclareLaunchArgument(
                'mode_startup_grace_period',
                default_value='3.0',
                description=(
                    'Mode launch identity-capture grace period in seconds'
                ),
            ),
            LogInfo(
                msg=(
                    'Dashboard safety preflight passed.'
                )
            ),
            LogInfo(
                msg=[
                    'Package share: ',
                    str(package_share),
                ]
            ),
            LogInfo(
                msg=[
                    'Dashboard URL: http://localhost:',
                    dashboard_port,
                ]
            ),
            simulation_manager,
            mode_manager,
            mapping_manager,
            localization_manager,
            navigation_goal_manager,
            platform_lifecycle_orchestrator,
            rosbridge_websocket,
            dashboard_server,
            browser_action,
        ]
    )


def generate_launch_description():
    """Acquire runtime ownership and build the launch description safely."""
    prepare_runtime_admission()

    try:
        description = _build_launch_description()
        atexit.register(cleanup_runtime_admission)
        return description
    except Exception:
        release_single_instance_lock()
        raise
