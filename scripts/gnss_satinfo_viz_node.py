#!/usr/bin/env python3
"""
gnss_satinfo_viz_node.py
========================
ROS 2 node that subscribes to /gnss/satinfo (GnssSatInfo) and
renders a real-time Matplotlib bar chart matching the u-center style.

Colour scheme
-------------
Each bar is coloured by its *status*, not its GNSS system:
  Detected (unused) – light blue  (#87CEEB  / skyblue)
  Used              – dark green  (#006400)
  Used + Differential – bright green (#00C800)
  Unhealthy         – red         (#CC0000)

The X-axis label is  "<gnss_id>:<sv_id>"  (e.g. "0:3", "3:16").
GNSS identifiers: 0=GPS  1=SBAS  2=Galileo  3=BeiDou  4=IMES  5=QZSS  6=GLONASS
"""

import threading
import rclpy
from rclpy.node import Node

import matplotlib
matplotlib.use('TkAgg')          # change to 'Qt5Agg' / 'GTK3Agg' if needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ---------------------------------------------------------------------------
# Try to import the custom message.  If the workspace has not been sourced yet
# fall back to a lightweight stub so the file can at least be linted / tested.
# ---------------------------------------------------------------------------
try:
    from gnss_satinfo_viz.msg import GnssSatInfo  # type: ignore  # noqa: E402
    MSG_AVAILABLE = True
except ImportError:
    MSG_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GNSS_NAMES = {
    0: 'GPS',
    1: 'SBAS',
    2: 'Galileo',
    3: 'BeiDou',
    4: 'IMES',
    5: 'QZSS',
    6: 'GLONASS',
}

# Flag bit masks (mirrors the .msg constants)
FLAGS_SIGNAL_QUALITY_MASK   = 0x07
FLAGS_USED_FOR_NAV_MASK     = 0x08
FLAGS_HEALTH_MASK           = 0x30
FLAGS_HEALTH_UNHEALTHY      = 0x20
FLAGS_DIFFERENTIAL_MASK     = 0x40

# Bar colours  ── match u-center / attached screenshot exactly
COLOR_DETECTED   = '#87CEEB'   # light blue   – detected but not used
COLOR_USED       = '#006400'   # dark green   – used for navigation
COLOR_USED_DIFF  = '#00C800'   # bright green – used + differential
COLOR_UNHEALTHY  = '#CC0000'   # red          – unhealthy

# Y-axis range  (dBHz)
Y_MIN, Y_MAX = 0, 50

# How often to redraw [s]  – set lower for smoother feel
REDRAW_INTERVAL = 0.1


# ---------------------------------------------------------------------------
def classify_bar(flags: int) -> str:
    """Return one of 'unhealthy', 'used_diff', 'used', 'detected'."""
    health = flags & FLAGS_HEALTH_MASK
    if health == FLAGS_HEALTH_UNHEALTHY:
        return 'unhealthy'
    used = bool(flags & FLAGS_USED_FOR_NAV_MASK)
    diff = bool(flags & FLAGS_DIFFERENTIAL_MASK)
    if used and diff:
        return 'used_diff'
    if used:
        return 'used'
    return 'detected'


STATUS_COLOR = {
    'detected':  COLOR_DETECTED,
    'used':      COLOR_USED,
    'used_diff': COLOR_USED_DIFF,
    'unhealthy': COLOR_UNHEALTHY,
}


