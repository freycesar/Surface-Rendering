'''
Author: Mingxin Zhang m.zhang@hapis.k.u-tokyo.ac.jp
Date: 2022-11-22 22:42:58
LastEditors: Mingxin Zhang
LastEditTime: 2023-08-16 16:46:33
Copyright (c) 2022 by Mingxin Zhang, All Rights Reserved. 
'''

from pyautd3.link import TwinCAT, SOEM, Simulator, OnLostFunc
from pyautd3.gain import Focus
from pyautd3 import AUTD3, Controller, Geometry, SilencerConfig, Synchronize, Stop, DEVICE_WIDTH, DEVICE_HEIGHT
from pyautd3.modulation import Static, Sine
import numpy as np
import ctypes
import platform
import os
import pyrealsense2 as rs
import cv2
import mediapipe as mp
import math
from math import pi
from multiprocessing import Process, Pipe
import time

# use cpp to get high precision sleep time
dll = ctypes.cdll.LoadLibrary
libc = dll(os.path.dirname(__file__) + '/../cpp/' + platform.system().lower() + '/HighPrecisionTimer.so') 

W = 640
H = 480

def on_lost(msg: ctypes.c_char_p):
    print(msg.decode('utf-8'), end="")
    os._exit(-1)

def run(subscriber, publisher):
    # Multiple AUTD
    # The arrangement of the AUTDs:
    # 1 → 2
    #     ↓
    # 4 ← 3
    # (See from the upside)

    W_cos = math.cos(math.pi/12) * DEVICE_WIDTH

    on_lost_func = OnLostFunc(on_lost)

    autd = (
        Controller.builder()
        .add_device(AUTD3.from_euler_zyz([W_cos - (DEVICE_WIDTH - W_cos), DEVICE_HEIGHT - 10 + 12.5, 0.], [pi, pi/12, 0.]))
        .add_device(AUTD3.from_euler_zyz([W_cos - (DEVICE_WIDTH - W_cos), -10 - 12.5, 0.], [pi, pi/12, 0.]))
        .add_device(AUTD3.from_euler_zyz([-W_cos + (DEVICE_WIDTH - W_cos),  12.5, 0.], [0., pi/12, 0.]))
        .add_device(AUTD3.from_euler_zyz([-W_cos + (DEVICE_WIDTH - W_cos), -DEVICE_HEIGHT - 12.5, 0.], [0., pi/12, 0.]))
        .advanced_mode()
        # .open_with(Simulator(8080))
        .open_with(SOEM().with_on_lost(on_lost_func))
        # .open_with(TwinCAT())
    )

    autd.send(Synchronize())

    print('================================== Firmware information ====================================')
    firm_info_list = autd.firmware_info_list()
    for firm in firm_info_list:
        print(firm)
    print('============================================================================================')

    center = autd.geometry.center + np.array([0., 0., 0.])

    m = Static()
    # m = Sine(150)

    radius = 1.0    # radius of STM
    zero_radius = 1.0
    step = 0.2      # step length (mm)
    stm_f = 6.0     # frequency of STM
    theta = 0
    height = 200.   # init x, y, height
    x = 0.
    y = 0.
    zero_height = 200.
    config = SilencerConfig()
    autd.send(config)

    print('press ctrl+c to finish...')

    subscriber.close()

    try:
        while True:
            # update the focus information
            p = radius * np.array([np.cos(theta), np.sin(theta), 0])
            p += np.array([x, y, height])
            f = Focus(center + p)
            autd.send((m, f))

            # ... change the radius and height here
            if publisher.poll():
                coordinate = publisher.recv()
                x = coordinate[0]
                y = coordinate[1]
                # height of D435i: 25mm
                # D435i depth start point: -4.2mm
                height = coordinate[2] - 4 - 4.2
            
            delta_height = zero_height - height
            radius = zero_radius + min(20, max(delta_height, 0)) * 0.25

            theta += step / radius
            size = 2 * np.pi * radius // step   # recalculate the number of points in a round
            time_step = (1 / stm_f) / size  # recalculate time step
            libc.HighPrecisionSleep(ctypes.c_float(time_step))  # cpp sleep function

    except KeyboardInterrupt:
        pass

    print('finish.')
    autd.send(Stop())
    publisher.close()

    autd.close()


