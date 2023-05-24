'''
File: geometry_viewer.py
Project: example
Created Date: 21/10/2022
Author: Shun Suzuki
-----
Last Modified: 21/10/2022
Modified By: Shun Suzuki (suzuki@hapis.k.u-tokyo.ac.jp)
-----
Copyright (c) 2022 Shun Suzuki. All rights reserved.

'''


from pyautd3 import Controller, DEVICE_WIDTH, DEVICE_HEIGHT
from pyautd3.extra import GeometryViewer
from math import pi, sqrt

if __name__ == '__main__':
    autd = Controller()

    autd.geometry.add_device([0., 0., 0.], [0., 0., 0.])
    autd.geometry.add_device([DEVICE_WIDTH, 0., 0.], [0., -pi/3, 0.])
    autd.geometry.add_device([DEVICE_WIDTH, -DEVICE_HEIGHT - 25, 0.], [0., -pi/3, 0.])
    autd.geometry.add_device([0., -DEVICE_HEIGHT - 25, 0.], [0., 0., 0.])
    
    GeometryViewer().window_size(800, 600).vsync(True).view(autd.geometry)