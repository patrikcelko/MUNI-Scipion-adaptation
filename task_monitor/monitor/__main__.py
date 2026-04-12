"""
Task monitor entry point
========================
"""

from monitor.ui import TaskMonitor


def main() -> None:
    """Create and run the monitor window."""

    app = TaskMonitor()
    app.mainloop()


if __name__ == '__main__':
    main()
