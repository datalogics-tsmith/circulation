#!/usr/bin/env python
"""Make books presentation ready by asking the metadata wrangler about them."""
import os
import sys
bin_dir = os.path.split(__file__)[0]
package_dir = os.path.join(bin_dir, "..")
sys.path.append(os.path.abspath(package_dir))
from monitor import (
    LicensePoolButNoWorkPresentationReadyMonitor,
)
from core.scripts import RunMonitorScript
RunMonitorScript(LicensePoolButNoWorkPresentationReadyMonitor).run()