# ---------------------------------------------------------------------------
class GnssSatinfoVizNode(Node):
    """ROS 2 node – subscribes to /gnss/satinfo and updates a Matplotlib figure."""

    def __init__(self):
        super().__init__('gnss_satinfo_viz_node')

        # Declare parameters
        self.declare_parameter('topic', '/gnss/satinfo')
        self.declare_parameter('window_title', 'GNSS Satellite Status')
        self.declare_parameter('show_zero_cno', False)

        topic       = self.get_parameter('topic').value
        win_title   = self.get_parameter('window_title').value
        self._show_zero = self.get_parameter('show_zero_cno').value

        # Latest satellite data protected by a lock
        self._lock = threading.Lock()
        self._sat_data: list[dict] = []   # list of {label, cno, status}
        self._itow: int = 0
        self._new_data = False

        # Subscribe
        if MSG_AVAILABLE:
            self.create_subscription(
                GnssSatInfo,
                topic,
                self._callback,
                10,
            )
            self.get_logger().info(f'Subscribed to {topic}')
        else:
            self.get_logger().warn(
                'GnssSatInfo message not found – running in demo mode.'
            )
            self._inject_demo_data()

        # Build Matplotlib figure
        self._fig, self._ax = plt.subplots(figsize=(16, 5))
        self._fig.canvas.manager.set_window_title(win_title)
        self._fig.patch.set_facecolor('#1E1E1E')
        self._ax.set_facecolor('#1E1E1E')

        # Legend patches
        legend_items = [
            mpatches.Patch(color=COLOR_DETECTED,  label='Detected (unused)'),
            mpatches.Patch(color=COLOR_USED,       label='Used'),
            mpatches.Patch(color=COLOR_USED_DIFF,  label='Used+D'),
            mpatches.Patch(color=COLOR_UNHEALTHY,  label='Unhealthy'),
        ]
        self._ax.legend(
            handles=legend_items,
            loc='upper right',
            fontsize=8,
            facecolor='#2E2E2E',
            edgecolor='#555555',
            labelcolor='white',
            ncol=4,
        )

        self._ax.set_ylabel('Signal Strength (dBHz)', color='white', fontsize=9)
        self._ax.set_ylim(Y_MIN, Y_MAX)
        self._ax.yaxis.set_tick_params(colors='white')
        self._ax.xaxis.set_tick_params(colors='white', labelsize=7, rotation=90)
        for spine in self._ax.spines.values():
            spine.set_edgecolor('#555555')
        self._ax.grid(axis='y', color='#444444', linewidth=0.5, linestyle='--')
        self._ax.set_title(
            'GNSS Identifiers: 0:GPS  1:SBAS  2:Galileo  3:BeiDou  5:QZSS  6:GLONASS',
            color='#AAAAAA', fontsize=8, loc='left',
        )

        # Timer drives the GUI refresh from the ROS executor thread
        self.create_timer(REDRAW_INTERVAL, self._redraw)

    # ------------------------------------------------------------------
    def _callback(self, msg: 'GnssSatInfo') -> None:
        """Process incoming satellite info message."""
        sats = []
        n = int(msg.num_svs)
        for i in range(min(n, 60)):
            cno    = int(msg.cno[i])
            flags  = int(msg.flags[i])
            gnss   = int(msg.gnss_id[i])
            sv     = int(msg.sv_id[i])
            status = classify_bar(flags)

            if cno == 0 and not self._show_zero:
                continue

            sats.append({
                'label':  f'{gnss}:{sv}',
                'cno':    cno,
                'status': status,
                'gnss':   gnss,
                'sv':     sv,
            })

        # Sort by GNSS system then SV id for a consistent left-to-right order
        sats.sort(key=lambda s: (s['gnss'], s['sv']))

        with self._lock:
            self._sat_data = sats
            self._itow     = int(msg.itow)
            self._new_data = True

    # ------------------------------------------------------------------
    def _inject_demo_data(self) -> None:
        """Populate with synthetic data so the window looks useful without a device."""
        import random, math
        demo = []
        # GPS (0)
        for sv in [1, 3, 4, 6, 9, 11, 14, 17, 19, 22]:
            demo.append({'label': f'0:{sv}', 'cno': random.randint(15, 45),
                         'status': random.choice(['used', 'used', 'used_diff', 'detected']),
                         'gnss': 0, 'sv': sv})
        # Galileo (2)
        for sv in [2, 5, 15, 25]:
            demo.append({'label': f'2:{sv}', 'cno': random.randint(20, 42),
                         'status': random.choice(['used', 'used_diff']),
                         'gnss': 2, 'sv': sv})
        # BeiDou (3)
        for sv in [10, 16, 20, 30]:
            demo.append({'label': f'3:{sv}', 'cno': random.randint(18, 44),
                         'status': random.choice(['used', 'unhealthy', 'detected']),
                         'gnss': 3, 'sv': sv})
        # GLONASS (6)
        for sv in [10, 15, 18, 20]:
            demo.append({'label': f'6:{sv}', 'cno': random.randint(10, 40),
                         'status': random.choice(['detected', 'used']),
                         'gnss': 6, 'sv': sv})
        demo.sort(key=lambda s: (s['gnss'], s['sv']))
        with self._lock:
            self._sat_data = demo
            self._new_data = True

    # ------------------------------------------------------------------
    def _redraw(self) -> None:
        """Called by the ROS timer – refreshes the Matplotlib axes."""
        with self._lock:
            if not self._new_data:
                return
            sats       = list(self._sat_data)
            itow       = self._itow
            self._new_data = False

        if not sats:
            return

        ax = self._ax
        ax.cla()

        labels  = [s['label']  for s in sats]
        heights = [s['cno']    for s in sats]
        colors  = [STATUS_COLOR[s['status']] for s in sats]
        x       = np.arange(len(sats))

        bars = ax.bar(x, heights, color=colors, width=0.7, zorder=2)

        # Value labels on top of each bar
        for bar, h in zip(bars, heights):
            if h > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    h + 0.4,
                    str(h),
                    ha='center', va='bottom',
                    fontsize=6, color='white',
                )

        # X-axis ticks
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=90, fontsize=7, color='white')
        ax.set_xlim(-0.7, len(sats) - 0.3)

        # Y-axis
        ax.set_ylim(Y_MIN, Y_MAX)
        ax.set_yticks(range(0, Y_MAX + 1, 2))
        ax.set_ylabel('Signal Strength (dBHz)', color='white', fontsize=9)
        ax.yaxis.set_tick_params(colors='white')

        # Grid
        ax.set_facecolor('#1E1E1E')
        ax.grid(axis='y', color='#444444', linewidth=0.5, linestyle='--', zorder=0)
        for spine in ax.spines.values():
            spine.set_edgecolor('#555555')

        # Title / legend
        ax.set_title(
            f'GNSS Identifiers: 0:GPS  1:SBAS  2:Galileo  3:BeiDou  5:QZSS  6:GLONASS'
            f'        iTOW: {itow} ms    SVs: {len(sats)}',
            color='#AAAAAA', fontsize=8, loc='left',
        )
        legend_items = [
            mpatches.Patch(color=COLOR_DETECTED,  label='Detected (unused)'),
            mpatches.Patch(color=COLOR_USED,       label='Used'),
            mpatches.Patch(color=COLOR_USED_DIFF,  label='Used+D'),
            mpatches.Patch(color=COLOR_UNHEALTHY,  label='Unhealthy'),
        ]
        ax.legend(
            handles=legend_items,
            loc='upper right',
            fontsize=8,
            facecolor='#2E2E2E',
            edgecolor='#555555',
            labelcolor='white',
            ncol=4,
        )

        try:
            self._fig.canvas.draw_idle()
            self._fig.canvas.flush_events()
        except Exception:
            pass  # window may have been closed


# ---------------------------------------------------------------------------
def main(args=None):
    rclpy.init(args=args)

    node = GnssSatinfoVizNode()

    # Show the figure (non-blocking)
    plt.ion()
    plt.show(block=False)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        plt.close('all')
        rclpy.shutdown()


if __name__ == '__main__':
    main()
