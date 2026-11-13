import cv2
import numpy as np
import time
import datetime
from MutoLib import Muto
import socket, struct, io, ssl
from PIL import Image
import threading, queue
import random, math
from pathlib import Path

q = queue.Queue() # used with q.put(item) and q.get()
initiateFollow = queue.Queue()

# Convert image to bytestream (from instructor-provided code)
def pil_to_bytes(img: Image.Image, fmt="JPEG", q = 70) -> bytes:
    # Encode a PIL image to bytes (PNG/JPEG/etc.)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality = q)
    return buf.getvalue()

# ----------------------------
# Utilities
# ----------------------------

# ----------------------------
# Config: HSV color thresholds (tune to your lighting)
# Hue: 0..179, Sat/Val: 0..255
# ----------------------------
COLOR_RANGES = {
    "RED":    [((0,  40, 120), (10, 70, 255)), ((170, 80, 60), (179,255,255))],
    "GREEN":  [((35, 60, 60), (85,  255,255))],
    "BLUE":   [((70, 90, 90), (110,  255,255))],
    "YELLOW": [((20, 100, 100), (30, 255, 255))],
} # [((40, 200, 200), (120, 255, 255)), ((40, 80, 120), (70, 230, 255))]
LABEL_BGR = {
    "RED": (0,0,255), "GREEN": (0,255,0), "BLUE": (255,0,0),
    "YELLOW": (0,255,255)
}

# Expected ball radius range in pixels (set these for your scene!)
MIN_R, MAX_R = 12, 180

cascade_dir = Path(cv2.data.haarcascades) 
face_xml = cascade_dir / "haarcascade_frontalface_default.xml"
eye_xml  = cascade_dir / "haarcascade_eye.xml"

face = cv2.CascadeClassifier(str(face_xml))
eye  = cv2.CascadeClassifier(str(eye_xml))

scaling_factor = 0.5
waitTime = 5
show_mask = False
MASK_WIN = "Color Mask (union)"

if face.empty():
    raise IOError(f"Failed to load {face_xml}")

if eye.empty():
    raise IOError(f"Failed to load {eye_xml}")

# ----------------------------
# Utilities
# ----------------------------
def open_first_camera(indices=(0,1,2), backends=(cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY)):
    """Try several camera indices/backends and return the first that works."""
    for idx in indices:
        for be in backends:
            cap = cv2.VideoCapture(idx, be)
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    print(f"[OK] Camera index {idx} (backend={be})")
                    return cap
            cap.release()
    return None

def build_masks(hsv):
    """Return union mask and per-color masks (denoised)."""
    masks = {}
    union = np.zeros(hsv.shape[:2], np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
    for label, ranges in COLOR_RANGES.items():
        m = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            lo = np.array(lo, np.uint8); hi = np.array(hi, np.uint8)
            m |= cv2.inRange(hsv, lo, hi)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN,  k, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=1)
        masks[label] = m
        union |= m
    return union, masks

def classify_color_hsv(hsv, center, radius, min_coverage=0.25):
    """Pick the color occupying the most pixels inside the circle."""
    h, w = hsv.shape[:2]
    cx, cy, r = int(center[0]), int(center[1]), int(radius)
    circ = np.zeros((h, w), np.uint8)
    cv2.circle(circ, (cx, cy), r, 255, -1)
    area = math.pi * r * r

    best_label, best_score = "UNKNOWN", 0
    for label, ranges in COLOR_RANGES.items():
        m = np.zeros((h, w), np.uint8)
        for lo, hi in ranges:
            m |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        score = cv2.countNonZero(cv2.bitwise_and(m, circ))
        if score > best_score:
            best_label, best_score = label, score

    return best_label if best_score >= min_coverage * area else "UNKNOWN"

def detect_with_hough(gray_masked):
    circles = cv2.HoughCircles(
        gray_masked, cv2.HOUGH_GRADIENT,
        dp=1.25,          # 1.2–1.5; higher -> fewer circles
        minDist=40,       # spacing between centers
        param1=160,       # Canny high threshold
        param2=26,        # accumulator (raise if too many FPs, lower if none)
        minRadius=MIN_R,
        maxRadius=MAX_R
    )
    return None if circles is None else np.uint16(np.around(circles[0, :]))

