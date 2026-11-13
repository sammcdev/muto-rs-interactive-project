import numpy as np
import cv2 as cv
from matplotlib import pyplot as plt

def open_first_camera(indices=(0,1,2), backends=(cv.CAP_DSHOW, cv.CAP_MSMF, cv.CAP_ANY)):
    """Try several camera indices/backends and return the first that works."""
    for idx in indices:
        for be in backends:
            cap = cv.VideoCapture(idx, be)
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    print(f"[OK] Camera index {idx} (backend={be})")
                    return cap
            cap.release()
    return None

cv.namedWindow("Ball Color Detector (R/G/B/Y)", cv.WINDOW_NORMAL)
cap = open_first_camera()
if cap is None:
    raise SystemExit("[ERR] No working camera found. Close other apps or try a different index.")


ok, output = cap.read()
cv.imshow("Ball Color Detector (R/G/B/Y)", output)
while True:
    
    ok, output = cap.read()
    
    
    img = output.copy()
    assert img is not None, "file could not be read, check with os.path.exists()"
    edges = cv.Canny(img,100,200)
    cv.imshow("Ball Color Detector (R/G/B/Y)", edges)
    
    key = cv.waitKey(1) & 0xFF
    if key in (27, ord('q'), ord('Q')):
        break

plt.show()