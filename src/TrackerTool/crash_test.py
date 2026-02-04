# crash_test.py
import time, os
print("Fake eSim.exe will abort in 2 seconds...")
time.sleep(2)
os.abort()