def detect_with_contours(masks_per_color):
    """Fallback: find roughly circular blobs per color mask."""
    dets = []
    for label, m in masks_per_color.items():
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 200:
                continue
            perim = cv2.arcLength(c, True)
            if perim == 0:
                continue
            circularity = 4 * math.pi * area / (perim * perim)  # 1.0 = circle
            (x, y), r = cv2.minEnclosingCircle(c)
            if r < MIN_R or r > MAX_R:
                continue
            fill = area / (math.pi * r * r)
            if circularity >= 0.65 and fill >= 0.60:
                dets.append((int(x), int(y), int(r), label))
    return dets

def findUSB():
    for i  in range(0,5):
        try:
            print(f'ttyUSB{i}')
            g_bot = Muto(f'/dev/ttyUSB{i}')
        except:
            print(i)
            continue
        else:
            print('success')
            return i
    return -1

# ----------------------------
# Emotes
# ----------------------------

def wave(g_bot):
    for i in range(3):
        g_bot.motor(2, -90, 100)
        g_bot.motor(3, 90, 100)
        time.sleep(0.3)
        g_bot.stop()
        g_bot.reset()
        time.sleep(0.3)

def peacockSpider(g_bot):
    g_bot.motor(4, 45, 100)
    g_bot.motor(13, -45, 100)
    time.sleep(0.25)

    for i in range(3):
        g_bot.motor(2, -90, 400)
        g_bot.motor(3, 90, 400)
        g_bot.motor(17, -90, 400)
        g_bot.motor(18, 90, 400)
        time.sleep(0.5)
        g_bot.motor(2, -20, 400)
        g_bot.motor(3, -20, 400)
        g_bot.motor(17, -20, 400)
        g_bot.motor(18, -20, 400)
        time.sleep(0.3)
    
    g_bot.stop()
    g_bot.reset()
    
def sit(robot, speed = 2):
    # Movement
    robot.motor(8, -80, 100 * speed)
    robot.motor(11, -80, 100 * speed)
    time.sleep(0.5)
    
def lay(robot, speed = 5):
    robot.motor(8, -80, 100 * speed)
    robot.motor(11, -80, 100 * speed)
    time.sleep(0.5)
    robot.motor(14, -80, 100 * speed)
    robot.motor(5, -80, 100 * speed)
    time.sleep(0.5)
    robot.motor(2, -80, 100 * speed)
    robot.motor(17, -80, 100 * speed)
    time.sleep(0.5)
    
def dance(g_bot):
    shiftDown = 1
    shiftUp = 1
    for i in range(2):
        g_bot.motor(2, shiftDown, 100)
        g_bot.motor(5, shiftDown, 100)
        g_bot.motor(8, shiftDown, 100)

        g_bot.motor(12, shiftUp, 100)
        g_bot.motor(15, shiftUp, 100)
        g_bot.motor(18, shiftUp, 100)

        time.sleep(0.75)
        g_bot.stop()
        g_bot.reset()
        time.sleep(0.5)

        g_bot.motor(11, shiftDown, 100)
        g_bot.motor(14, shiftDown, 100)
        g_bot.motor(17, shiftDown, 100)

        g_bot.motor(3, shiftUp, 100)
        g_bot.motor(6, shiftUp, 100)
        g_bot.motor(9, shiftUp, 100)
        
        time.sleep(0.75)
        g_bot.stop()
        g_bot.reset()
        time.sleep(0.5)

def stretch(g_bot):
    shiftDown = 1
    shiftUp = 1
    g_bot.motor(2, shiftDown, 500)
    g_bot.motor(5, shiftDown, 500)
    g_bot.motor(8, shiftDown, 500)

    g_bot.motor(12, shiftUp, 500)
    g_bot.motor(15, shiftUp, 500)
    g_bot.motor(18, shiftUp, 500)

    time.sleep(2)
    g_bot.stop()
    g_bot.reset()
    time.sleep(0.5)

    g_bot.motor(11, shiftDown, 500)
    g_bot.motor(14, shiftDown, 500)
    g_bot.motor(17, shiftDown, 500)

    g_bot.motor(3, shiftUp, 500)
    g_bot.motor(6, shiftUp, 500)
    g_bot.motor(9, shiftUp, 500)
        
    time.sleep(2)
    g_bot.stop()
    g_bot.reset()
    time.sleep(0.5)
    
