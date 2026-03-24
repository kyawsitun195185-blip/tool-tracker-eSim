import time
import pyautogui

print("Move mouse to TOP-LEFT of the eSim console in 5 seconds...")
time.sleep(5)
x1, y1 = pyautogui.position()
print("Top-left:", x1, y1)

print("Move mouse to BOTTOM-RIGHT of the eSim console in 5 seconds...")
time.sleep(5)
x2, y2 = pyautogui.position()
print("Bottom-right:", x2, y2)

print("BBOX =", (x1, y1, x2, y2))