def get_finger_distance(subscriber, publisher):
    # Initialization hand tracking
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles
    mp_hands = mp.solutions.hands
    pipeline = rs.pipeline()
    config = rs.config()

    # Get device product line for setting a supporting resolution
    pipeline_wrapper = rs.pipeline_wrapper(pipeline)
    pipeline_profile = config.resolve(pipeline_wrapper)
    device = pipeline_profile.get_device()

    # Judge whether there is rgb input
    found_rgb = False
    for s in device.sensors:
        if s.get_info(rs.camera_info.name) == 'RGB Camera':
            found_rgb = True
            break
    if not found_rgb:
        print("The demo requires Depth camera with Color sensor")
        exit(0)

    # Decide resolutions for both depth and rgb streaming
    config.enable_stream(rs.stream.depth, W, H, rs.format.z16, 30)
    config.enable_stream(rs.stream.color, W, H, rs.format.bgr8, 30)

    # Start streaming
    profile = pipeline.start(config)

    # Create an align object
    # rs.align allows us to perform alignment of depth frames to others frames
    # The "align_to" is the stream type to which we plan to align depth frames.
    align_to = rs.stream.color
    align = rs.align(align_to)

    publisher.close()

    try:
        with mp_hands.Hands(model_complexity=0, min_detection_confidence=0.5, min_tracking_confidence=0.5) as hands:
            while True:
                # Get frameset of color and depth
                frames = pipeline.wait_for_frames()
                # frames.get_depth_frame() is a 640x360 depth image

                # Align the depth frame to color frame
                aligned_frames = align.process(frames)

                # Get aligned frames
                depth_frame = aligned_frames.get_depth_frame() # depth_frame is a 640x480 depth image
                color_frame = aligned_frames.get_color_frame()

                # Validate that both frames are valid
                if not depth_frame or not color_frame:
                    continue

                color_image = np.asanyarray(color_frame.get_data())      

                results = hands.process(color_image)

                color_image.flags.writeable = True

                if results.multi_hand_landmarks:
                    for hand_landmarks in results.multi_hand_landmarks:
                        mp_drawing.draw_landmarks(
                            color_image,
                            hand_landmarks,
                            mp_hands.HAND_CONNECTIONS,
                            mp_drawing_styles.get_default_hand_landmarks_style(),
                            mp_drawing_styles.get_default_hand_connections_style())

                        x_index = math.floor(hand_landmarks.landmark[8].x * W)
                        y_index = math.floor(hand_landmarks.landmark[8].y * H)
                        cv2.circle(color_image, (x_index, y_index), 10, (0, 0, 255))
                        # print(x_index, y_index)
                        # print(hand_landmarks.landmark[8].x, hand_landmarks.landmark[8].y)
                        finger_dis = 1000 * depth_frame.get_distance(x_index, y_index)  # meter to mm
                        
                        # rgb fov of D435i: 69° x 42°
                        ang_x = math.radians((x_index - W / 2) / (W / 2) * (69 / 2))
                        ang_y = math.radians((y_index - H / 2) / (H / 2) * (42 / 2))
                        x_dis = math.tan(ang_x) * finger_dis
                        y_dis = math.tan(ang_y) * finger_dis
                        print('xyz coordinate: ', x_dis, y_dis, finger_dis)
                        subscriber.send([x_dis, y_dis, finger_dis])

                # Flip the image horizontally for a selfie-view display.
                cv2.imshow('MediaPipe Hands', cv2.flip(color_image, 1))

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    finally:
        # Stop streaming
        pipeline.stop()
        cv2.destroyAllWindows()
        subscriber.close()


if __name__ == '__main__':
    subscriber, publisher = Pipe()

    p_main = Process(target=run, args=(subscriber, publisher))
    p_main.start()

    get_finger_distance(subscriber, publisher)

    publisher.close()
    subscriber.close()

    p_main.join()