def frontStretch(g_bot):
    shiftDown = 8
    shiftUp = 10
    g_bot.motor(3, shiftUp, 500)
    g_bot.motor(18, shiftUp, 500)

    g_bot.motor(11, shiftDown, 500)
    g_bot.motor(8, shiftDown, 500)

    time.sleep(2)
    g_bot.stop()
    g_bot.reset()
    time.sleep(1)
    
def backStretch(g_bot):
    shiftDown = 8
    shiftUp = 10
    g_bot.motor(9, shiftUp, 500)
    g_bot.motor(12, shiftUp, 500)

    g_bot.motor(2, shiftDown, 500)
    g_bot.motor(17, shiftDown, 500)

    time.sleep(2)
    g_bot.stop()
    g_bot.reset()
    time.sleep(0.5)
    
def liftLeg(g_bot, legNo):
    shiftUp = -90
    legBendMotors = {1: 2, 2: 5, 3: 8, 4: 11, 5: 14, 6: 17}
    g_bot.motor(legBendMotors[legNo], shiftUp, 100)
    
def liftAllSolo(g_bot, speed = 1):
    shiftUp = -90
    legBendMotors = {1: 2, 2: 5, 3: 8, 4: 11, 5: 14, 6: 17}
    for i in range(1, len(legBendMotors) + 1):
        g_bot.motor(legBendMotors[i], shiftUp, 100 * speed)
        time.sleep(0.25)
        g_bot.stop()
        g_bot.reset()
        time.sleep(0.25)
        
def gaze(robot, speed = 5):
    robot.motor(8, -80, 100 * speed)
    robot.motor(11, -80, 100 * speed)
    time.sleep(0.5)
    robot.motor(14, -80, 100 * speed)
    robot.motor(5, -80, 100 * speed)
    time.sleep(0.5)
    
def slam(g_bot, speed = 5):
    g_bot.motor(4, 45, 100)
    g_bot.motor(13, -45, 100)
    time.sleep(0.25)

    g_bot.motor(2, -90, 100 * speed)
    g_bot.motor(3, 90, 100 * speed)
    g_bot.motor(17, -90, 100 * speed)
    g_bot.motor(18, 90, 100 * speed)
    time.sleep(1)
    g_bot.motor(2, 0, 100)
    g_bot.motor(3, 0, 100)
    g_bot.motor(17, 0, 100)
    g_bot.motor(18, 0, 100)
    time.sleep(0.3)
    
    g_bot.stop()
    g_bot.reset()
    
def shuffle(g_bot, speed = 1, negative = False, iterations = 3):
    for i in range(iterations):
        liftAllSolo(g_bot, speed)
        if negative:
            time.sleep(1)

