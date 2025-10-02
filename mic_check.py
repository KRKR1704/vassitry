# mic_check.py — lists devices and shows live RMS so you can pick the right mic
# Works with older pvrecorder (uses get_available_devices() fallback).

import math
from pvrecorder import PvRecorder

def list_devices():
    try:
        # Newer pvrecorder (>=1.2.2)
        devices = PvRecorder.get_audio_devices()
    except AttributeError:
        # Older pvrecorder
        devices = PvRecorder.get_available_devices()
    return devices

def main():
    devices = list_devices()
    print("[Ultron] Audio devices:")
    for i, name in enumerate(devices):
        print(f"  {i}: {name}")

    raw = input("Enter the index of your microphone (-1 for default): ").strip() or "-1"
    try:
        idx = int(raw)
    except ValueError:
        idx = -1

    # frame_length doesn’t affect the RMS meter much; 512 is fine
    recorder = PvRecorder(device_index=idx, frame_length=512)
    recorder.start()
    print("[Ultron] Listening... speak; press Ctrl+C to stop.")

    try:
        while True:
            # pvrecorder.read() returns a list of int16 samples
            pcm = recorder.read()
            # Compute simple RMS to show activity
            rms = math.sqrt(sum(s * s for s in pcm) / len(pcm))
            print(f"RMS: {rms:7.1f} (device {idx})", end="\r")
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()
        recorder.delete()
        print("\n[Ultron] Stopped.")

if __name__ == "__main__":
    main()
