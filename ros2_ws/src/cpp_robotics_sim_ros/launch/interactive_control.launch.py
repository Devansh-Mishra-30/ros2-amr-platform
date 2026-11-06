# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
)
from launch.launch_description_sources import (
    PythonLaunchDescriptionSource,
)
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    world = LaunchConfiguration('world')
    use_sim_time = LaunchConfiguration('use_sim_time')

    package_share = FindPackageShare(
        'cpp_robotics_sim_ros'
    )

    simulation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    package_share,
                    'launch',
                    'ros2_control.launch.py',
                ]
            )
        ),
        launch_arguments={
            'world': world,
            'use_sim_time': use_sim_time,
        }.items(),
    )

    command_mux = Node(
        package='cpp_robotics_sim_ros',
        executable='command_mux_node.py',
        name='command_mux',
        output='screen',
        parameters=[
            PathJoinSubstitution(
                [
                    package_share,
                    'config',
                    'command_mux.yaml',
                ]
            ),
            {
                'use_sim_time': use_sim_time,
            },
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'world',
                default_value=PathJoinSubstitution(
                    [
                        package_share,
                        'worlds',
                        'empty_diffbot_world.sdf',
                    ]
                ),
                description='Path to Gazebo world SDF file',
            ),
            DeclareLaunchArgument(
                'use_sim_time',
                default_value='true',
                description='Use Gazebo simulation time',
            ),
            simulation,
            command_mux,
        ]
    )
