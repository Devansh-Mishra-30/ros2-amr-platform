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
    use_sim_time = LaunchConfiguration('use_sim_time')
    package_share = FindPackageShare('cpp_robotics_sim_ros')

    base_simulation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                package_share,
                'launch',
                'ros2_control.launch.py',
            ])
        ),
        launch_arguments={
            'use_sim_time': use_sim_time,
        }.items(),
    )

    imu_sensor_frame_transform = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='imu_sensor_frame_transform',
        output='screen',
        arguments=[
            '--x', '0.0',
            '--y', '0.0',
            '--z', '0.0',
            '--roll', '0.0',
            '--pitch', '0.0',
            '--yaw', '0.0',
            '--frame-id', 'imu_link',
            '--child-frame-id',
            'diffbot/base_link/diffbot_imu',
        ],
    )

    ekf_node = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[
            PathJoinSubstitution([
                package_share,
                'config',
                'ekf_localization.yaml',
            ]),
            {
                'use_sim_time': use_sim_time,
            },
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='true',
            description='Use Gazebo simulation time',
        ),
        base_simulation,
        imu_sensor_frame_transform,
        ekf_node,
    ])
