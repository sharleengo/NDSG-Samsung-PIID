#!/bin/bash
python3 packet_capture.py &
nohup python3 -u pii_detector.py &