def commandHandling(nxt, g_bot, sitting, laying, resetNeeded, following, idleTime, idleLowRange, idleHighRange, sittingIdle, layingIdle, idleIterations, positivity):
    # Returns values for sitting, laying, and resetNeeded
    gStep = 10
    movmentCmds = ['w', 's', 'a', 'd', 'g', 'l', 'r', 'q', 'shuffle', 'stretch', 
                   'forwardstretch', 'sit', 'lay', 'follow', 'dance', 'gaze', 'slam'
                ]
    if nxt in movmentCmds:
        resetNeeded = True
        idleIterations = 0
        if sitting or laying or sittingIdle or layingIdle:
            g_bot.stop()
            g_bot.reset()
            time.sleep(1)
            if laying or sitting: 
                frontStretch(g_bot)
                g_bot.stop()
                g_bot.reset()
                time.sleep(1)
            sitting, laying, sittingIdle, layingIdle = False, False, False, False 
        idleTime = time.time() + random.randint(idleLowRange, idleHighRange)
    if nxt == 'w':
        print('Moving forward.')
        g_bot.forward(gStep)
        time.sleep(3)
        g_bot.stop()
        g_bot.reset()
    elif nxt == 's':
        print('Moving backward.')
        g_bot.back(gStep)
        time.sleep(3)
        g_bot.stop()
        g_bot.reset()
    elif nxt == 'a':
        print('Moving left.')
        g_bot.left(gStep)
        time.sleep(3)
        g_bot.stop()
        g_bot.reset()
    elif nxt == 'd':
        print('Moving right.')
        g_bot.right(gStep)
        time.sleep(3)
        g_bot.stop()
        g_bot.reset()
    elif nxt == 'g':
        print('Waving.')
        wave(g_bot)
    elif nxt == 'l':
        print('Turning left.')
        g_bot.turnleft(gStep)
        time.sleep(3)
        g_bot.stop()
        g_bot.reset()
    elif nxt == 'r':
        print('Turning right.')
        g_bot.turnright(gStep)
        time.sleep(3)
        g_bot.stop()
        g_bot.reset()
    elif nxt == 'q':
        print('Waving like a peacock spider.')
        peacockSpider(g_bot)
    elif nxt == 'sit':
        if positivity < -0.4:
            print('Sitting slowly.')
            sit(g_bot, 5)
        else:
            print('Sitting.')
            sit(g_bot)
        sitting = True
    elif nxt == 'lay':
        if positivity < -0.4:
            print('Laying slowly.')
            lay(g_bot, 8)
        else:
            print('Laying.')
            lay(g_bot)
        laying = True
    elif nxt == 'follow':
        if sitting or laying:
            sitting, laying = False, False
            g_bot.stop()
            g_bot.reset()
            time.sleep(1)
        print('Following.')
        initiateFollow.put('follow')
        following = True
    elif nxt == 'shuffle':
        if positivity < -0.4:
            print('Shuffling slowly.')
            shuffle(g_bot, 5, True, 2)
        elif positivity > 0.4:
            print('Shuffling quickly.')
            shuffle(g_bot)
        else:
            print('Shuffling at medium speed.')
            shuffle(g_bot, 3)
    elif nxt == 'stretch':
        print('Stretching.')
        stretch(g_bot)
    elif nxt == 'forwardstretch':
        print('Stretching forward.')
        frontStretch(g_bot)
    elif nxt == 'dance':
        print('Dancing side-to-side.')
        dance(g_bot)
    elif nxt == 'slam':
        print('Slamming front legs into surface.')
        slam(g_bot)
    elif nxt == 'gaze':
        if positivity < -0.4:
            print('Gazing with gradual transition.')
            gaze(g_bot, 8)
        else:
            print('Gazing.')
            gaze(g_bot)
        laying = True
    return sitting, laying, resetNeeded, following, idleTime, sittingIdle, layingIdle, idleIterations

def modifyEmotion(cmd, cmdHistory, positivity, mvmtPositivity, mvntNegativity, mvntTolerance):
    if cmd not in cmdHistory:
        cmdHistory = []
        cmdHistory.append(cmd)
    else:
        cmdHistory.append(cmd)
    if cmd in mvmtPositivity:
        modifier = 0
        if len(cmdHistory) > mvntTolerance[cmd]:
            modifier = -mvntNegativity[cmd]
        else:
            modifier = mvmtPositivity[cmd]
        positivity += modifier
        positivity = 1 if (positivity > 1) else (-1 if (positivity < -1) else positivity)
    return cmdHistory, positivity
    
# ----------------------------
# Main
# ----------------------------

def connectionThread():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ip = input('Enter the IP you are connecting to, otherwise leave empty for local host: ')
    if ip == '':
        ip = 'localhost'
    client_socket.connect((ip, 5050))
    q.put(ip)
    print("Connected to server in the connection thread.")
    
    while True:
        nxt = client_socket.recv(1024)
        nxt = nxt.decode()
        print('Continuing.')
        if nxt == 'END':
            q.put('END')
            client_socket.close()
            break
        else:
            q.put(nxt)
    print('Connection thread ended.')
            
