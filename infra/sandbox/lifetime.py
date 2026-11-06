"""Trusted PID-1 child: cap container lifetime even if the worker disappears."""

import sys
import time

time.sleep(int(sys.argv[1]))
