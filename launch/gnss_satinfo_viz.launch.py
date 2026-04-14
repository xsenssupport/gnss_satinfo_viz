from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    topic_arg = DeclareLaunchArgument(
        'topic',
        default_value='/gnss/satinfo',
        description='Topic name for GnssSatInfo messages',
    )
    show_zero_arg = DeclareLaunchArgument(
        'show_zero_cno',
        default_value='false',
        description='Show satellites with CNO = 0 (no signal)',
    )

    viz_node = Node(
        package='gnss_satinfo_viz',
        executable='gnss_satinfo_viz_node',
        name='gnss_satinfo_viz_node',
        output='screen',
        parameters=[{
            'topic':         LaunchConfiguration('topic'),
            'show_zero_cno': LaunchConfiguration('show_zero_cno'),
        }],
    )

    return LaunchDescription([topic_arg, show_zero_arg, viz_node])
