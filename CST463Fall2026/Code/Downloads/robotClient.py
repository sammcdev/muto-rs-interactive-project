import cv2
import numpy as np
import time
import datetime
from MutoLib import Muto
import socket, struct, io, ssl
from PIL import Image
import threading, queue

q = queue.Queue() # used with q.put(item) and q.get()

# Convert image to bytestream (from instructor-provided code)
def pil_to_bytes(img: Image.Image, fmt="JPEG", q = 70) -> bytes:
    # Encode a PIL image to bytes (PNG/JPEG/etc.)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality = q)
    return buf.getvalue()

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
        g_bot.motor(2, -90, 200)
        g_bot.motor(3, 90, 200)
        g_bot.motor(17, -90, 200)
        g_bot.motor(18, 90, 200)
        time.sleep(0.5)
        g_bot.motor(2, 0, 200)
        g_bot.motor(3, 0, 200)
        g_bot.motor(17, 0, 200)
        g_bot.motor(18, 0, 200)
        time.sleep(0.3)
    
    g_bot.stop()
    g_bot.reset()
    
def sit(robot):
    # Movement
    #robot.motor(9, 45, 200)
    robot.motor(8, -80, 200)
    #obot.motor(12, -45, 200)
    robot.motor(11, -80, 200)
    time.sleep(0.5)
    
def lay(robot):
    robot.motor(8, -80, 200)
    robot.motor(11, -80, 200)
    time.sleep(0.5)
    robot.motor(14, -80, 200)
    robot.motor(5, -80, 200)
    time.sleep(0.5)
    robot.motor(2, -80, 200)
    robot.motor(17, -80, 200)
    time.sleep(0.5)

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
    print("Connected to server.")
    
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

def robotControlThread():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ip = q.get()
    client_socket.connect((ip, 5051))
    print("Connected to server.")
    g_bot = Muto(f'/dev/ttyUSB{findUSB()}')
    gStep = 10
    # Open camera
    cap = open_first_camera()
        
    if cap is None:
        raise SystemExit("[ERR] No working camera found. Close other apps or try a different index.")
    
    cv2.namedWindow("Muto RS Camera", cv2.WINDOW_NORMAL)
    print("Press 'q' or Esc = quit.")
    ok, frame = cap.read()
    
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
    
        nxt = q.get()
        if nxt == 'END':
            break
        elif nxt == 'p':
            ok, frame = cap.read()
            # Optional resize for speed; comment out to use full resolution
            max_w = 960
            if frame.shape[1] > max_w:
                s = max_w / frame.shape[1]
            frame = cv2.resize(frame, (640, 480))
                
            output = frame.copy()
    
            cv2.imshow("Muto RS Camera", output)
            timeLater = datetime.datetime.now()
            timeLater = timeLater.microsecond
                
            timeBegin = datetime.datetime.now()
            timeBegin = timeBegin.microsecond
            cv2.imwrite('snapshotMuto.jpg', output)
            img = Image.open('snapshotMuto.jpg').convert('RGB')
            payload = pil_to_bytes(img)
            client_socket.sendall(struct.pack(">Q", len(payload)))
            client_socket.sendall(payload)
            img.close()
                #key = cv2.waitKey(1) & 0xFF
                #if key in (27, ord('q'), ord('Q')):
                    #client_socket.sendall('END'.encode())
                    #break
                #else:
                    #client_socket.sendall('CONTINUE'.encode())
        else:
            g_bot.stop()
            g_bot.reset()
            if nxt == 'w':
                g_bot.forward(gStep)
                time.sleep(3)
                g_bot.stop()
                g_bot.reset()
            elif nxt == 's':
                g_bot.back(gStep)
                time.sleep(3)
                g_bot.stop()
                g_bot.reset()
            elif nxt == 'a':
                g_bot.left(gStep)
                time.sleep(3)
                g_bot.stop()
                g_bot.reset()
            elif nxt == 'd':
                g_bot.right(gStep)
                time.sleep(3)
                g_bot.stop()
                g_bot.reset()
            elif nxt == 'g':
                wave(g_bot)
            elif nxt == 'l':
                g_bot.turnleft(gStep)
                time.sleep(3)
                g_bot.stop()
                g_bot.reset()
            elif nxt == 'r':
                g_bot.turnleft(gStep)
                time.sleep(3)
                g_bot.stop()
                g_bot.reset()
            elif nxt == 'q':
                peacockSpider(g_bot)
            elif nxt == 'sit':
                sit(g_bot)
            elif nxt == 'lay':
                lay(g_bot)
            
            #serverEnd = client_socket.recv(1024).decode()
            #if serverEnd == 'END':
                #break
        
    cap.release()
    cv2.destroyAllWindows()
    client_socket.close()

def main():
    t1 = threading.Thread(target = connectionThread)
    t2 = threading.Thread(target = robotControlThread)
    threads = [t1, t2]
    
    # Start threads
    for t in threads:
        t.start()
    
    # Wait for threads to finish
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()			
