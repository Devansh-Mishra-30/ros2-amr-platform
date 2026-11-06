# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

import os

from ament_index_python.packages import (
    get_package_share_directory,
)
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
)
from launch.launch_description_sources import (
    PythonLaunchDescriptionSource,
)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time = LaunchConfiguration(
        'use_sim_time'
    )
    map_yaml = LaunchConfiguration('map')

    package_share_dir = get_package_share_directory(
        'cpp_robotics_sim_ros'
    )
    nav2_bringup_dir = get_package_share_directory(
        'nav2_bringup'
    )

    nav2_params = os.path.join(
        package_share_dir,
        'nav2',
        'diffbot_nav2_params.yaml',
    )

    localization_launch_file = os.path.join(
        nav2_bringup_dir,
        'launch',
        'localization_launch.py',
    )

    scan_frame_bridge = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='scan_frame_bridge',
        arguments=[
            '0',
            '0',
            '0',
            '0',
            '0',
            '0',
            'lidar_link',
            'diffbot/base_link/diffbot_lidar',
        ],
        output='screen',
    )

    cmd_vel_bridge = Node(
        package='cpp_robotics_sim_ros',
        executable='cmd_vel_twist_bridge.py',
        name='cmd_vel_twist_bridge',
        output='screen',
        parameters=[
            {
                'use_sim_time': use_sim_time,
                'input_topic': '/cmd_vel',
                'output_topic': '/cmd_vel/navigation',
                'frame_id': 'base_link',
            },
        ],
    )

    localization_stack = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            localization_launch_file
        ),
        launch_arguments={
            'map': map_yaml,
            'use_sim_time': use_sim_time,
            'params_file': nav2_params,
            'autostart': 'true',
            'use_composition': 'False',
        }.items(),
    )

    controller_server = Node(
        package='nav2_controller',
        executable='controller_server',
        name='controller_server',
        output='screen',
        parameters=[
            nav2_params,
            {
                'use_sim_time': use_sim_time,
            },
        ],
        remappings=[
            (
                '/cmd_vel',
                '/cmd_vel_nav_raw',
            ),
        ],
    )

    planner_server = Node(
        package='nav2_planner',
        executable='planner_server',
        name='planner_server',
        output='screen',
        parameters=[
            nav2_params,
            {
                'use_sim_time': use_sim_time,
            },
        ],
    )

    behavior_server = Node(
        package='nav2_behaviors',
        executable='behavior_server',
        name='behavior_server',
        output='screen',
        parameters=[
            nav2_params,
            {
                'use_sim_time': use_sim_time,
            },
        ],
        remappings=[
            (
                '/cmd_vel',
                '/cmd_vel_nav_raw',
            ),
        ],
    )

    bt_navigator = Node(
        package='nav2_bt_navigator',
        executable='bt_navigator',
        name='bt_navigator',
        output='screen',
        parameters=[
            nav2_params,
            {
                'use_sim_time': use_sim_time,
            },
        ],
    )

    waypoint_follower = Node(
        package='nav2_waypoint_follower',
        executable='waypoint_follower',
        name='waypoint_follower',
        output='screen',
        parameters=[
            nav2_params,
            {
                'use_sim_time': use_sim_time,
            },
        ],
    )

    velocity_smoother = Node(
        package='nav2_velocity_smoother',
        executable='velocity_smoother',
        name='velocity_smoother',
        output='screen',
        parameters=[
            nav2_params,
            {
                'use_sim_time': use_sim_time,
            },
        ],
        remappings=[
            (
                '/cmd_vel',
                '/cmd_vel_nav_raw',
            ),
            (
                '/cmd_vel_smoothed',
                '/cmd_vel',
            ),
        ],
    )

    lifecycle_manager_navigation = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_navigation',
        output='screen',
        parameters=[
            {
                'use_sim_time': use_sim_time,
                'autostart': True,
                'bond_timeout': 0.0,
                'node_names': [
                    'controller_server',
                    'planner_server',
                    'behavior_server',
                    'bt_navigator',
                    'waypoint_follower',
                    'velocity_smoother',
                ],
            },
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'use_sim_time',
                default_value='true',
                description='Use Gazebo simulation time',
            ),
            DeclareLaunchArgument(
                'map',
                description=(
                    'Absolute path to saved map YAML'
                ),
            ),
            scan_frame_bridge,
            cmd_vel_bridge,
            localization_stack,
            controller_server,
            planner_server,
            behavior_server,
            bt_navigator,
            waypoint_follower,
            velocity_smoother,
            lifecycle_manager_navigation,
        ]
    )