def followThread(cap, g_bot):
    while True:
        nxt = initiateFollow.get()
        print('Follow First Command Received:', nxt)
        if nxt == 'END':
            break
        elif nxt == 'follow':
            print('Entering follow state.')
            tCapB = datetime.datetime.now()
            tCapB = tCapB.microsecond
            timeBegin = datetime.datetime.now()
            faceFound = False
            while True:
                nxt2 = 0
                try:
                    nxt2 = initiateFollow.get(block = False)
                    print('Follow Second Command:', nxt2)
                except:
                    nxt2 = None
                if nxt2 == 'END':
                    print('Exiting follow state.')
                    break
                else:
                    tCapL = datetime.datetime.now()
                    tCapL = tCapL.microsecond

                    tCapB = datetime.datetime.now()
                    tCapB = tCapB.microsecond
                    ok, frame = cap.read()
                    if not ok:
                        continue

                    # Optional resize for speed; comment out to use full resolution
                    frame = cv2.resize(frame, None, 
                        fx=scaling_factor, fy=scaling_factor, 
                        interpolation=cv2.INTER_AREA)

                    blur = cv2.GaussianBlur(frame, (7,7), 0)
                    hsv  = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
                    union_mask, masks_per_color = build_masks(hsv)

                    # Hough on masked grayscale
                    gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
                    face_rects = face.detectMultiScale(gray, 1.3, 5)
                    gray_masked = cv2.bitwise_and(gray, gray, mask=union_mask)
                    circles = detect_with_hough(gray_masked)

                    output = frame.copy()
                    detections = []

                    if circles is not None and len(circles) > 0:
                        for (x, y, r) in circles:
                            label = classify_color_hsv(hsv, (x, y), r, min_coverage=0.25)
                            if label != "UNKNOWN":
                                detections.append((x, y, r, label))

                    # Fallback if Hough found nothing useful
                    if len(detections) == 0:
                        detections = detect_with_contours(masks_per_color)

                    # Draw
                    if detections:
                        for (x, y, r, label) in detections:
                            cv2.circle(output, (x, y), r, (255,255,255), 2)
                            cv2.circle(output, (x, y), 2, (255,255,255), 3)
                            cv2.putText(output, label, (x - r, max(22, y - r - 8)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, LABEL_BGR[label], 2, cv2.LINE_AA)

                        for (x, y, r, label) in detections:
                            if 'green' in label.lower():
                                if x > 225:
                                    g_bot.turnright(10)
                                    print('Right')
                                elif x < 125:
                                    g_bot.turnleft(10)
                                    print('Left')
                                else:
                                    print('Forward')
                                    g_bot.forward(10)
                                    
                    else:
                        g_bot.reset()
                        g_bot.stop()
                        cv2.putText(output, "No balls detected", (18, 28),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2, cv2.LINE_AA)

                    # Draw rectangle around face
                    for (x,y,w,h) in face_rects:
                        cv2.rectangle(output, (x,y), (x+w,y+h), (0,255,0), 3)
                        # Reset timer if no face
                        if not faceFound:
                            timeBegin = datetime.datetime.now()
                            timeBegin = timeBegin.second
                            faceFound = True
                        else:
                            timeNow = datetime.datetime.now()
                            timeNow = timeNow.second
                            if abs(timeBegin - timeNow) > waitTime:
                                faceFound = False
                                print('Waving like a peacock spider.')
                                peacockSpider(g_bot)
                                timeBegin = datetime.datetime.now()
                                timeBegin = timeBegin.second                 
                                
                    if len(face_rects) == 0:
                        faceFound = False

    print('Follow thread ended.')

def robotControlThread(cap, g_bot):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ip = q.get()
    client_socket.connect((ip, 5051))
    print("Connected to server in the robot control thread.")
    gStep = 10
    # Open camera
    
    idleLowRange = 9
    idleHighRange = 24
    
    idleTime = time.time() + random.randint(idleLowRange, idleHighRange)
    following = False
    idling = False
    sitting = False
    laying = False
    resetNeeded = False
    layingIdle, sittingIdle = False, False
    timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)

    positivity = 0.5
    cmdHistory = []
    mvmtPositivity = {'reset' : 0.1, 'w' : 0.1, 's' : 0.1, 'a' : 0.1, 'd' : 0.1, 'g'  : 0.2, 'l' : 0.1, 'r' : 0.1, 'q' : 0.2, 
                      'shuffle' : 0.2, 'stretch' : 0.1, 'forwardstretch' : 0.1, 'p' : 0.05, 'follow' : 0.5, 'lay': 0.1, 'sit': 0.1,
                      'dance' : 0.3, 'slam' : 0.1, 'gaze': 0.1
                      }
    mvntNegativity = {'reset' : 0.2, 'w' : 0.2, 's' : 0.2, 'a' : 0.2, 'd' : 0.2, 'g'  : 0.1, 'l' : 0.2, 'r' : 0.2, 'q' : 0.1, 
                      'shuffle' : 0.4, 'stretch' : 0.1, 'forwardstretch' : 0.1, 'p' : 0.05, 'follow' : 0.3, 'lay': 0.2, 'sit': 0.2,
                      'dance' : 0.4, 'slam' : 0.2, 'gaze' : 0.2
                      }
    mvntTolerance = {'reset' : 2, 'w' : 3, 's' : 3, 'a' : 3, 'd' : 3, 'g'  : 2, 'l' : 3, 'r' : 3, 'q' : 2, 
                      'shuffle' : 1, 'stretch' : 2, 'forwardstretch' : 2, 'p' : 2, 'follow' : 1, 'lay': 4, 'sit': 4,
                      'dance': 1, 'slam': 2, 'gaze': 4
                    }
    idleIterations = 0
    
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        
        nxt = 0
        try:
            nxt = q.get(block = False)
            print('Control Thread Command Received:', nxt)
        except:
            nxt = None

        if nxt != None and nxt != 'END' and not following:
            cmdHistory, positivity = modifyEmotion(nxt, cmdHistory, positivity, mvmtPositivity, mvntNegativity, mvntTolerance)
            if positivity > 0.4: 
                print('Setting speed to fast based on positive mood.')
                g_bot.speed(5) 
            elif positivity < -0.4:
                print('Setting speed to slow based on negative mood.')
                g_bot.speed(1)
            else:
                print('Setting speed to medium based on neutral mood.')
                g_bot.speed(3)
            
        if nxt == 'END':
            print('Ending program.')
            initiateFollow.put('END')
            initiateFollow.put('END')
            break
        elif nxt == 'p' and not following:
            idleIterations = 0
            ok, frame = cap.read()
            print('Photo taken.')
            # Optional resize for speed; comment out to use full resolution
            max_w = 960
            if frame.shape[1] > max_w:
                s = max_w / frame.shape[1]
            frame = cv2.resize(frame, (640, 480))
                
            output = frame.copy()

            #cv2.imshow("Muto RS Camera", output)
            timeLater = datetime.datetime.now()
            timeLater = timeLater.microsecond
            
            timeBegin = datetime.datetime.now()
            timeBegin = timeBegin.microsecond
            cv2.imwrite('snapshotMuto.jpg', output)
            print('Photo saved.')
            img = Image.open('snapshotMuto.jpg').convert('RGB')
            payload = pil_to_bytes(img)
            client_socket.sendall(struct.pack(">Q", len(payload)))
            client_socket.sendall(payload)
            img.close()
            print('Photo sent sucessfully.')

        elif nxt == 'reset':
            print('Resetting robot.')
            if following:
                initiateFollow.put('END')
            g_bot.stop()
            g_bot.reset()
            time.sleep(1)
            if laying or sitting:
                print('Stretching forward.')
                frontStretch(g_bot)
                g_bot.stop()
                g_bot.reset()
                time.sleep(1)
            following = False
            sitting = False
            laying = False
            sittingIdle, layingIdle = False, False
            resetNeeded = False
            idling = False
            idleIterations = 0
            idleTime = time.time() + random.randint(idleLowRange, idleHighRange)

        elif not following:
            if nxt == None and not idling and not sitting and not laying and resetNeeded:
                g_bot.stop()
                g_bot.reset()
                resetNeeded = False
                #print('Resetting position out of idle.')
            if laying or sitting:
                idleTime = time.time() + random.randint(idleLowRange, idleHighRange)

            sitting, laying, resetNeeded, following, idleTime, sittingIdle, layingIdle, idleIterations = commandHandling(nxt, g_bot, sitting, laying, resetNeeded, 
                                                                                                                            following, idleTime, idleLowRange, idleHighRange, sittingIdle, 
                                                                                                                            layingIdle, idleIterations, positivity
                                                                                                                        )
            
            # Begin idle
            if nxt == None and not following and time.time() > idleTime and not sitting and not laying:
                print('Entering idle state.')
                idleIterations += 1
                if idleIterations > 6:
                    positivity -= 0.2
                    positivity = 1 if (positivity > 1) else (-1 if (positivity < -1) else positivity)
                elif idleIterations > 3:
                    positivity -= 0.1
                    positivity = 1 if (positivity > 1) else (-1 if (positivity < -1) else positivity)
                g_bot.stop()
                g_bot.reset()
                time.sleep(1)

                if positivity < -0.4: # Negative
                    determineState = random.randint(0, 10)
                    if determineState < 3:
                        print('Shuffling.')
                        shuffle(g_bot, 5, True, 2)
                    elif determineState < 6:
                        print('Laying.')
                        lay(g_bot, 8)
                        layingIdle, laying = True, True
                        timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)
                    elif determineState < 7:
                        print('Sitting.')
                        sit(g_bot, 5)
                        sittingIdle, sitting = True, True
                        timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)
                    elif determineState < 9:
                        print('Gazing.')
                        gaze(g_bot, 8)
                        layingIdle, laying = True, True
                        timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)
                    elif determineState < 11:
                        print('Slamming front legs into surface.')
                        slam(g_bot)

                elif positivity > 0.4: # Positive
                    determineState = random.randint(0, 10)
                    if determineState < 2:
                        print('Shuffling.')
                        shuffle(g_bot)
                    elif determineState < 5:
                        print('Waving.')
                        wave(g_bot)
                    elif determineState < 8:
                        print('Waving like a peacock spider.')
                        peacockSpider(g_bot)
                    elif determineState < 10:
                        print('Dancing.')
                        dance(g_bot)
                    elif determineState < 11:
                        print('Laying down.')
                        lay(g_bot)
                        layingIdle, laying = True, True
                        timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)

                else: # Neutral
                    determineState = random.randint(0, 4)
                    if determineState == 0:
                        print('Sitting down.')
                        sit(g_bot)
                        sittingIdle, sitting = True, True
                        timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)
                    elif determineState == 1:
                        print('Laying down.')
                        lay(g_bot)
                        layingIdle, laying = True, True
                        timerForIdleAction = time.time() + random.randint(idleLowRange//2, idleHighRange//2)
                    elif determineState == 2:
                        print('Stretching side-to-side.')
                        stretch(g_bot)
                    elif determineState == 3:
                        print('Stretching towards the front.')
                        frontStretch(g_bot)
                    elif determineState == 4:
                        print('Shuffling.')
                        shuffle(g_bot, 3)

                idleTime = time.time() + random.randint(idleLowRange, idleHighRange)
            elif nxt == None and not following and time.time() > timerForIdleAction and (sittingIdle or layingIdle):
                print('Standing up.')
                g_bot.stop()
                g_bot.reset()
                time.sleep(1)
                if laying or sitting:
                    print('Stretching forward.')
                    frontStretch(g_bot)
                    g_bot.stop()
                    g_bot.reset()
                    time.sleep(1)
                sitting, laying, sittingIdle, layingIdle = False, False, False, False
                idleTime = time.time() + random.randint(idleLowRange, idleHighRange)

    client_socket.close()
    g_bot.stop()
    g_bot.reset()
    print('Robot control thread ended.')

def main():
    g_bot = Muto(f'/dev/ttyUSB{findUSB()}')
    #g_bot = None # Robotless client only
    cap = open_first_camera()
            
    if cap is None:
        raise SystemExit("[ERR] No working camera found. Close other apps or try a different index.")
        
    cv2.namedWindow("Muto RS Camera", cv2.WINDOW_NORMAL)
    print("Press 'q' or Esc = quit.")
    t1 = threading.Thread(target = connectionThread)
    t2 = threading.Thread(target = robotControlThread, args = (cap, g_bot))
    t3 = threading.Thread(target = followThread, args = (cap, g_bot))
    threads = [t1, t2, t3]
    
    # Start threads
    for t in threads:
        t.start()
    
    # Wait for threads to finish
    for t in threads:
        t.join()
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()